import httpx
import os
import json

def _get_url() -> str:
    return os.getenv("LNBITS_URL", "")

def _admin_headers() -> dict:
    return {
        "X-Api-Key": os.getenv("LNBITS_ADMIN_KEY", ""),
        "Content-Type": "application/json",
    }

def _invoice_headers() -> dict:
    return {
        "X-Api-Key": os.getenv("LNBITS_API_KEY", ""),
        "Content-Type": "application/json",
    }


async def get_wallet_balance() -> int:
    """Returns wallet balance in millisatoshis."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_get_url()}/api/v1/wallet",
            headers=_invoice_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        # LNbits returns balance in millisats
        return data.get("balance", 0)


async def resolve_lightning_address(address: str, amount_sats: int) -> str:
    """
    Resolve a Lightning Address (user@domain.com) to a BOLT11 invoice.
    Returns the payment_request string.
    """
    if "@" not in address:
        raise ValueError("Not a valid Lightning Address format (expected user@domain.com)")

    user, domain = address.split("@", 1)
    lnurl_url = f"https://{domain}/.well-known/lnurlp/{user}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: Get LNURL pay params
        resp = await client.get(lnurl_url)
        resp.raise_for_status()
        params = resp.json()

        if params.get("status") == "ERROR":
            raise ValueError(f"Lightning Address error: {params.get('reason')}")

        min_sats = params["minSendable"] // 1000
        max_sats = params["maxSendable"] // 1000

        if amount_sats < min_sats or amount_sats > max_sats:
            raise ValueError(f"Amount {amount_sats} sats out of range [{min_sats}, {max_sats}]")

        # Step 2: Request invoice for the amount
        callback = params["callback"]
        amount_msats = amount_sats * 1000
        invoice_resp = await client.get(f"{callback}?amount={amount_msats}")
        invoice_resp.raise_for_status()
        invoice_data = invoice_resp.json()

        if invoice_data.get("status") == "ERROR":
            raise ValueError(f"Invoice error: {invoice_data.get('reason')}")

        return invoice_data["pr"]  # BOLT11 payment request


async def pay_invoice(payment_request: str) -> dict:
    """Pay a BOLT11 invoice from the LNbits wallet using admin key."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_get_url()}/api/v1/payments",
            headers=_admin_headers(),
            json={"out": True, "bolt11": payment_request},
        )
        resp.raise_for_status()
        return resp.json()


async def sweep_to_lightning_address(address: str, amount_sats: int) -> dict:
    """
    Full sweep: resolve Lightning Address → get invoice → pay it.
    Returns payment result.
    """
    payment_request = await resolve_lightning_address(address, amount_sats)
    result = await pay_invoice(payment_request)
    return {
        "success": True,
        "address": address,
        "amount_sats": amount_sats,
        "payment_hash": result.get("payment_hash", ""),
    }
