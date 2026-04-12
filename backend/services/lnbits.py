import httpx
import os
from dotenv import load_dotenv

load_dotenv()


def _get_url() -> str:
    return os.getenv("LNBITS_URL", "")

def _get_key() -> str:
    return os.getenv("LNBITS_API_KEY", "")

def _headers() -> dict:
    return {
        "X-Api-Key": _get_key(),
        "Content-Type": "application/json",
    }


async def create_invoice(amount_sats: int, memo: str, webhook_url: str | None = None) -> dict:
    """
    Create a Lightning invoice via LNbits.
    Returns: { payment_hash, payment_request (bolt11) }
    """
    payload = {
        "out": False,
        "amount": amount_sats,
        "memo": memo,
        "unit": "sat",
    }
    if webhook_url:
        payload["webhook"] = webhook_url

    url = f"{_get_url()}/api/v1/payments"
    print(f"[LNbits] Creating invoice: {amount_sats} sats | memo: {memo}")
    print(f"[LNbits] URL: {url}")
    print(f"[LNbits] Key: {_get_key()[:8]}...")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        print(f"[LNbits] Response status: {resp.status_code}")
        print(f"[LNbits] Response body: {resp.text}")
        resp.raise_for_status()
        return resp.json()


async def check_payment(payment_hash: str) -> dict:
    """
    Check if a payment has been settled.
    Returns: { paid: bool, details: {...} }
    """
    url = f"{_get_url()}/api/v1/payments/{payment_hash}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return {
            "paid": data.get("paid", False),
            "details": data,
        }