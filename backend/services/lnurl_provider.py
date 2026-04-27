# backend/services/lnurl_provider.py
import httpx
import hashlib
import os
import json
import base64
import logging
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# LNURL Provider Configuration
LNURL_MODE = os.getenv("LNURL_MODE", "direct")
LND_REST_URL = os.getenv("LND_REST_URL", "")
LND_MACAROON_PATH = os.getenv("LND_MACAROON_PATH", "")
LND_CERT_PATH = os.getenv("LND_CERT_PATH", "")
LNURL_PROVIDER_URL = os.getenv("LNURL_PROVIDER_URL", "")
LNURL_PROVIDER_API_KEY = os.getenv("LNURL_PROVIDER_API_KEY", "")


async def generate_lightning_invoice_lnd(
    amount_sats: int,
    memo: str,
    expiry_seconds: int = 3600
) -> Tuple[str, str]:
    """
    Generate invoice using LND (Lightning Network Daemon)
    Returns: (bolt11, payment_hash)
    """
    try:
        # Load macaroon for authentication
        macaroon = None
        if LND_MACAROON_PATH and os.path.exists(LND_MACAROON_PATH):
            with open(LND_MACAROON_PATH, 'rb') as f:
                macaroon = base64.b64encode(f.read()).decode()
        
        headers = {
            "Grpc-Metadata-macaroon": macaroon,
            "Content-Type": "application/json"
        }
        
        payload = {
            "value": amount_sats,
            "memo": memo,
            "expiry": expiry_seconds
        }
        
        async with httpx.AsyncClient(timeout=30, verify=False if LND_CERT_PATH else True) as client:
            response = await client.post(
                f"{LND_REST_URL}/v1/invoices",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            bolt11 = data.get("payment_request")
            payment_hash = data.get("r_hash")
            
            if not bolt11:
                raise ValueError("No invoice generated")
            
            # Convert base64 payment hash to hex
            if payment_hash:
                payment_hash = base64.b64decode(payment_hash).hex()
            
            logger.info(f"✅ LND invoice generated: {amount_sats} sats")
            return bolt11, payment_hash
            
    except Exception as e:
        logger.error(f"❌ LND invoice failed: {e}")
        raise


async def generate_lightning_invoice_cln(
    amount_sats: int,
    memo: str,
    expiry_seconds: int = 3600
) -> Tuple[str, str]:
    """
    Generate invoice using Core Lightning (CLN)
    """
    try:
        import pyln.client
        from pyln.client import LightningRpc
        
        rpc_path = os.getenv("CLN_RPC_PATH", "/home/bitcoin/.lightning/lightning-rpc")
        rpc = LightningRpc(rpc_path)
        
        # Create invoice
        label = f"zampos_{int(datetime.now().timestamp())}"
        invoice = rpc.invoice(amount_sats * 1000, label, memo, expiry_seconds)
        
        bolt11 = invoice['bolt11']
        payment_hash = invoice['payment_hash']
        
        logger.info(f"✅ CLN invoice generated: {amount_sats} sats")
        return bolt11, payment_hash
        
    except ImportError:
        logger.error("pyln-client not installed. Install with: pip install pyln-client")
        raise
    except Exception as e:
        logger.error(f"❌ CLN invoice failed: {e}")
        raise


async def generate_lightning_invoice_breez(
    amount_sats: int,
    memo: str,
    expiry_seconds: int = 3600
) -> Tuple[str, str]:
    """
    Generate invoice using Breez SDK (when funded)
    """
    try:
        from services.breez_service import receive_payment
        
        result = await receive_payment(amount_sats, memo)
        
        if not result.get("success"):
            raise ValueError(f"Breez invoice failed: {result.get('error')}")
        
        bolt11 = result["bolt11"]
        payment_hash = result.get("payment_hash")
        
        if not payment_hash:
            import hashlib
            payment_hash = hashlib.sha256(bolt11.encode()).hexdigest()
        
        logger.info(f"✅ Breez invoice generated: {amount_sats} sats")
        return bolt11, payment_hash
        
    except Exception as e:
        logger.error(f"❌ Breez invoice failed: {e}")
        raise


async def generate_lightning_invoice_generic_provider(
    amount_sats: int,
    memo: str,
    expiry_seconds: int = 3600
) -> Tuple[str, str]:
    """
    Generate invoice using a generic LNURL provider API
    (For services like LNBits, Alby, OpenNode, etc.)
    """
    try:
        if not LNURL_PROVIDER_URL:
            raise ValueError("LNURL_PROVIDER_URL not configured")
        
        headers = {
            "Content-Type": "application/json",
        }
        
        if LNURL_PROVIDER_API_KEY:
            headers["X-API-Key"] = LNURL_PROVIDER_API_KEY
            headers["Authorization"] = f"Bearer {LNURL_PROVIDER_API_KEY}"
        
        payload = {
            "amount": amount_sats,
            "memo": memo,
            "expiry": expiry_seconds,
            "description_hash": hashlib.sha256(memo.encode()).hexdigest()
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{LNURL_PROVIDER_URL}/api/v1/invoices",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            # Handle different response formats
            bolt11 = data.get("payment_request") or data.get("bolt11") or data.get("pr")
            payment_hash = data.get("payment_hash") or data.get("r_hash")
            
            if not bolt11:
                raise ValueError("No invoice in response")
            
            logger.info(f"✅ Generic provider invoice generated: {amount_sats} sats")
            return bolt11, payment_hash
            
    except Exception as e:
        logger.error(f"❌ Generic provider invoice failed: {e}")
        raise


async def generate_lightning_invoice_direct_lnurl(
    amount_sats: int,
    memo: str,
    expiry_seconds: int = 3600
) -> Tuple[str, str]:
    """
    Generate invoice using direct LNURL callback to merchant's wallet.
    This uses the merchant's own Lightning Address to request an invoice.
    """
    try:
        from services.lnurl_pay import resolve_lightning_address, fetch_invoice_from_lightning_address
        
        # For merchant-specific invoices, we need the merchant's Lightning Address
        # This function should be called with the merchant's address
        # For now, we'll use this for operator or fallback
        lightning_address = os.getenv("OPERATOR_LIGHTNING_ADDRESS", "")
        
        if not lightning_address:
            raise ValueError("No Lightning Address configured for direct LNURL")
        
        bolt11 = await fetch_invoice_from_lightning_address(
            lightning_address=lightning_address,
            amount_sats=amount_sats,
            comment=memo
        )
        
        payment_hash = hashlib.sha256(bolt11.encode()).hexdigest()
        
        logger.info(f"✅ Direct LNURL invoice generated: {amount_sats} sats")
        return bolt11, payment_hash
        
    except Exception as e:
        logger.error(f"❌ Direct LNURL invoice failed: {e}")
        raise


async def generate_lightning_invoice(
    amount_sats: int,
    memo: str,
    merchant_lightning_address: Optional[str] = None,
    expiry_seconds: int = 3600
) -> Tuple[str, str]:
    """
    Main invoice generation function - routes to appropriate provider
    Returns: (bolt11, payment_hash)
    """
    
    # Priority 1: Use merchant's own LNURL (most direct)
    if merchant_lightning_address:
        try:
            from services.lnurl_pay import fetch_invoice_from_lightning_address
            bolt11 = await fetch_invoice_from_lightning_address(
                lightning_address=merchant_lightning_address,
                amount_sats=amount_sats,
                comment=memo
            )
            payment_hash = hashlib.sha256(bolt11.encode()).hexdigest()
            logger.info(f"✅ Invoice generated via merchant's LNURL: {merchant_lightning_address}")
            return bolt11, payment_hash
        except Exception as e:
            logger.warning(f"Failed to use merchant's LNURL: {e}, falling back...")
    
    # Priority 2: Use configured LNURL mode
    if LNURL_MODE == "lnd":
        return await generate_lightning_invoice_lnd(amount_sats, memo, expiry_seconds)
    elif LNURL_MODE == "cln":
        return await generate_lightning_invoice_cln(amount_sats, memo, expiry_seconds)
    elif LNURL_MODE == "breez":
        return await generate_lightning_invoice_breez(amount_sats, memo, expiry_seconds)
    elif LNURL_MODE == "generic":
        return await generate_lightning_invoice_generic_provider(amount_sats, memo, expiry_seconds)
    elif LNURL_MODE == "direct":
        return await generate_lightning_invoice_direct_lnurl(amount_sats, memo, expiry_seconds)
    else:
        raise ValueError(f"Unknown LNURL_MODE: {LNURL_MODE}")


async def check_invoice_status_lnd(payment_hash: str) -> dict:
    """Check invoice status using LND"""
    try:
        macaroon = None
        if LND_MACAROON_PATH and os.path.exists(LND_MACAROON_PATH):
            with open(LND_MACAROON_PATH, 'rb') as f:
                macaroon = base64.b64encode(f.read()).decode()
        
        headers = {"Grpc-Metadata-macaroon": macaroon}
        
        # Convert hex payment hash to base64 for LND
        r_hash_base64 = base64.b64encode(bytes.fromhex(payment_hash)).decode()
        
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            response = await client.get(
                f"{LND_REST_URL}/v1/invoice/{r_hash_base64}",
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            settled = data.get("settled", False)
            return {
                "paid": settled,
                "settled": settled,
                "preimage": data.get("payment_preimage") if settled else None
            }
            
    except Exception as e:
        logger.error(f"❌ LND status check failed: {e}")
        return {"paid": False, "error": str(e)}


async def check_invoice_status_cln(payment_hash: str) -> dict:
    """Check invoice status using CLN"""
    try:
        import pyln.client
        from pyln.client import LightningRpc
        
        rpc_path = os.getenv("CLN_RPC_PATH", "/home/bitcoin/.lightning/lightning-rpc")
        rpc = LightningRpc(rpc_path)
        
        invoice = rpc.listinvoices(payment_hash)
        
        if invoice and invoice.get('invoices'):
            inv = invoice['invoices'][0]
            settled = inv.get('status') == 'paid'
            return {
                "paid": settled,
                "settled": settled,
                "preimage": inv.get('payment_preimage') if settled else None
            }
        
        return {"paid": False}
        
    except Exception as e:
        logger.error(f"❌ CLN status check failed: {e}")
        return {"paid": False, "error": str(e)}


async def check_invoice_status_generic(payment_hash: str) -> dict:
    """Check invoice status via generic provider"""
    try:
        headers = {}
        if LNURL_PROVIDER_API_KEY:
            headers["Authorization"] = f"Bearer {LNURL_PROVIDER_API_KEY}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{LNURL_PROVIDER_URL}/api/v1/invoices/{payment_hash}",
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            settled = data.get("settled", False) or data.get("paid", False)
            return {
                "paid": settled,
                "settled": settled,
                "preimage": data.get("payment_preimage") if settled else None
            }
            
    except Exception as e:
        logger.error(f"❌ Generic status check failed: {e}")
        return {"paid": False, "error": str(e)}


async def check_invoice_status(payment_hash: str) -> dict:
    """Main invoice status check function"""
    if LNURL_MODE == "lnd":
        return await check_invoice_status_lnd(payment_hash)
    elif LNURL_MODE == "cln":
        return await check_invoice_status_cln(payment_hash)
    elif LNURL_MODE == "generic":
        return await check_invoice_status_generic(payment_hash)
    else:
        # For direct LNURL, status checking is limited
        return {"paid": False, "message": "Manual confirmation required for direct LNURL"}