from fastapi import APIRouter, Request
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# In production, replace with a database or event emitter (e.g. Redis pub/sub)
paid_invoices: set = set()


@router.post("/payment")
async def payment_webhook(request: Request):
    """
    LNbits calls this endpoint when a payment is settled.
    Store the payment_hash so the frontend can pick it up via polling.
    """
    try:
        body = await request.json()
        payment_hash = body.get("payment_hash")
        if payment_hash:
            paid_invoices.add(payment_hash)
            logger.info(f"✅ Payment received: {payment_hash}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}
