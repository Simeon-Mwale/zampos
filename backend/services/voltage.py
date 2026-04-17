# backend/services/voltage.py
import httpx
import os
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

NODE_REST_HOST = os.getenv("NODE_REST_HOST", "").strip()
NODE_MACAROON_HEX = os.getenv("NODE_MACAROON_HEX", "").strip()
INVOICE_EXPIRY = int(os.getenv("INVOICE_EXPIRY_SECONDS", "1800"))

if not NODE_REST_HOST or not NODE_MACAROON_HEX:
    raise ValueError("⚠️ Set NODE_REST_HOST and NODE_MACAROON_HEX in .env")

# ✅ Not async — no need for await
def _headers() -> dict:
    return {
        "Grpc-Metadata-macaroon": NODE_MACAROON_HEX,
        "Content-Type": "application/json",
    }

def _get_endpoints(path: str) -> list[str]:
    """
    Build endpoint list based on NODE_REST_HOST format.
    Voltage REST proxy (.m. subdomain) uses port 443.
    Direct LND REST (.u. subdomain) uses port 8080.
    """
    host = NODE_REST_HOST.rstrip("/")

    # If host already includes a port, use it as-is
    if ":" in host.split("/")[-1]:
        return [f"https://{host}{path}"]

    # Otherwise try both common Voltage formats
    return [
        f"https://{host}:8080{path}",  # Direct LND REST (most Voltage nodes)
        f"https://{host}{path}",        # REST proxy (port 443)
    ]

def _to_hex(r_hash: str) -> str:
    """Convert base64 r_hash to hex if needed."""
    if not r_hash:
        return r_hash
    # Hex strings are longer and only contain 0-9a-f
    try:
        bytes.fromhex(r_hash)
        return r_hash  # Already hex
    except ValueError:
        # Must be base64
        return base64.b64decode(r_hash + "==").hex()

async def create_invoice(
    amount_sats: int,
    memo: str,
    webhook_url: Optional[str] = None,
    expiry_seconds: Optional[int] = None
) -> dict:
    """Create Lightning invoice via LND REST API."""

    payload = {
        "value": str(amount_sats),
        "memo": memo[:200],
        "expiry": str(expiry_seconds or INVOICE_EXPIRY),
    }

    endpoints = _get_endpoints("/v1/invoices")
    last_error = None

    for url in endpoints:
        try:
            logger.info(f"⚡ Trying LND endpoint: {url}")
            async with httpx.AsyncClient(timeout=20.0, verify=True) as client:
                response = await client.post(url, headers=_headers(), json=payload)

            logger.info(f"↩️  Response {response.status_code}: {response.text[:300]}")

            if response.status_code == 200:
                data = response.json()
                payment_hash = _to_hex(data.get("r_hash", ""))
                payment_request = data.get("payment_request", "")

                if not payment_hash or not payment_request:
                    raise Exception(f"Incomplete invoice response: {data}")

                logger.info(f"✅ Invoice created: {payment_hash[:16]}...")
                return {
                    "payment_hash": payment_hash,
                    "payment_request": payment_request,
                    "expires_at": int(data.get("creation_date", 0)) + (expiry_seconds or INVOICE_EXPIRY)
                }

            elif response.status_code in [401, 403]:
                raise Exception(
                    f"LND auth error {response.status_code}: Invalid macaroon or missing invoices:write permission."
                )

            elif response.status_code == 404:
                logger.warning(f"⚠️  404 on {url} — trying next endpoint")
                last_error = f"404 Not Found: {url}"
                continue

            elif response.status_code == 500:
                logger.error(f"❌ LND 500 on {url}: {response.text}")
                last_error = f"LND internal error: {response.text[:200]}"
                # 500 often means bad macaroon encoding — don't retry other ports
                raise Exception(last_error)

            else:
                response.raise_for_status()

        except httpx.RequestError as e:
            logger.warning(f"⚠️  Connection error on {url}: {e}")
            last_error = f"Connection error: {e}"
            continue

        except Exception as e:
            if "auth" in str(e).lower() or "macaroon" in str(e).lower() or "401" in str(e) or "403" in str(e):
                raise  # Never retry auth errors
            last_error = str(e)
            logger.error(f"❌ Error on {url}: {e}")
            continue

    logger.error(f"❌ All LND endpoints failed. Last error: {last_error}")
    raise Exception(f"Failed to create invoice after trying all endpoints: {last_error}")


async def check_payment(payment_hash: str) -> dict:
    """Check payment status via LND REST API."""
    payment_hash = _to_hex(payment_hash)
    endpoints = _get_endpoints(f"/v1/invoice/{payment_hash}")

    for url in endpoints:
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
                response = await client.get(url, headers=_headers())

            if response.status_code == 200:
                data = response.json()
                # LND state: 0=OPEN, 1=SETTLED, 2=CANCELLED, 3=ACCEPTED
                is_paid = data.get("state") == "SETTLED" or data.get("settled") is True
                return {"paid": is_paid, "settled_at": data.get("settle_date")}

            elif response.status_code == 404:
                logger.warning(f"⚠️  Invoice not found on {url}")
                continue

        except Exception as e:
            logger.warning(f"⚠️  check_payment error on {url}: {e}")
            continue

    return {"paid": False, "settled_at": None}