# backend/webhooks.py
"""
ZamPOS Webhook Handler
──────────────────────
Handles Voltage payment confirmation events.

On invoice.settled:
  1. Verify webhook secret
  2. Mark transaction as paid in DB
  3. Calculate gas fee (50 sats flat)
  4. Sweep net sats to owner Phoenix wallet
  5. Log gas fee to DB
"""

import logging
import hmac
import os
from database import mark_paid, get_transaction_by_hash
from services.fee_engine import calculate_gas_fee, log_gas_fee
from services.phoenix_sweep import sweep_to_phoenix
from typing import Dict, Any

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


def verify_webhook_secret(secret_header: str | None) -> bool:
    """
    Verify the Voltage-Secret header matches our configured secret.
    If no secret configured, skip verification (dev mode).
    """
    if not WEBHOOK_SECRET:
        logger.warning("⚠️ WEBHOOK_SECRET not set — skipping verification (dev mode)")
        return True
    if not secret_header:
        logger.warning("⚠️ Webhook missing Voltage-Secret header")
        return False
    return hmac.compare_digest(secret_header.strip(), WEBHOOK_SECRET.strip())


async def handle_voltage_webhook(
    payload: Dict[str, Any],
    background_tasks,
    secret_header: str | None = None,
) -> bool:
    """
    Process Voltage webhook events.

    Expected payload structure:
    {
      "event": "invoice.settled",
      "data": {
        "payment_hash": "abc123...",
        "amount": 1000,
        "memo": "ZamPOS...",
        "settled_at": "2024-01-15T10:30:00Z"
      },
      "timestamp": 1705315800
    }
    """
    # Verify secret
    if not verify_webhook_secret(secret_header):
        logger.warning("❌ Webhook secret verification failed — rejecting")
        return False

    event = payload.get("event")
    data = payload.get("data", {})
    payment_hash = data.get("payment_hash")

    if not payment_hash:
        logger.warning(f"⚠️ Webhook missing payment_hash: {payload}")
        return False

    # Payment confirmed
    if event in ["invoice.settled", "payment.received"]:
        logger.info(f"✅ Webhook: Payment settled {payment_hash[:12]}...")

        # 1. Mark paid in local DB
        success = await mark_paid(payment_hash)
        if not success:
            logger.warning(f"⚠️ Could not mark paid for {payment_hash}")

        # 2. Fetch transaction
        tx = await get_transaction_by_hash(payment_hash)
        if not tx:
            logger.warning(f"⚠️ Transaction not found for {payment_hash[:12]}... — skipping sweep")
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
            logger.warning(f"⚠️ Skipping sweep: {fee_result['reason']}")
            return True

        # 4. Sweep in background — return 200 to Voltage immediately
        background_tasks.add_task(
            _sweep_and_log,
            payment_hash=payment_hash,
            merchant_id=merchant_id,
            gross_sats=fee_result["gross_sats"],
            fee_sats=fee_result["fee_sats"],
            net_sats=fee_result["net_sats"],
        )

        return True

    elif event == "invoice.expired":
        logger.info(f"⏰ Webhook: Invoice expired {payment_hash[:12]}...")
        return True

    else:
        logger.debug(f"🔍 Unhandled webhook event: {event}")
        return True


async def _sweep_and_log(
    payment_hash: str,
    merchant_id: int,
    gross_sats: int,
    fee_sats: int,
    net_sats: int,
) -> None:
    """Background task: sweep to Phoenix then log the fee."""
    logger.info(f"🔄 Sweep starting | merchant={merchant_id} net={net_sats} sats → Phoenix")

    sweep = await sweep_to_phoenix(amount_sats=net_sats, payment_hash=payment_hash)

    if sweep["success"]:
        await log_gas_fee(
            payment_hash=payment_hash,
            merchant_id=merchant_id,
            gross_sats=gross_sats,
            fee_sats=fee_sats,
            net_sats=net_sats,
        )
        logger.info(f"✅ Sweep done | gross={gross_sats} fee={fee_sats} net={net_sats} sats")
    else:
        logger.error(
            f"❌ Sweep FAILED | merchant={merchant_id} net={net_sats} sats | {sweep['error']}"
        )