# backend/services/alby_service.py
import httpx
import os
import logging

logger = logging.getLogger(__name__)

ALBY_ACCESS_TOKEN = os.getenv("ALBY_ACCESS_TOKEN", "")
ALBY_API_URL = "https://api.getalby.com"


async def pay_lightning_address(lightning_address: str, amount_sats: int, memo: str = "") -> dict:
    """
    Pay a Lightning address via Alby API.
    Returns {"success": True, "payment_hash": "..."} or {"success": False, "error": "..."}
    """
    if not ALBY_ACCESS_TOKEN:
        return {"success": False, "error": "Alby API token not configured"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ALBY_API_URL}/payments/keysend",
                headers={
                    "Authorization": f"Bearer {ALBY_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "invoice": None,
                    "amount": amount_sats,
                    "destination": lightning_address,
                    "memo": memo or "ZamPOS withdrawal",
                },
            )

            # Better: use lnurl pay endpoint
            resp2 = await client.post(
                f"{ALBY_API_URL}/payments/lnurl",
                headers={
                    "Authorization": f"Bearer {ALBY_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "lnurl": lightning_address,  # Alby accepts lightning addresses here
                    "amount": amount_sats * 1000,  # msats
                    "comment": memo or "ZamPOS withdrawal",
                },
            )

            data = resp2.json()
            logger.info(f"Alby payout response: {data}")

            if resp2.status_code == 200 and data.get("payment_hash"):
                return {
                    "success": True,
                    "payment_hash": data["payment_hash"],
                    "amount_sats": amount_sats,
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message") or data.get("error") or "Payout failed",
                }

    except Exception as e:
        logger.error(f"Alby pay error: {e}")
        return {"success": False, "error": str(e)}


async def get_alby_balance() -> int:
    """Returns Alby wallet balance in sats, or -1 on error."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{ALBY_API_URL}/balance",
                headers={"Authorization": f"Bearer {ALBY_ACCESS_TOKEN}"},
            )
            data = resp.json()
            return data.get("balance", -1)
    except Exception as e:
        logger.error(f"Alby balance error: {e}")
        return -1