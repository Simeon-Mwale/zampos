# backend/router.py
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from decimal import Decimal
import os
import logging
import json
import aiosqlite

from services.rate_service import fetch_live_rates, zmw_to_sats, format_btc_display, get_cache_metadata
from services.voltage import create_invoice, check_payment
from services.fee_engine import calculate_gas_fee, get_total_fees_collected
from services.phoenix_sweep import sweep_to_phoenix
from database import (
    save_transaction, mark_paid, get_merchant_by_id,
    create_merchant, get_transaction_by_hash, get_merchant_transactions,
    get_transaction_summary
)
from webhooks import handle_voltage_webhook

logger = logging.getLogger(__name__)
router = APIRouter()

DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")
MAX_SATS = int(os.getenv("MAX_INVOICE_SATS", "100000"))
MIN_ZMW = float(os.getenv("MIN_TRANSACTION_ZMW", "1.0"))

# ── Request Models ─────────────────────────────────────────────────────────────

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
    lock_rate: bool = Field(default=True)

    @validator('memo')
    def sanitize_memo(cls, v):
        return v.strip() or "ZamPOS Payment"

    class Config:
        extra = "forbid"


class SweepRequest(BaseModel):
    merchant_id: int = Field(..., gt=0)
    lightning_address: str = Field(..., min_length=5)
    amount_sats: int = Field(..., gt=0)


# ── Price / Rate ───────────────────────────────────────────────────────────────

@router.get("/price/rate")
async def get_exchange_rate(refresh: bool = Query(False)):
    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        cache_meta = get_cache_metadata()
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
    try:
        if zmw <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than 0")
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        sats = zmw_to_sats(zmw, zmw_per_btc)
        if sats == 0:
            raise HTTPException(status_code=502, detail="Rate fetch failed")
        btc = Decimal(str(sats)) / Decimal("100000000")
        cache_meta = get_cache_metadata()
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


# ── Merchant ───────────────────────────────────────────────────────────────────

@router.post("/merchant/register")
async def register_merchant(req: MerchantRegisterRequest):
    try:
        merchant = await create_merchant(shop_name=req.shop_name, location=req.location)
        logger.info(f"✅ Merchant registered: {merchant['shop_name']} (ID: {merchant['merchant_id']})")
        return merchant
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Registration failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to register merchant. Try again.")


@router.get("/merchant/{merchant_id}")
async def get_merchant(merchant_id: int):
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant


@router.get("/merchant/{merchant_id}/transactions")
async def get_merchant_txs(merchant_id: int, limit: int = 50, status: Optional[str] = None):
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    transactions = await get_merchant_transactions(merchant_id, limit, status)
    return {"merchant_id": merchant_id, "transactions": transactions}


@router.get("/merchant/{merchant_id}/summary")
async def get_merchant_summary(merchant_id: int):
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    summary = await get_transaction_summary(merchant_id)
    return {"merchant_id": merchant_id, "summary": summary}


# ── Owner ──────────────────────────────────────────────────────────────────────

@router.get("/owner/earnings")
async def owner_earnings():
    """Platform owner: total gas fees collected across all merchants"""
    return await get_total_fees_collected()


@router.get("/owner/merchants")
async def owner_merchants():
    """Platform owner: list all registered merchants"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, shop_name, location, created_at
                FROM merchants
                ORDER BY created_at DESC
            """)
            rows = await cursor.fetchall()
            return {"merchants": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        logger.error(f"❌ Failed to fetch merchants: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch merchants")


# ── Sweep / Withdrawal ─────────────────────────────────────────────────────────

@router.get("/sweep/balance")
async def get_sweep_balance(merchant_id: int = Query(..., gt=0)):
    try:
        merchant = await get_merchant_by_id(merchant_id)
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT COALESCE(SUM(amount_sats), 0) as total_sats
                FROM transactions
                WHERE merchant_id = ? AND status = 'paid'
            """, (merchant_id,))
            row = await cursor.fetchone()
            total_sats = row["total_sats"] or 0

            # Check previous sweeps logged in gas_fees
            cursor = await db.execute("""
                SELECT COALESCE(SUM(gross_sats), 0) as swept_sats
                FROM gas_fees WHERE merchant_id = ?
            """, (merchant_id,))
            swept = await cursor.fetchone()
            swept_sats = swept["swept_sats"] or 0

            available_sats = max(0, total_sats - swept_sats)
            return {
                "total_sats": total_sats,
                "withdrawn_sats": swept_sats,
                "available_sats": available_sats
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Balance fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch balance")


@router.get("/sweep/estimate")
async def estimate_sweep_fee(
    merchant_id: int = Query(..., gt=0),
    amount_sats: int = Query(..., gt=0)
):
    try:
        merchant = await get_merchant_by_id(merchant_id)
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        fee_result = calculate_gas_fee(amount_sats)
        return {
            "gross_sats": fee_result["gross_sats"],
            "fee_sats": fee_result["fee_sats"],
            "net_sats": fee_result["net_sats"],
            "sweepable": fee_result["sweepable"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fee estimate failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to estimate fee")


@router.post("/sweep/send")
async def send_sweep(req: SweepRequest, background_tasks: BackgroundTasks):
    """Send withdrawal to merchant's Lightning Address via Phoenix sweep."""
    merchant = await get_merchant_by_id(req.merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    if '@' not in req.lightning_address:
        raise HTTPException(status_code=400, detail="Invalid Lightning Address format")

    fee_result = calculate_gas_fee(req.amount_sats)

    if not fee_result["sweepable"]:
        raise HTTPException(status_code=400, detail=fee_result["reason"])

    try:
        sweep = await sweep_to_phoenix(
            amount_sats=fee_result["net_sats"],
            payment_hash=f"manual_{req.merchant_id}_{req.amount_sats}",
            lightning_address=req.lightning_address,
        )

        if not sweep["success"]:
            raise HTTPException(status_code=502, detail=f"Sweep failed: {sweep['error']}")

        # Log fee
        from services.fee_engine import log_gas_fee
        await log_gas_fee(
            payment_hash=f"manual_{req.merchant_id}_{req.amount_sats}",
            merchant_id=req.merchant_id,
            gross_sats=fee_result["gross_sats"],
            fee_sats=fee_result["fee_sats"],
            net_sats=fee_result["net_sats"],
        )

        logger.info(
            f"✅ Manual sweep | merchant={req.merchant_id} "
            f"→ {req.lightning_address} | net={fee_result['net_sats']} sats"
        )

        return {
            "success": True,
            "lightning_address": req.lightning_address,
            "gross_sats": fee_result["gross_sats"],
            "fee_sats": fee_result["fee_sats"],
            "net_sats": fee_result["net_sats"],
            "payment_hash": sweep["payment_hash"],
            "message": f"Withdrawal complete! {fee_result['net_sats']} sats sent."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Sweep failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Withdrawal failed: {str(e)}")


# ── Invoice ────────────────────────────────────────────────────────────────────

@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest, background_tasks: BackgroundTasks):
    if body.amount_zmw < MIN_ZMW:
        raise HTTPException(status_code=400, detail=f"Minimum amount is K{MIN_ZMW}")

    merchant = await get_merchant_by_id(body.merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=True)
        sats = zmw_to_sats(body.amount_zmw, zmw_per_btc)
        if sats == 0:
            raise Exception("Rate conversion failed")

        if sats > MAX_SATS:
            max_zmw = float((Decimal(str(MAX_SATS)) / Decimal("100000000") * zmw_per_btc).quantize(Decimal("0.01")))
            raise HTTPException(status_code=400, detail=f"Amount too high. Max is K{max_zmw} (~{MAX_SATS:,} sats)")

        webhook_url = None
        if os.getenv("ENVIRONMENT") == "production" and os.getenv("WEBHOOK_URL"):
            webhook_url = os.getenv("WEBHOOK_URL")

        invoice = await create_invoice(
            amount_sats=sats,
            memo=f"{body.memo} | Merchant:{body.merchant_id}",
            webhook_url=webhook_url,
            expiry_seconds=1800
        )

        cache_meta = get_cache_metadata()
        saved = await save_transaction(
            payment_hash=invoice["payment_hash"],
            merchant_id=body.merchant_id,
            amount_zmw=body.amount_zmw,
            amount_sats=sats,
            memo=body.memo,
            rate_snapshot={
                "zmw_per_btc": float(zmw_per_btc),
                "sats_per_zmw": float(sats_per_zmw),
                "timestamp": cache_meta["last_updated"]
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
            "rate_timestamp": cache_meta["last_updated"],
            "memo": body.memo,
            "merchant_id": body.merchant_id,
            "expires_in_seconds": 1800
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Invoice creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Payment service temporarily unavailable. Please try again in 30 seconds.")


@router.get("/status/{payment_hash}")
async def invoice_status(payment_hash: str):
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


@router.get("/transactions")
async def get_transactions(limit: int = 50, status: Optional[str] = None):
    return {"transactions": [], "total": 0}


# ── Webhook ────────────────────────────────────────────────────────────────────

@router.post("/webhook/voltage")
async def voltage_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Voltage payment confirmation webhooks"""
    try:
        body = await request.body()
        secret_header = request.headers.get("Voltage-Secret")

        payload = json.loads(body)
        result = await handle_voltage_webhook(payload, background_tasks, secret_header)

        if not result:
            raise HTTPException(status_code=401, detail="Webhook rejected")

        return {"status": "received", "event": payload.get("event")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Webhook processing failed: {e}", exc_info=True)
        return {"status": "error", "message": "Processing failed but acknowledged"}


# ── Background Helpers ─────────────────────────────────────────────────────────

async def verify_payment_fallback(payment_hash: str, merchant_id: int):
    import asyncio
    await asyncio.sleep(5)
    try:
        result = await check_payment(payment_hash)
        if result["paid"]:
            await mark_paid(payment_hash)
            logger.info(f"✅ Fallback verified payment: {payment_hash[:12]}...")
    except Exception as e:
        logger.debug(f"Fallback check failed (non-critical): {e}")