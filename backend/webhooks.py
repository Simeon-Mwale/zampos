# backend/webhooks.py
"""
ZamPOS Webhook Handler
──────────────────────
Handles Voltage payment confirmation events.

On invoice.settled:
  1. Mark transaction as paid in DB
  2. Calculate gas fee (50 sats flat)
  3. Sweep net sats to owner Phoenix wallet
  4. Log gas fee to DB
"""

import logging
from database import mark_paid, get_transaction_by_hash
from services.fee_engine import calculate_gas_fee, log_gas_fee
from services.phoenix_sweep import sweep_to_phoenix
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def handle_voltage_webhook(payload: Dict[str, Any], background_tasks) -> bool:
    """
    Process Voltage webhook events.

    Expected payload structure:
    {
      "event": "invoice.settled",
      "data": {
        "payment_hash": "abc123...",
        "amount": 1000,          ← amount in sats
        "memo": "ZamPOS...",
        "settled_at": "2024-01-15T10:30:00Z"
      },
      "timestamp": 1705315800
    }
    """
    event = payload.get("event")
    data = payload.get("data", {})
    payment_hash = data.get("payment_hash")

    if not payment_hash:
        logger.warning(f"⚠️ Webhook missing payment_hash: {payload}")
        return False

    # ── Payment confirmed ──────────────────────────────────────────────────────
    if event in ["invoice.settled", "payment.received"]:
        logger.info(f"✅ Webhook: Payment settled {payment_hash[:12]}...")

        # 1. Mark paid in local DB
        success = await mark_paid(payment_hash)
        if not success:
            logger.warning(f"⚠️ Could not mark paid for {payment_hash}")

        # 2. Fetch transaction to get amount + merchant
        tx = await get_transaction_by_hash(payment_hash)
        if not tx:
            logger.warning(
                f"⚠️ Transaction not found in DB for {payment_hash[:12]}... "
                f"— skipping sweep (invoice may have been created before gas fee update)"
            )
            return True

        gross_sats = tx.get("amount_sats", 0)
        merchant_id = tx.get("merchant_id")

        if not gross_sats or gross_sats <= 0:
            logger.warning(f"⚠️ Invalid amount_sats={gross_sats} for {payment_hash[:12]}...")
            return True

        # 3. Calculate gas fee
        fee_result = calculate_gas_fee(gross_sats)

        logger.info(
            f"💰 Fee calc | gross={fee_result['gross_sats']} "
            f"fee={fee_result['fee_sats']} net={fee_result['net_sats']} "
            f"sweepable={fee_result['sweepable']}"
        )

        if not fee_result["sweepable"]:
            logger.warning(
                f"⚠️ Skipping sweep for {payment_hash[:12]}...: {fee_result['reason']}"
            )
            return True

        # 4. Sweep net sats to Phoenix (run in background — don't block webhook response)
        background_tasks.add_task(
            _sweep_and_log,
            payment_hash=payment_hash,
            merchant_id=merchant_id,
            gross_sats=fee_result["gross_sats"],
            fee_sats=fee_result["fee_sats"],
            net_sats=fee_result["net_sats"],
        )

        return True

    # ── Invoice expired ────────────────────────────────────────────────────────
    elif event == "invoice.expired":
        logger.info(f"⏰ Webhook: Invoice expired {payment_hash[:12]}...")
        return True

    else:
        logger.debug(f"🔍 Unhandled webhook event: {event}")
        return True  # Always acknowledge


async def _sweep_and_log(
    payment_hash: str,
    merchant_id: int,
    gross_sats: int,
    fee_sats: int,
    net_sats: int,
) -> None:
    """
    Background task: sweep to Phoenix then log the fee.
    Separated from webhook handler so we return 200 to Voltage immediately.
    """
    logger.info(
        f"🔄 Background sweep starting | "
        f"merchant={merchant_id} net={net_sats} sats → Phoenix"
    )

    sweep = await sweep_to_phoenix(
        amount_sats=net_sats,
        payment_hash=payment_hash,
    )

    if sweep["success"]:
        # Log gas fee to DB only on successful sweep
        await log_gas_fee(
            payment_hash=payment_hash,
            merchant_id=merchant_id,
            gross_sats=gross_sats,
            fee_sats=fee_sats,
            net_sats=net_sats,
        )
        logger.info(
            f"✅ Sweep + fee log complete | "
            f"merchant={merchant_id} | "
            f"gross={gross_sats} fee={fee_sats} net={net_sats} sats"
        )
    else:
        # Log failure — don't silently drop
        logger.error(
            f"❌ Sweep FAILED for {payment_hash[:12]}... | "
            f"merchant={merchant_id} net={net_sats} sats | "
            f"error: {sweep['error']}"
        )
        # TODO: add to a retry queue for resilience