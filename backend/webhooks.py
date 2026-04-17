# backend/webhooks.py
import logging
from database import mark_paid, get_transaction_by_hash
from typing import Dict, Any

logger = logging.getLogger(__name__)

async def handle_voltage_webhook(payload: Dict[str, Any], background_tasks) -> bool:
    """
    Process Voltage webhook events.
    
    Expected payload structure:
    {
      "event": "invoice.settled",
      "data": {
        "payment_hash": "abc123...",
        "amount": 1000,
        "memo": "ZamPOS...",
        "settled_at": "2024-01-15T10:30:00Z"
      },
      "timestamp": 1705315800
    }
    """
    event = payload.get("event")
    data = payload.get("data", {})
    payment_hash = data.get("payment_hash")
    
    if not payment_hash:
        logger.warning(f"⚠️ Webhook missing payment_hash: {payload}")
        return False
    
    # Handle payment confirmation
    if event in ["invoice.settled", "payment.received"]:
        logger.info(f"✅ Webhook: Payment settled {payment_hash[:12]}...")
        
        # Update local DB
        success = await mark_paid(payment_hash)
        if not success:
            logger.warning(f"⚠️ Could not mark paid for {payment_hash}")
        
        # 🇿🇲 Optional: Trigger SMS confirmation via Africa's Talking
        # if os.getenv("AFRICAS_TALKING_API_KEY"):
        #     background_tasks.add_task(
        #         send_payment_sms, 
        #         payment_hash, 
        #         data.get("amount"),
        #         data.get("memo")
        #     )
        
        return True
    
    # Handle other events (optional)
    elif event == "invoice.expired":
        logger.info(f"⏰ Webhook: Invoice expired {payment_hash[:12]}...")
        # Could update status to 'expired' in DB if needed
        return True
    
    else:
        logger.debug(f"🔍 Unhandled webhook event: {event}")
        return True  # Acknowledge but no action

# Optional: SMS notification helper (Africa's Talking integration)
# async def send_payment_sms(payment_hash: str, amount_sats: int, memo: str):
#     """Send payment confirmation SMS to merchant"""
#     # Implementation depends on Africa's Talking SDK
#     pass