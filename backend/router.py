# backend/router.py — Updated for live ZMW→USD→BTC→sats flow
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from decimal import Decimal
import os
import logging

# Import our new rate service
from services.rate_service import fetch_live_rates, zmw_to_sats, format_btc_display, get_cache_metadata
from services.voltage import create_invoice, check_payment
from database import (
    save_transaction, mark_paid, get_merchant_by_id, 
    create_merchant, get_transaction_by_hash, get_merchant_transactions,
    get_transaction_summary
)
from webhooks import handle_voltage_webhook

logger = logging.getLogger(__name__)
router = APIRouter()

# Configuration
MAX_SATS = int(os.getenv("MAX_INVOICE_SATS", "100000"))
MIN_ZMW = float(os.getenv("MIN_TRANSACTION_ZMW", "1.0"))

# ------------------------
# Request Models
# ------------------------

class MerchantRegisterRequest(BaseModel):
    shop_name: str = Field(..., min_length=2, max_length=100)
    location: Optional[str] = Field(None, max_length=200)
    
    @validator('shop_name')
    def validate_shop_name(cls, v):
        return v.strip()

class CreateInvoiceRequest(BaseModel):
    merchant_id: int = Field(..., gt=0)
    amount_zmw: float = Field(..., gt=0, le=1_000_000)
    memo: str = Field(default="ZamPOS Payment", max_length=200)
    lock_rate: bool = Field(default=True, description="Lock rate at invoice creation time")
    
    @validator('memo')
    def sanitize_memo(cls, v):
        return v.strip() or "ZamPOS Payment"
    
    class Config:
        extra = "forbid"

class WebhookRequest(BaseModel):
    event: str
    data: Dict[str, Any]
    timestamp: int
    signature: Optional[str] = None

# ------------------------
# Routes: Price/Rate Endpoints
# ------------------------

@router.get("/price/rate")
async def get_exchange_rate(refresh: bool = Query(False, description="Force fresh fetch")):
    """
    Get live BTC/ZMW exchange rate via ZMW→USD→BTC flow.
    Returns: { "zmw_per_btc": number, "sats_per_zmw": number, "last_updated": timestamp }
    """
    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        cache_meta = get_cache_metadata()  # ✅ Use public helper
        
        return {
            "zmw_per_btc": float(zmw_per_btc),
            "sats_per_zmw": float(sats_per_zmw),
            "last_updated": cache_meta["last_updated"],
            "source": cache_meta["source"],
            "cache_valid": cache_meta["is_valid"]
        }
    except Exception as e:
        logger.error(f"❌ Rate fetch failed: {e}")
        return {
            "zmw_per_btc": 1500000.0,
            "sats_per_zmw": 0.06666667,
            "last_updated": None,
            "source": "fallback",
            "cache_valid": False,
            "warning": "Using emergency fallback rates"
        }

@router.get("/price/convert")
async def convert_price(zmw: float, refresh: bool = Query(False)):
    """Convert ZMW amount to sats/BTC with live rates"""
    try:
        if zmw <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than 0")
        
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        sats = zmw_to_sats(zmw, zmw_per_btc)
        if sats == 0:
            raise HTTPException(status_code=502, detail="Rate fetch failed")
        
        btc = Decimal(str(sats)) / Decimal("100000000")
        cache_meta = get_cache_metadata()  # ✅ Use public helper
        
        return {
            "zmw": round(zmw, 2),
            "sats": sats,
            "btc": float(btc),
            "btc_display": format_btc_display(zmw, zmw_per_btc),
            "rate_zmw_per_btc": float(zmw_per_btc),
            "rate_sats_per_zmw": float(sats_per_zmw),
            "rate_timestamp": cache_meta["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Conversion failed: {e}")
        raise HTTPException(status_code=502, detail="Conversion failed. Try again.")

# ------------------------
# Routes: Merchant Endpoints
# ------------------------

@router.post("/merchant/register")
async def register_merchant(req: MerchantRegisterRequest):
    """Register new merchant"""
    try:
        merchant = await create_merchant(
            shop_name=req.shop_name,
            location=req.location
        )
        logger.info(f"✅ Merchant registered: {merchant['shop_name']} (ID: {merchant['merchant_id']})")
        return merchant
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Registration failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to register merchant. Try again.")

@router.get("/merchant/{merchant_id}")
async def get_merchant(merchant_id: int):
    """Get merchant details by ID"""
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant

# ------------------------
# Routes: Invoice Endpoints
# ------------------------

@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest, background_tasks: BackgroundTasks):
    """Create Lightning invoice with LIVE rate at creation time"""
    
    if body.amount_zmw < MIN_ZMW:
        raise HTTPException(status_code=400, detail=f"Minimum amount is K{MIN_ZMW}")
    
    merchant = await get_merchant_by_id(body.merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    try:
        # 🔑 CRITICAL: Fetch FRESH rates at invoice creation
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=True)
        
        # Precision-safe conversion
        sats = zmw_to_sats(body.amount_zmw, zmw_per_btc)
        if sats == 0:
            raise Exception("Rate conversion failed")
        
        if sats > MAX_SATS:
            max_zmw = float((Decimal(str(MAX_SATS)) / Decimal("100000000") * zmw_per_btc).quantize(Decimal("0.01")))
            raise HTTPException(
                status_code=400,
                detail=f"Amount too high. Max is K{max_zmw} (~{MAX_SATS:,} sats)"
            )
        
        # Create Lightning invoice via Voltage
        webhook_url = None
        if os.getenv("ENVIRONMENT") == "production" and os.getenv("WEBHOOK_URL"):
            webhook_url = os.getenv("WEBHOOK_URL")
        
        invoice = await create_invoice(
            amount_sats=sats,
            memo=f"{body.memo} | Merchant:{body.merchant_id}",
            webhook_url=webhook_url,
            expiry_seconds=1800
        )
        
        # ✅ Get cache metadata via public helper
        cache_meta = get_cache_metadata()
        
        # Save transaction with LOCKED rate snapshot
        saved = await save_transaction(
            payment_hash=invoice["payment_hash"],
            merchant_id=body.merchant_id,
            amount_zmw=body.amount_zmw,
            amount_sats=sats,
            memo=body.memo,
            rate_snapshot={
                "zmw_per_btc": float(zmw_per_btc),
                "sats_per_zmw": float(sats_per_zmw),
                "timestamp": cache_meta["last_updated"]  # ✅ Fixed
            }
        )
        if not saved:
            logger.warning(f"⚠️ Transaction save failed but invoice created: {invoice['payment_hash'][:12]}...")
        
        background_tasks.add_task(verify_payment_fallback, invoice["payment_hash"], body.merchant_id)
        
        return {
            "payment_hash": invoice["payment_hash"],
            "payment_request": invoice["payment_request"],
            "amount_zmw": body.amount_zmw,
            "amount_sats": sats,
            "btc_amount": format_btc_display(body.amount_zmw, zmw_per_btc),
            "rate_zmw_per_btc": float(zmw_per_btc),
            "rate_sats_per_zmw": float(sats_per_zmw),
            "rate_timestamp": cache_meta["last_updated"],  # ✅ Fixed
            "memo": body.memo,
            "merchant_id": body.merchant_id,
            "expires_in_seconds": 1800
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Invoice creation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=502, 
            detail="Payment service temporarily unavailable. Please try again in 30 seconds."
        )

@router.get("/status/{payment_hash}")
async def invoice_status(payment_hash: str):
    """Check payment status - with local DB fallback"""
    
    local_tx = await get_transaction_by_hash(payment_hash)
    if local_tx and local_tx["status"] == "paid":
        return {"payment_hash": payment_hash, "paid": True}
    
    try:
        result = await check_payment(payment_hash)
        if result["paid"] and local_tx:
            await mark_paid(payment_hash)
        return {
            "payment_hash": payment_hash,
            "paid": result["paid"],
            "settled_at": result.get("settled_at")
        }
    except Exception as e:
        logger.warning(f"⚠️ Status check failed, returning local state: {e}")
        return {
            "payment_hash": payment_hash,
            "paid": local_tx["status"] == "paid" if local_tx else False
        }

# ------------------------
# Routes: Transaction Endpoints
# ------------------------

@router.get("/transactions")
async def get_transactions(limit: int = 50, status: Optional[str] = None):
    """Get all transactions (admin view)"""
    return {"transactions": [], "total": 0}

@router.get("/merchant/{merchant_id}/transactions")
async def get_merchant_txs(merchant_id: int, limit: int = 50, status: Optional[str] = None):
    """Get transactions for a specific merchant"""
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    transactions = await get_merchant_transactions(merchant_id, limit, status)
    return {"merchant_id": merchant_id, "transactions": transactions}

@router.get("/merchant/{merchant_id}/summary")
async def get_merchant_summary(merchant_id: int):
    """Get sales summary for a merchant"""
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    summary = await get_transaction_summary(merchant_id)
    return {"merchant_id": merchant_id, "summary": summary}

# ------------------------
# Routes: Webhook Endpoints
# ------------------------

@router.post("/webhook/voltage")
async def voltage_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Voltage payment confirmation webhooks"""
    try:
        body = await request.body()
        signature = request.headers.get("X-Voltage-Signature")
        
        if os.getenv("ENVIRONMENT") == "production":
            from services.voltage import verify_webhook_signature
            if not await verify_webhook_signature(body, signature):
                logger.warning("❌ Webhook signature verification failed")
                raise HTTPException(status_code=401, detail="Invalid signature")
        
        import json
        payload = json.loads(body)
        result = await handle_voltage_webhook(payload, background_tasks)
        
        return {"status": "received", "event": payload.get("event")}
        
    except Exception as e:
        logger.error(f"❌ Webhook processing failed: {e}", exc_info=True)
        return {"status": "error", "message": "Processing failed but acknowledged"}

# ------------------------
# Background Helpers
# ------------------------

async def verify_payment_fallback(payment_hash: str, merchant_id: int):
    """Fallback payment check if webhook fails (runs after 5s delay)"""
    import asyncio
    await asyncio.sleep(5)
    try:
        result = await check_payment(payment_hash)
        if result["paid"]:
            await mark_paid(payment_hash)
            logger.info(f"✅ Fallback verified payment: {payment_hash[:12]}...")
    except Exception as e:
        logger.debug(f"Fallback check failed (non-critical): {e}")