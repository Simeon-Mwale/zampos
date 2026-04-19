# backend/services/sms_service.py
# Africa's Talking SMS — ZamPOS v2
# Sign up: https://africastalking.com
# Sandbox: use USERNAME="sandbox" — sends to AT simulator, not real phones (free)
# Production: use your real username + approved Sender ID

import httpx
import os
import logging

logger = logging.getLogger(__name__)

AT_USERNAME   = os.getenv("AFRICASTALKING_USERNAME", "sandbox")
AT_API_KEY    = os.getenv("AFRICASTALKING_API_KEY", "")
AT_SENDER_ID  = os.getenv("AFRICASTALKING_SENDER_ID", "ZamPOS")

# Sandbox vs production endpoints
AT_URLS = {
    "sandbox":    "https://api.sandbox.africastalking.com/version1/messaging",
    "production": "https://api.africastalking.com/version1/messaging",
}


def _sms_url() -> str:
    return AT_URLS["sandbox"] if AT_USERNAME == "sandbox" else AT_URLS["production"]


def _is_configured() -> bool:
    return bool(AT_API_KEY and AT_USERNAME)


def _normalize_phone(phone: str) -> str:
    """
    Normalize Zambian numbers to E.164 (+260XXXXXXXXX).
    Handles: 0971234567 → +260971234567
             260971234567 → +260971234567
             +260971234567 → unchanged
    Also passes through international numbers (e.g. +254 Kenya).
    """
    p = phone.strip().replace(" ", "").replace("-", "")
    if p.startswith("+"):
        return p
    if p.startswith("260") and len(p) == 12:
        return f"+{p}"
    if p.startswith("0") and len(p) == 10:
        return f"+260{p[1:]}"
    return f"+{p}"


def format_payment_sms(
    shop_name: str,
    amount_zmw: float,
    gross_sats: int,
    lightning_address: str,
) -> str:
    """
    Build a concise payment confirmation SMS.
    Kept under 160 chars for single SMS segment.
    """
    short_addr = lightning_address.split("@")[0]
    msg = (
        f"ZamPOS \u26a1 K{amount_zmw:.2f} received!\n"
        f"{gross_sats:,} sats sent to {short_addr}\n"
        f"Powered by ZamPOS"
    )
    return msg[:160]


async def send_sms(phone_number: str, message: str) -> dict:
    """
    Send SMS via Africa's Talking.
    phone_number: any Zambian format — normalized automatically.
    Returns { success, message_id, error }
    """
    if not _is_configured():
        logger.warning("⚠️ Africa's Talking not configured — SMS skipped")
        return {"success": False, "message_id": None, "error": "AT not configured"}

    phone_e164 = _normalize_phone(phone_number)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _sms_url(),
                headers={
                    "apiKey":       AT_API_KEY,
                    "Accept":       "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "username": AT_USERNAME,
                    "to":       phone_e164,
                    "message":  message,
                    "from":     AT_SENDER_ID,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        recipients = data.get("SMSMessageData", {}).get("Recipients", [])
        if not recipients:
            return {"success": False, "message_id": None, "error": "No recipients in AT response"}

        recipient = recipients[0]
        status    = recipient.get("status", "")
        msg_id    = recipient.get("messageId", "")

        if status == "Success":
            logger.info(f"📱 SMS sent → {phone_e164} | id={msg_id}")
            return {"success": True, "message_id": msg_id, "error": None}
        else:
            code = recipient.get("statusCode", status)
            logger.warning(f"⚠️ SMS issue: {code} → {phone_e164}")
            return {"success": False, "message_id": None, "error": str(code)}

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ AT HTTP {e.response.status_code}: {e.response.text[:100]}")
        return {"success": False, "message_id": None, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"❌ SMS failed: {e}")
        return {"success": False, "message_id": None, "error": str(e)}


async def send_payment_confirmation(
    phone_number: str,
    shop_name: str,
    amount_zmw: float,
    gross_sats: int,
    lightning_address: str,
) -> dict:
    """
    High-level helper: format + send payment confirmation SMS to merchant.
    Called after invoice is confirmed as paid.
    """
    message = format_payment_sms(
        shop_name=shop_name,
        amount_zmw=amount_zmw,
        gross_sats=gross_sats,
        lightning_address=lightning_address,
    )
    return await send_sms(phone_number, message)