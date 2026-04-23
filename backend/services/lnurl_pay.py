import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def resolve_lightning_address(lightning_address: str) -> dict:
    """
    Resolve Lightning Address → LNURL-pay metadata
    """

    if "@" not in lightning_address:
        raise ValueError(f"Invalid Lightning Address: {lightning_address}")

    user, domain = lightning_address.strip().lower().split("@", 1)

    paths = [
        f"https://{domain}/.well-known/lnurlp/{user}",
        f"https://{domain}/lnurlp/{user}",
    ]

    data = None
    last_error = None

    async with httpx.AsyncClient(timeout=12) as client:
        for url in paths:
            try:
                logger.debug(f"🔍 Trying LNURL endpoint: {url}")
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                last_error = e

    if data is None:
        raise Exception(f"LNURL resolution failed for {lightning_address}: {last_error}")

    if data.get("status") == "ERROR":
        raise Exception(f"LNURL error: {data.get('reason', 'Unknown')}")

    if data.get("tag") != "payRequest":
        raise Exception(f"Not a payRequest: tag={data.get('tag')}")

    return {
        "callback": data["callback"],
        "min_sendable": int(data.get("minSendable", 1000)),
        "max_sendable": int(data.get("maxSendable", 10**12)),
        "metadata": data.get("metadata", ""),
        "comment_allowed": int(data.get("commentAllowed", 0)),
        "domain": domain,
    }


async def fetch_invoice_from_lightning_address(
    lightning_address: str,
    amount_sats: int,
    comment: Optional[str] = None,
) -> str:

    lnurl = await resolve_lightning_address(lightning_address)
    amount_msats = amount_sats * 1000

    min_msat = lnurl["min_sendable"]
    max_msat = lnurl["max_sendable"]

    min_sats = min_msat // 1000
    max_sats = max_msat // 1000

    if amount_msats < min_msat:
        raise ValueError(f"Minimum is {min_sats} sats")

    if amount_msats > max_msat:
        raise ValueError(f"Maximum is {max_sats} sats")

    params = {"amount": amount_msats}

    if comment and lnurl["comment_allowed"] > 0:
        params["comment"] = comment[: lnurl["comment_allowed"]]

    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.get(lnurl["callback"], params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "ERROR":
        raise Exception(data.get("reason", "Invoice error"))

    bolt11 = data.get("pr")
    if not bolt11:
        raise Exception("Missing invoice")

    return bolt11
async def check_lightning_invoice_status(bolt11: str, lightning_address: str) -> dict:
    """
    Check if a bolt11 invoice has been paid.
    
    For Wallet of Satoshi, this is tricky because they don't expose a status endpoint.
    Alternative: Use a separate node or service to check.
    """
    # First, try to see if the LNURL provider has a status endpoint
    try:
        lnurl = await resolve_lightning_address(lightning_address)
        
        # Some providers include a 'checkEndpoint' in their response
        if "checkEndpoint" in lnurl:
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.get(lnurl["checkEndpoint"], params={"pr": bolt11})
                data = resp.json()
                return {
                    "paid": data.get("paid", False),
                    "settled": data.get("settled", False),
                    "preimage": data.get("preimage"),
                }
        
        # For Wallet of Satoshi, they don't expose this
        # We need to use a different approach
        
    except Exception as e:
        logger.warning(f"Could not check status via LNURL: {e}")
    
    # Fallback: Return unknown - rely on manual confirmation or webhook
    return {"paid": False, "settled": False, "error": "Status checking not supported by this provider"}


async def wait_for_payment(
    bolt11: str, 
    lightning_address: str, 
    timeout_seconds: int = 300,
    check_interval: int = 5
) -> bool:
    """
    Poll for payment status until timeout.
    Works with providers that support status checking.
    """
    import asyncio
    
    start_time = asyncio.get_event_loop().time()
    
    while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
        try:
            status = await check_lightning_invoice_status(bolt11, lightning_address)
            if status.get("paid") or status.get("settled"):
                logger.info(f"✅ Payment detected for invoice")
                return True
        except Exception as e:
            logger.debug(f"Payment check failed: {e}")
        
        await asyncio.sleep(check_interval)
    
    return False

async def validate_lightning_address(lightning_address: str) -> dict:
    try:
        lnurl = await resolve_lightning_address(lightning_address)
        return {
            "valid": True,
            "min_sats": lnurl["min_sendable"] // 1000,
            "max_sats": lnurl["max_sendable"] // 1000,
            "domain": lnurl["domain"],
            "error": None,
        }
    except Exception as e:
        return {
            "valid": False,
            "min_sats": None,
            "max_sats": None,
            "domain": None,
            "error": str(e),
        }


def extract_payment_hash(bolt11: str) -> str:
    try:
        import bolt11 as b11
        return b11.decode(bolt11).payment_hash
    except Exception:
        import hashlib
        return hashlib.sha256(bolt11.encode()).hexdigest()