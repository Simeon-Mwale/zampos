from fastapi import APIRouter, Request
from database import mark_paid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/payment")
async def payment_webhook(request: Request):
    """LNbits calls this when a payment is settled."""
    try:
        body = await request.json()
        payment_hash = body.get("payment_hash")
        if payment_hash:
            mark_paid(payment_hash)
            logger.info(f"✅ Payment received: {payment_hash}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}
