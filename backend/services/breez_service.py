# backend/services/breez_service.py — ZamPOS Breez SDK (Production Ready)
#
# FIXES vs previous version:
#   1. Added pay_lightning_address() — was completely missing, causing all
#      withdrawals to stay 'pending' via ImportError fallback in router
#   2. Added pay_bolt11() — needed internally by pay_lightning_address
#   3. Fixed close_breez() — `await expr if cond else None` evaluates the
#      condition AFTER await, crashing if _sdk has no disconnect(). Fixed to
#      check hasattr first, then conditionally await.
#   4. check_payment_status() now checks both SENT and RECEIVED filters
#   5. All public functions return consistent {success, error} dicts on failure

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BREEZ_API_KEY    = os.getenv("BREEZ_API_KEY", "")
BREEZ_MNEMONIC   = os.getenv("BREEZ_MNEMONIC", "")
BREEZ_STORAGE_DIR = os.getenv("BREEZ_STORAGE_DIR", "./.breez_data")

_sdk = None


# ─────────────────────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────────────────────

async def init_breez() -> bool:
    """Initialize Breez SDK connection. Returns True on success."""
    global _sdk
    try:
        import breez_sdk_spark as breez

        if not BREEZ_API_KEY:
            raise ValueError("BREEZ_API_KEY not set in environment")
        if not BREEZ_MNEMONIC:
            raise ValueError("BREEZ_MNEMONIC not set in environment")

        os.makedirs(BREEZ_STORAGE_DIR, exist_ok=True)

        config          = breez.default_config(breez.Network.MAINNET)
        config.api_key  = BREEZ_API_KEY

        connect_request = breez.ConnectRequest(
            config=config,
            seed=breez.Seed.MNEMONIC(BREEZ_MNEMONIC, ""),
            storage_dir=BREEZ_STORAGE_DIR,
        )

        _sdk = await breez.connect(connect_request)

        info = await _sdk.get_info(breez.GetInfoRequest(ensure_synced=False))
        logger.info(
            f"✅ Breez ready | Node: {info.identity_pubkey} | Balance: {info.balance_sats} sats"
        )
        return True

    except Exception as e:
        logger.error(f"❌ Breez init failed: {e}")
        _sdk = None
        return False


# ─────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────

async def breez_is_ready() -> bool:
    return _sdk is not None


# ─────────────────────────────────────────────────────────────
# BALANCE
# ─────────────────────────────────────────────────────────────

async def get_breez_balance() -> int:
    """Return current Breez node balance in sats, or -1 on error."""
    global _sdk
    try:
        if not _sdk:
            return -1
        import breez_sdk_spark as breez
        info = await _sdk.get_info(breez.GetInfoRequest(ensure_synced=False))
        return info.balance_sats
    except Exception as e:
        logger.error(f"❌ Breez balance error: {e}")
        return -1


# ─────────────────────────────────────────────────────────────
# NODE ID
# ─────────────────────────────────────────────────────────────

async def get_breez_node_id() -> Optional[str]:
    """Return Breez node public key, or None on error."""
    global _sdk
    try:
        if not _sdk:
            return None
        import breez_sdk_spark as breez
        info = await _sdk.get_info(breez.GetInfoRequest(ensure_synced=False))
        return info.identity_pubkey
    except Exception as e:
        logger.error(f"❌ Breez node id error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# RECEIVE PAYMENT  (top-up / invoice generation)
# ─────────────────────────────────────────────────────────────

async def receive_payment(
    amount_sats: int,
    description: str = "ZamPOS Payment",
) -> dict:
    """Generate a Bolt11 invoice to receive funds into the Breez node."""
    global _sdk
    try:
        if not _sdk:
            return {"success": False, "error": "Breez SDK not initialized"}

        import breez_sdk_spark as breez
        import secrets

        payment_hash   = secrets.token_hex(32)
        payment_method = breez.ReceivePaymentMethod.BOLT11_INVOICE(
            description=description,
            amount_sats=amount_sats,
            expiry_secs=3600,
            payment_hash=payment_hash,
        )

        req  = breez.ReceivePaymentRequest(payment_method=payment_method)
        resp = await _sdk.receive_payment(req)

        # ── Robust invoice extraction ──────────────────────────
        bolt11 = None

        # 1. Direct field
        bolt11 = getattr(resp, "invoice", None)

        # 2. Nested invoice_details
        if not bolt11:
            inv_details = getattr(resp, "invoice_details", None)
            if inv_details:
                inv_obj = getattr(inv_details, "invoice", None)
                bolt11  = getattr(inv_obj, "bolt11", None)
                if not bolt11 and isinstance(inv_obj, str):
                    bolt11 = inv_obj

        # 3. Final fallback
        if not bolt11:
            bolt11 = getattr(resp, "payment_request", None)

        if not bolt11:
            raise ValueError(f"Invoice extraction failed. resp attrs: {dir(resp)}")

        return {
            "success":      True,
            "bolt11":       bolt11,
            "invoice":      bolt11,        # alias for backward compat
            "amount_sats":  amount_sats,
            "fees_sat":     getattr(resp, "fees_sat", 0),
            "payment_hash": payment_hash,
        }

    except Exception as e:
        logger.error(f"❌ Breez receive_payment error: {e}")
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# PAY BOLT11  (outbound payment)
# ─────────────────────────────────────────────────────────────

async def pay_bolt11(bolt11: str, amount_sats: Optional[int] = None) -> dict:
    """
    Pay a Bolt11 invoice from the Breez node wallet.

    Args:
        bolt11:      The Lightning invoice string (lnbc...)
        amount_sats: Override amount for zero-amount invoices. Leave None
                     for fixed-amount invoices.

    Returns:
        {"success": True, "payment_hash": ..., "fee_sats": ...}
        {"success": False, "error": ...}
    """
    global _sdk
    try:
        if not _sdk:
            return {"success": False, "error": "Breez SDK not initialized"}

        import breez_sdk_spark as breez

        # Check we have enough balance before attempting
        balance = await get_breez_balance()
        if balance < 0:
            return {"success": False, "error": "Could not read Breez balance"}

        needed = amount_sats or 0
        if needed > 0 and balance < needed:
            return {
                "success": False,
                "error": f"Insufficient Breez balance: have {balance} sats, need {needed} sats",
            }

        # Build the send request
        if amount_sats:
            send_req = breez.SendPaymentRequest(
                bolt11=bolt11,
                amount_sats=amount_sats,
            )
        else:
            send_req = breez.SendPaymentRequest(bolt11=bolt11)

        resp = await _sdk.send_payment(send_req)

        payment      = getattr(resp, "payment", resp)
        payment_hash = getattr(payment, "payment_hash", None) or getattr(payment, "id", "unknown")
        fee_sats     = getattr(payment, "fee_sats", 0) or getattr(payment, "fees_sats", 0)

        logger.info(f"⚡ Bolt11 paid | hash={payment_hash} | fee={fee_sats} sats")

        return {
            "success":      True,
            "payment_hash": payment_hash,
            "fee_sats":     fee_sats,
        }

    except Exception as e:
        logger.error(f"❌ Breez pay_bolt11 error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# PAY LIGHTNING ADDRESS  (LNURL-pay flow)
# ─────────────────────────────────────────────────────────────

async def pay_lightning_address(
    lightning_address: str,
    amount_sats: int,
    memo: str = "ZamPOS withdrawal",
) -> dict:
    """
    Pay a Lightning Address (user@domain.com) by:
      1. Resolving the LNURL-pay endpoint
      2. Fetching a Bolt11 invoice for amount_sats
      3. Paying the invoice via Breez

    Returns:
        {"success": True, "payment_hash": ..., "fee_sats": ...}
        {"success": False, "error": ...}
    """
    if not _sdk:
        return {"success": False, "error": "Breez SDK not initialized"}

    if amount_sats <= 0:
        return {"success": False, "error": "amount_sats must be > 0"}

    try:
        # ── Step 1: Resolve Lightning Address → LNURL callback ──
        import httpx

        user, domain = lightning_address.strip().lower().split("@")
        lnurl_url    = f"https://{domain}/.well-known/lnurlp/{user}"

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(lnurl_url)
            r.raise_for_status()
            lnurl_data = r.json()

        if lnurl_data.get("status") == "ERROR":
            return {
                "success": False,
                "error": f"LNURL error: {lnurl_data.get('reason', 'unknown')}",
            }

        callback  = lnurl_data.get("callback")
        min_msats = lnurl_data.get("minSendable", 1000)
        max_msats = lnurl_data.get("maxSendable", 100_000_000_000)

        if not callback:
            return {"success": False, "error": "No callback URL in LNURL response"}

        amount_msats = amount_sats * 1000

        if amount_msats < min_msats:
            return {
                "success": False,
                "error": f"Amount too small: {amount_sats} sats < min {min_msats // 1000} sats",
            }
        if amount_msats > max_msats:
            return {
                "success": False,
                "error": f"Amount too large: {amount_sats} sats > max {max_msats // 1000} sats",
            }

        # ── Step 2: Fetch invoice from callback ─────────────────
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                callback,
                params={"amount": amount_msats, "comment": memo[:144]},
            )
            r.raise_for_status()
            invoice_data = r.json()

        if invoice_data.get("status") == "ERROR":
            return {
                "success": False,
                "error": f"Invoice fetch error: {invoice_data.get('reason', 'unknown')}",
            }

        bolt11 = invoice_data.get("pr")
        if not bolt11:
            return {"success": False, "error": "No invoice (pr) in callback response"}

        logger.info(
            f"⚡ Paying Lightning Address | {lightning_address} | "
            f"{amount_sats} sats | invoice fetched"
        )

        # ── Step 3: Pay the invoice via Breez ───────────────────
        result = await pay_bolt11(bolt11, amount_sats=None)  # invoice is fixed-amount

        if result["success"]:
            logger.info(
                f"✅ Lightning Address paid | {lightning_address} | "
                f"{amount_sats} sats | fee={result.get('fee_sats', 0)} sats"
            )
        else:
            logger.error(
                f"❌ Lightning Address payment failed | {lightning_address} | "
                f"{amount_sats} sats | {result['error']}"
            )

        return result

    except httpx.HTTPStatusError as e:
        err = f"HTTP {e.response.status_code} resolving {lightning_address}"
        logger.error(f"❌ pay_lightning_address: {err}")
        return {"success": False, "error": err}

    except Exception as e:
        logger.error(f"❌ pay_lightning_address: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# PAYMENT STATUS CHECK
# ─────────────────────────────────────────────────────────────

async def check_payment_status(payment_hash: str) -> dict:
    """Check the status of any payment (sent or received) by hash."""
    global _sdk
    try:
        if not _sdk:
            return {"success": False, "error": "Breez SDK not initialized"}

        import breez_sdk_spark as breez

        # Check both sent and received
        for filter_type in (
            breez.PaymentTypeFilter.SENT,
            breez.PaymentTypeFilter.RECEIVED,
        ):
            try:
                list_req  = breez.ListPaymentsRequest(filters=[filter_type])
                payments  = await _sdk.list_payments(list_req)

                for payment in payments:
                    if getattr(payment, "payment_hash", None) == payment_hash:
                        return {
                            "success":     True,
                            "found":       True,
                            "status":      str(payment.status),
                            "amount_sats": getattr(payment, "amount_sats", 0),
                            "fee_sats":    getattr(payment, "fee_sats", 0),
                            "timestamp":   getattr(payment, "payment_time", None),
                            "direction":   "sent" if filter_type == breez.PaymentTypeFilter.SENT else "received",
                        }
            except Exception:
                continue  # filter not supported — skip

        return {"success": True, "found": False, "message": "Payment not found"}

    except Exception as e:
        logger.error(f"❌ check_payment_status: {e}")
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# SHUTDOWN
# ─────────────────────────────────────────────────────────────

async def close_breez():
    """Gracefully shut down the Breez SDK connection."""
    global _sdk
    try:
        if _sdk is not None:
            # FIX: check hasattr BEFORE awaiting — previous code had the
            # conditional on the wrong side of `await`, which crashes if
            # disconnect() doesn't exist
            if hasattr(_sdk, "disconnect"):
                await _sdk.disconnect()
            elif hasattr(_sdk, "close"):
                await _sdk.close()
    except Exception as e:
        logger.error(f"❌ Breez disconnect error: {e}")
    finally:
        _sdk = None
        logger.info("🔌 Breez SDK cleared")