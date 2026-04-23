# backend/services/breez_service.py — ZamPOS Breez SDK (PRODUCTION FIXED)

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BREEZ_API_KEY = os.getenv("BREEZ_API_KEY", "")
BREEZ_MNEMONIC = os.getenv("BREEZ_MNEMONIC", "")
BREEZ_STORAGE_DIR = os.getenv("BREEZ_STORAGE_DIR", "./.breez_data")

_sdk = None


# --------------------------------------------------
# INIT
# --------------------------------------------------
async def init_breez() -> bool:
    """Initialize Breez SDK connection"""
    global _sdk
    try:
        import breez_sdk_spark as breez

        if not BREEZ_API_KEY:
            raise Exception("BREEZ_API_KEY not set")

        if not BREEZ_MNEMONIC:
            raise Exception("BREEZ_MNEMONIC not set")

        os.makedirs(BREEZ_STORAGE_DIR, exist_ok=True)

        config = breez.default_config(breez.Network.MAINNET)
        config.api_key = BREEZ_API_KEY

        connect_request = breez.ConnectRequest(
            config=config,
            seed=breez.Seed.MNEMONIC(BREEZ_MNEMONIC, ""),
            storage_dir=BREEZ_STORAGE_DIR,
        )

        _sdk = await breez.connect(connect_request)

        info = await _sdk.get_info(
            breez.GetInfoRequest(ensure_synced=False)
        )

        logger.info(
            f"✅ Breez ready | Node: {info.identity_pubkey} | Balance: {info.balance_sats} sats"
        )

        return True

    except Exception as e:
        logger.error(f"❌ Breez init failed: {e}")
        return False


# --------------------------------------------------
# HEALTH
# --------------------------------------------------
async def breez_is_ready() -> bool:
    """Check if Breez SDK is initialized"""
    return _sdk is not None


# --------------------------------------------------
# RECEIVE PAYMENT (TOPUP / INVOICE GENERATION)
# --------------------------------------------------
async def receive_payment(amount_sats: int, description: str = "ZamPOS Payment") -> dict:
    global _sdk
    try:
        if not _sdk:
            return {"success": False, "error": "Breez SDK not initialized"}

        import breez_sdk_spark as breez
        import secrets

        payment_hash = secrets.token_hex(32)

        # ✅ REQUIRED FIELDS ONLY
        payment_method = breez.ReceivePaymentMethod.BOLT11_INVOICE(
            description=description,
            amount_sats=amount_sats,
            expiry_secs=3600,
            payment_hash=payment_hash
        )

        req = breez.ReceivePaymentRequest(payment_method=payment_method)
        resp = await _sdk.receive_payment(req)

        # -----------------------------------------
        # 🔥 ULTRA-ROBUST INVOICE EXTRACTION
        # -----------------------------------------
        bolt11 = None

        # 1. direct field
        bolt11 = getattr(resp, "invoice", None)

        # 2. nested invoice_details
        if not bolt11:
            inv_details = getattr(resp, "invoice_details", None)
            if inv_details:
                inv_obj = getattr(inv_details, "invoice", None)

                # case A: object with bolt11
                bolt11 = getattr(inv_obj, "bolt11", None)

                # case B: string wrapper
                if not bolt11 and isinstance(inv_obj, str):
                    bolt11 = inv_obj

        # 3. final fallback
        if not bolt11:
            bolt11 = getattr(resp, "payment_request", None)

        if not bolt11:
            raise Exception(f"Invoice extraction failed. Resp keys: {dir(resp)}")

        return {
            "success": True,
            "invoice": bolt11,
            "amount_sats": amount_sats,
            "fees_sat": getattr(resp, "fees_sat", 0),
            "payment_hash": payment_hash,
        }

    except Exception as e:
        logger.error(f"❌ Breez receive_payment error: {e}")
        return {"success": False, "error": str(e)}

# --------------------------------------------------
# BALANCE
# --------------------------------------------------
async def get_breez_balance() -> int:
    """Get current Breez node balance in sats"""
    global _sdk
    try:
        if not _sdk:
            return -1

        import breez_sdk_spark as breez

        info = await _sdk.get_info(
            breez.GetInfoRequest(ensure_synced=False)
        )

        return info.balance_sats

    except Exception as e:
        logger.error(f"❌ Breez balance error: {e}")
        return -1


# --------------------------------------------------
# NODE ID
# --------------------------------------------------
async def get_breez_node_id() -> Optional[str]:
    """Get Breez node public key"""
    global _sdk
    try:
        if not _sdk:
            return None

        import breez_sdk_spark as breez

        info = await _sdk.get_info(
            breez.GetInfoRequest(ensure_synced=False)
        )

        return info.identity_pubkey

    except Exception as e:
        logger.error(f"❌ Breez node id error: {e}")
        return None


# --------------------------------------------------
# PAYMENT STATUS CHECK
# --------------------------------------------------
async def check_payment_status(payment_hash: str) -> dict:
    """Check the status of a payment by its hash"""
    global _sdk
    try:
        if not _sdk:
            return {"success": False, "error": "Breez SDK not initialized"}

        import breez_sdk_spark as breez

        # Attempt to list payments and filter by hash
        # Note: This depends on SDK version, adjust as needed
        list_req = breez.ListPaymentsRequest(
            filters=[breez.PaymentTypeFilter.RECEIVED]
        )
        
        payments = await _sdk.list_payments(list_req)
        
        for payment in payments:
            if getattr(payment, "payment_hash", None) == payment_hash:
                return {
                    "success": True,
                    "found": True,
                    "status": str(payment.status),
                    "amount_sats": payment.amount_sats,
                    "timestamp": payment.payment_time,
                }
        
        return {
            "success": True,
            "found": False,
            "message": "Payment not found"
        }

    except Exception as e:
        logger.error(f"❌ Payment status check error: {e}")
        return {"success": False, "error": str(e)}


# --------------------------------------------------
# SHUTDOWN
# --------------------------------------------------
async def close_breez():
    """Gracefully close Breez SDK connection"""
    global _sdk
    try:
        if _sdk:
            # Perform any cleanup if SDK supports it
            await _sdk.disconnect() if hasattr(_sdk, 'disconnect') else None
    except Exception as e:
        logger.error(f"❌ Breez disconnect error: {e}")
    finally:
        _sdk = None
        logger.info("🔌 Breez SDK cleared")