# backend/router.py — ZamPOS v2.1: Direct + Custodial modes
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query
from pydantic import BaseModel, Field, validator
from typing import Optional
from decimal import Decimal
import os, logging, json
import aiosqlite

from services.sweep_service import sweep_gas_fees, get_accumulated_gas_fees, get_sweep_history
from services.rate_service import fetch_live_rates, format_btc_display, get_cache_metadata
from services.lnurl_pay import fetch_invoice_from_lightning_address, validate_lightning_address, extract_payment_hash
from services.spread_engine import calculate_spread, apply_spread_to_rate, is_invoiceable
from services.sms_service import send_payment_confirmation
# NEW: static LNURL service
from services.lnurl_static import (
    build_lnurlp_response, get_lnurl_encoded, get_qr_value, get_lnurlp_url
)
from database import (
    save_transaction, mark_paid, mark_sms_sent,
    get_merchant_by_id, create_merchant, update_merchant,
    get_transaction_by_hash, get_merchant_transactions,
    get_transaction_summary, get_operator_earnings,
    credit_custodial_balance, debit_custodial_balance,
    create_withdrawal, mark_withdrawal_sent, mark_withdrawal_failed,
    get_merchant_withdrawals,
)

logger   = logging.getLogger(__name__)
router   = APIRouter()
DB_PATH  = os.getenv("DATABASE_PATH", "./data/zampos.db")
MAX_SATS = int(os.getenv("MAX_INVOICE_SATS", "100000"))
MIN_ZMW  = float(os.getenv("MIN_TRANSACTION_ZMW", "1.0"))
OPERATOR_LIGHTNING_ADDRESS = os.getenv("OPERATOR_LIGHTNING_ADDRESS", "flashysuit96@walletofsatoshi.com")


# ── Models ─────────────────────────────────────────────────────────────────────

class MerchantRegisterRequest(BaseModel):
    shop_name:         str           = Field(..., min_length=2, max_length=100)
    location:          Optional[str] = Field(None, max_length=200)
    phone_number:      str           = Field(..., min_length=8, max_length=20)
    payout_mode:       str           = Field(..., pattern="^(direct|custodial)$")
    lightning_address: Optional[str] = Field(None, max_length=200)

    @validator("shop_name")
    def clean_name(cls, v): return v.strip()

    @validator("phone_number")
    def clean_phone(cls, v):
        v = v.strip().replace(" ", "").replace("-", "")
        if not v: raise ValueError("Phone number required")
        return v

    @validator("lightning_address", always=True)
    def validate_addr(cls, v, values):
        mode = values.get("payout_mode")
        if mode == "direct":
            if not v: raise ValueError("Lightning Address required for Direct mode")
            v = v.strip().lower()
            if "@" not in v: raise ValueError("Must be user@domain.com")
        return v.strip().lower() if v else None

    class Config:
        extra = "forbid"


class MerchantUpdateRequest(BaseModel):
    phone_number:      Optional[str] = Field(None, max_length=20)
    lightning_address: Optional[str] = Field(None, max_length=200)
    location:          Optional[str] = Field(None, max_length=200)
    payout_mode:       Optional[str] = Field(None, pattern="^(direct|custodial)$")

    @validator("lightning_address")
    def clean_addr(cls, v):
        if v:
            v = v.strip().lower()
            if "@" not in v: raise ValueError("Must be user@domain.com")
        return v

    class Config:
        extra = "forbid"


class CreateInvoiceRequest(BaseModel):
    merchant_id: int   = Field(..., gt=0)
    amount_zmw:  float = Field(..., gt=0, le=1_000_000)
    memo:        str   = Field(default="ZamPOS Payment", max_length=200)
    lock_rate:   bool  = Field(default=True)

    @validator("memo")
    def clean_memo(cls, v): return v.strip() or "ZamPOS Payment"

    class Config:
        extra = "forbid"


class WithdrawRequest(BaseModel):
    lightning_address: str           = Field(..., min_length=5, max_length=200)
    amount_sats:       Optional[int] = Field(None, gt=0)
    note:              Optional[str] = Field(None, max_length=200)

    @validator("lightning_address")
    def clean_addr(cls, v):
        v = v.strip().lower()
        if "@" not in v: raise ValueError("Must be user@domain.com")
        return v

    class Config:
        extra = "forbid"


class ConfirmPaidRequest(BaseModel):
    payment_hash: str = Field(..., min_length=10)

    class Config:
        extra = "forbid"


# ── Rate ───────────────────────────────────────────────────────────────────────

@router.get("/price/rate")
async def get_exchange_rate(refresh: bool = Query(False)):
    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        cache_meta = get_cache_metadata()
        real_rate  = float(zmw_per_btc)
        return {
            "zmw_per_btc":           real_rate,
            "displayed_zmw_per_btc": apply_spread_to_rate(real_rate),
            "sats_per_zmw":          float(sats_per_zmw),
            "last_updated":          cache_meta["last_updated"],
            "source":                cache_meta["source"],
            "cache_valid":           cache_meta["is_valid"],
        }
    except Exception as e:
        logger.error(f"❌ Rate: {e}")
        return {"zmw_per_btc":1500000.0,"displayed_zmw_per_btc":1492500.0,"sats_per_zmw":0.06666667,
                "last_updated":None,"source":"fallback","cache_valid":False,"warning":"Using fallback rates"}


@router.get("/price/convert")
async def convert_price(zmw: float, refresh: bool = Query(False)):
    if zmw <= 0: raise HTTPException(400, "Amount must be > 0")
    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        real_rate = float(zmw_per_btc)
        gross_sats, merchant_sats, operator_sats = calculate_spread(zmw, real_rate)
        if gross_sats == 0: raise HTTPException(502, "Rate conversion failed")
        cache_meta = get_cache_metadata()
        return {
            "zmw": round(zmw,2), "sats": gross_sats, "merchant_sats": merchant_sats,
            "operator_sats": operator_sats,
            "btc": float(Decimal(str(gross_sats))/Decimal("100000000")),
            "btc_display": format_btc_display(zmw, zmw_per_btc),
            "rate_zmw_per_btc": real_rate,
            "displayed_zmw_per_btc": apply_spread_to_rate(real_rate),
            "rate_sats_per_zmw": float(sats_per_zmw),
            "rate_timestamp": cache_meta["last_updated"],
        }
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Convert: {e}"); raise HTTPException(502, "Conversion failed")


# ── Merchant ───────────────────────────────────────────────────────────────────

@router.post("/merchant/register")
async def register_merchant(req: MerchantRegisterRequest):
    wallet_info = {}

    if req.payout_mode == "direct":
        v = await validate_lightning_address(req.lightning_address)
        if not v["valid"]:
            raise HTTPException(400, f"Invalid Lightning Address: {v['error']}")
        wallet_info = {
            "wallet_min_sats": v["min_sats"],
            "wallet_max_sats": v["max_sats"],
            "wallet_domain": v["domain"]
        }

    try:
        lightning_address = req.lightning_address or ""
        m = await create_merchant(
            shop_name=req.shop_name,
            phone_number=req.phone_number,
            payout_mode=req.payout_mode,
            location=req.location,
            lightning_address=lightning_address
        )
        return {**m, **wallet_info}

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"❌ register: {e}")
        raise HTTPException(400, "Registration failed")

@router.patch("/merchant/{merchant_id}")
async def update_merchant_details(merchant_id: int, req: MerchantUpdateRequest):
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")
    if req.lightning_address:
        v = await validate_lightning_address(req.lightning_address)
        if not v["valid"]: raise HTTPException(400, f"Cannot reach '{req.lightning_address}': {v['error']}")
    ok = await update_merchant(merchant_id=merchant_id, phone_number=req.phone_number,
                                lightning_address=req.lightning_address, location=req.location,
                                payout_mode=req.payout_mode)
    if not ok: raise HTTPException(502, "Update failed")
    return await get_merchant_by_id(merchant_id)


@router.get("/merchant/{merchant_id}")
async def get_merchant(merchant_id: int):
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")
    return m


@router.get("/merchant/{merchant_id}/transactions")
async def get_merchant_txs(merchant_id: int, limit: int = 50, status: Optional[str] = None):
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")
    return {"merchant_id": merchant_id, "transactions": await get_merchant_transactions(merchant_id, limit, status)}


@router.get("/merchant/{merchant_id}/summary")
async def get_merchant_summary(merchant_id: int):
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")
    return {"merchant_id": merchant_id, "summary": await get_transaction_summary(merchant_id)}


# ── Custodial Withdrawal ───────────────────────────────────────────────────────

@router.post("/merchant/{merchant_id}/withdraw")
async def request_withdrawal(merchant_id: int, req: WithdrawRequest):
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")
    if m["payout_mode"] != "custodial": raise HTTPException(400, "Only available for custodial merchants")
    balance = m["custodial_balance_sats"]
    if balance <= 0: raise HTTPException(400, "No balance to withdraw")

    v = await validate_lightning_address(req.lightning_address)
    if not v["valid"]: raise HTTPException(400, f"Cannot reach '{req.lightning_address}': {v['error']}")

    amount_sats = req.amount_sats or balance
    if amount_sats > balance: raise HTTPException(400, f"Requested {amount_sats} sats but balance is {balance} sats")

    if not await debit_custodial_balance(merchant_id, amount_sats):
        raise HTTPException(502, "Failed to debit balance. Try again.")

    w = await create_withdrawal(merchant_id=merchant_id, amount_sats=amount_sats,
                                 lightning_address=req.lightning_address, note=req.note)
    logger.info(f"📤 Withdrawal | merchant={merchant_id} | {amount_sats} sats → {req.lightning_address}")
    return {**w, "remaining_balance_sats": balance - amount_sats,
            "message": f"Withdrawal of {amount_sats:,} sats requested. You'll receive them shortly."}


@router.get("/merchant/{merchant_id}/withdrawals")
async def get_withdrawals(merchant_id: int, limit: int = 20):
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")
    return {"merchant_id": merchant_id, "custodial_balance_sats": m["custodial_balance_sats"],
            "withdrawals": await get_merchant_withdrawals(merchant_id, limit)}


# ── Manual Confirm ─────────────────────────────────────────────────────────────

@router.post("/confirm-paid")
async def confirm_paid(req: ConfirmPaidRequest, background_tasks: BackgroundTasks):
    tx = await get_transaction_by_hash(req.payment_hash)
    if not tx: raise HTTPException(404, "Transaction not found")
    if tx["status"] == "paid": return {"success": True, "already_paid": True, "message": "Already confirmed"}
    if tx["status"] == "expired": raise HTTPException(400, "Invoice has expired")

    await mark_paid(req.payment_hash)

    if tx["payout_mode"] == "custodial":
        await credit_custodial_balance(tx["merchant_id"], tx["gross_sats"])
        logger.info(f"💰 Custodial credit | merchant={tx['merchant_id']} +{tx['gross_sats']} sats")

    m = await get_merchant_by_id(tx["merchant_id"])
    if m:
        background_tasks.add_task(_send_sms_notification,
            payment_hash=req.payment_hash, merchant_phone=m["phone_number"],
            shop_name=m["shop_name"], amount_zmw=tx["amount_zmw"],
            gross_sats=tx["gross_sats"],
            lightning_address=m.get("lightning_address") or OPERATOR_LIGHTNING_ADDRESS)

    return {"success": True, "already_paid": False, "payment_hash": req.payment_hash, "message": "Payment confirmed ✅"}


# ── Invoice ────────────────────────────────────────────────────────────────────

@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest, background_tasks: BackgroundTasks):
    if body.amount_zmw < MIN_ZMW: raise HTTPException(400, f"Minimum amount is K{MIN_ZMW}")
    m = await get_merchant_by_id(body.merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")

    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=True)
        real_rate = float(zmw_per_btc)
        gross_sats, merchant_sats, operator_sats = calculate_spread(body.amount_zmw, real_rate)
        if gross_sats == 0: raise Exception("Rate produced 0 sats")
        ok, reason = is_invoiceable(gross_sats)
        if not ok: raise HTTPException(400, reason)
        if gross_sats > MAX_SATS:
            max_zmw = float((Decimal(str(MAX_SATS))/Decimal("100000000")*Decimal(str(real_rate))).quantize(Decimal("0.01")))
            raise HTTPException(400, f"Amount too high. Max is K{max_zmw:.2f} (~{MAX_SATS:,} sats)")

        payout_mode     = m["payout_mode"]
        invoice_address = m["lightning_address"] if payout_mode == "direct" else OPERATOR_LIGHTNING_ADDRESS

        bolt11       = await fetch_invoice_from_lightning_address(invoice_address, gross_sats, comment=f"{body.memo} | {m['shop_name']}")
        payment_hash = extract_payment_hash(bolt11)
        cache_meta   = get_cache_metadata()

        await save_transaction(payment_hash=payment_hash, merchant_id=body.merchant_id,
            amount_zmw=body.amount_zmw, gross_sats=gross_sats, merchant_sats=merchant_sats,
            operator_sats=operator_sats, memo=body.memo, payout_mode=payout_mode,
            rate_snapshot={"zmw_per_btc": real_rate, "displayed_zmw_per_btc": apply_spread_to_rate(real_rate),
                           "sats_per_zmw": float(sats_per_zmw), "spread_pct": float(os.getenv("ZAMPOS_SPREAD_PCT","0.5")),
                           "timestamp": cache_meta["last_updated"]})

        background_tasks.add_task(_poll_payment, payment_hash=payment_hash,
            merchant_id=body.merchant_id, gross_sats=gross_sats, payout_mode=payout_mode,
            merchant_phone=m["phone_number"], shop_name=m["shop_name"],
            amount_zmw=body.amount_zmw, lightning_address=invoice_address)

        return {
            "payment_hash": payment_hash, "payment_request": bolt11,
            "amount_zmw": body.amount_zmw, "amount_sats": gross_sats,
            "merchant_sats": merchant_sats, "operator_sats": operator_sats,
            "btc_amount": format_btc_display(body.amount_zmw, zmw_per_btc),
            "rate_zmw_per_btc": real_rate,
            "displayed_zmw_per_btc": apply_spread_to_rate(real_rate),
            "rate_sats_per_zmw": float(sats_per_zmw),
            "rate_timestamp": cache_meta["last_updated"],
            "memo": body.memo, "merchant_id": body.merchant_id,
            "payout_mode": payout_mode, "invoice_address": invoice_address,
            "expires_in_seconds": 600,
        }
    except HTTPException: raise
    except ValueError as e: raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"❌ Invoice: {e}", exc_info=True)
        raise HTTPException(502, "Payment service temporarily unavailable. Try again.")


@router.get("/status/{payment_hash}")
async def invoice_status(payment_hash: str):
    tx = await get_transaction_by_hash(payment_hash)
    return {"payment_hash": payment_hash, "paid": bool(tx and tx["status"]=="paid"),
            "status": tx["status"] if tx else "unknown",
            "payout_mode": tx["payout_mode"] if tx else None}


@router.get("/transactions")
async def get_transactions(limit: int = 50):
    return {"transactions": [], "total": 0}


# ── Owner ──────────────────────────────────────────────────────────────────────

@router.get("/owner/earnings")
async def owner_earnings(): return await get_operator_earnings()


@router.get("/owner/merchants")
async def owner_merchants():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id,shop_name,location,phone_number,payout_mode,lightning_address,custodial_balance_sats,created_at FROM merchants ORDER BY created_at DESC")
            rows = await cur.fetchall()
            return {"merchants": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        logger.error(f"❌ owner_merchants: {e}"); raise HTTPException(502, "Failed")


@router.get("/owner/withdrawals")
async def owner_withdrawals():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT w.id,w.merchant_id,m.shop_name,m.phone_number,w.amount_sats,w.lightning_address,w.status,w.note,w.requested_at,w.processed_at FROM withdrawals w JOIN merchants m ON m.id=w.merchant_id ORDER BY w.requested_at DESC")
            rows = [dict(r) for r in await cur.fetchall()]
            return {"withdrawals": rows, "pending_count": sum(1 for r in rows if r["status"]=="pending")}
    except Exception as e:
        logger.error(f"❌ owner_withdrawals: {e}"); raise HTTPException(502, "Failed")


@router.post("/owner/withdrawals/{withdrawal_id}/mark-sent")
async def mark_sent(withdrawal_id: int):
    ok = await mark_withdrawal_sent(withdrawal_id)
    if not ok: raise HTTPException(502, "Failed")
    return {"success": True, "withdrawal_id": withdrawal_id, "status": "sent"}

# ── Auto-Sweep Endpoints ──────────────────────────────────────────────────────

@router.post("/owner/auto-sweep")
async def auto_sweep_gas_fees(force: bool = Query(False)):
    """Automatically sweep accumulated gas fees to operator wallet"""
    try:
        result = await sweep_gas_fees(force=force)
        return result
    except Exception as e:
        logger.error(f"❌ Auto-sweep error: {e}")
        raise HTTPException(502, f"Auto-sweep failed: {str(e)}")


@router.get("/owner/gas-fees")
async def get_gas_fees_status():
    """Get current gas fees accumulation status"""
    try:
        total_fees, details = await get_accumulated_gas_fees()
        return {
            "total_fees_sats": total_fees,
            "min_sweep_threshold": int(os.getenv("MIN_SWEEP_SATS", "10000")),
            "transaction_count": details["transaction_count"],
            "first_transaction": details["first_transaction"],
            "last_transaction": details["last_transaction"],
            "last_sweep_at": details["last_sweep_at"],
            "last_sweep_amount": details["last_sweep_amount"],
            "operator_wallet": os.getenv("OPERATOR_WALLET", "flashysuit96@walletofsatoshi.com")
        }
    except Exception as e:
        logger.error(f"❌ Gas fees status error: {e}")
        raise HTTPException(502, "Failed to get gas fees status")


@router.get("/owner/sweep-history")
async def sweep_history(limit: int = Query(50)):
    """Get history of operator sweeps"""
    try:
        history = await get_sweep_history(limit)
        return {"sweeps": history, "total": len(history)}
    except Exception as e:
        logger.error(f"❌ Sweep history error: {e}")
        raise HTTPException(502, "Failed to get sweep history")
    
# ── Webhook ────────────────────────────────────────────────────────────────────

@router.post("/webhook/payment")
async def payment_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        payment_hash = body.get("paymentHash") or body.get("payment_hash") or body.get("hash")
        if not payment_hash: return {"status": "ignored", "reason": "no payment_hash"}
        tx = await get_transaction_by_hash(payment_hash)
        if not tx: return {"status": "ignored"}
        if tx["status"] == "paid": return {"status": "already_processed"}
        await mark_paid(payment_hash)
        if tx["payout_mode"] == "custodial":
            await credit_custodial_balance(tx["merchant_id"], tx["gross_sats"])
        m = await get_merchant_by_id(tx["merchant_id"])
        if m:
            background_tasks.add_task(_send_sms_notification,
                payment_hash=payment_hash, merchant_phone=m["phone_number"],
                shop_name=m["shop_name"], amount_zmw=tx["amount_zmw"],
                gross_sats=tx["gross_sats"],
                lightning_address=m.get("lightning_address") or OPERATOR_LIGHTNING_ADDRESS)
        return {"status": "received", "payment_hash": payment_hash}
    except Exception as e:
        logger.error(f"❌ Webhook: {e}", exc_info=True); return {"status": "error"}


# ── NEW: Static LNURL-pay endpoints ───────────────────────────────────────────
#
# These two endpoints together implement the LNURL-pay spec:
#   Step 1: GET /merchant/{id}/lnurl          → wallet fetches metadata
#   Step 2: GET /merchant/{id}/lnurl/callback → wallet fetches bolt11 invoice
#
# The QR code encodes: lightning:LNURL1... (bech32 of the step-1 URL)
# Vendors print this once. Customers scan it and enter any ZMW amount.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/merchant/{merchant_id}/lnurl")
async def lnurl_pay_metadata(merchant_id: int):
    """
    LNURL-pay Step 1: wallet fetches this to learn min/max amounts and description.
    Returns spec-compliant payRequest metadata.
    Works for BOTH direct and custodial merchants.
    """
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")

    return build_lnurlp_response(
        merchant_id=merchant_id,
        shop_name=m["shop_name"],
        location=m.get("location"),
    )


@router.get("/merchant/{merchant_id}/lnurl/callback")
async def lnurl_pay_callback(
    merchant_id: int,
    amount: int,                          # msats — sent by wallet
    comment: Optional[str] = Query(None),
    background_tasks: BackgroundTasks = None,
):
    """
    LNURL-pay Step 2: wallet sends amount in msats, we return a bolt11 invoice.

    Direct mode:    Fetch invoice from merchant's own Lightning Address.
                    ZamPOS is just a router — zero custody.
    Custodial mode: Fetch invoice from operator wallet, credit merchant on payment.
    """
    m = await get_merchant_by_id(merchant_id)
    if not m:
        return {"status": "ERROR", "reason": "Merchant not found"}

    # Validate amount
    from services.lnurl_static import GLOBAL_MIN_SATS, GLOBAL_MAX_SATS
    min_msats = GLOBAL_MIN_SATS * 1000
    max_msats = GLOBAL_MAX_SATS * 1000

    if amount < min_msats:
        return {"status": "ERROR", "reason": f"Amount too low. Minimum is {GLOBAL_MIN_SATS} sats"}
    if amount > max_msats:
        return {"status": "ERROR", "reason": f"Amount too high. Maximum is {GLOBAL_MAX_SATS} sats"}

    amount_sats = amount // 1000

    # Convert sats → ZMW using live rate
    try:
        zmw_per_btc, _ = await fetch_live_rates(force_refresh=False)
        real_rate = float(zmw_per_btc)
        amount_zmw = round((amount_sats / 1e8) * real_rate, 2)
    except Exception:
        amount_zmw = 0.0  # fallback — still works, just no ZMW record

    # Apply spread to get gross/merchant/operator split
    try:
        gross_sats, merchant_sats, operator_sats = calculate_spread(amount_zmw, real_rate)
        # For LNURL static QR, amount_sats IS gross_sats (customer chose the sats amount)
        # Override gross to match what was requested
        gross_sats = amount_sats
    except Exception:
        gross_sats = amount_sats
        merchant_sats = amount_sats
        operator_sats = 0

    # Choose invoice source
    payout_mode     = m["payout_mode"]
    invoice_address = m["lightning_address"] if payout_mode == "direct" else OPERATOR_LIGHTNING_ADDRESS

    memo = comment or f"ZamPOS · {m['shop_name']}"

    try:
        bolt11 = await fetch_invoice_from_lightning_address(
            invoice_address, gross_sats, comment=memo
        )
        payment_hash = extract_payment_hash(bolt11)
        cache_meta   = get_cache_metadata()

        # Save to DB — same as regular invoice
        await save_transaction(
            payment_hash=payment_hash,
            merchant_id=merchant_id,
            amount_zmw=amount_zmw,
            gross_sats=gross_sats,
            merchant_sats=merchant_sats,
            operator_sats=operator_sats,
            memo=memo,
            payout_mode=payout_mode,
            rate_snapshot={
                "zmw_per_btc": real_rate,
                "displayed_zmw_per_btc": apply_spread_to_rate(real_rate),
                "sats_per_zmw": float(_) if _ else 0,
                "source": "lnurl_static",
                "timestamp": cache_meta["last_updated"],
            }
        )

        # Start background polling (same as regular invoice)
        if background_tasks:
            background_tasks.add_task(
                _poll_payment,
                payment_hash=payment_hash,
                merchant_id=merchant_id,
                gross_sats=gross_sats,
                payout_mode=payout_mode,
                merchant_phone=m["phone_number"],
                shop_name=m["shop_name"],
                amount_zmw=amount_zmw,
                lightning_address=invoice_address,
            )

        logger.info(f"⚡ LNURL invoice | merchant={merchant_id} | {gross_sats} sats | {payout_mode}")

        return {"pr": bolt11, "routes": []}

    except Exception as e:
        logger.error(f"❌ LNURL callback: {e}", exc_info=True)
        return {"status": "ERROR", "reason": "Could not generate invoice. Try again."}


@router.get("/merchant/{merchant_id}/lnurl/info")
async def lnurl_info(merchant_id: int):
    """
    Returns the LNURL strings and QR value for the frontend to display.
    Used by StaticQRCard component.
    """
    m = await get_merchant_by_id(merchant_id)
    if not m: raise HTTPException(404, "Merchant not found")

    return {
        "merchant_id":   merchant_id,
        "shop_name":     m["shop_name"],
        "location":      m.get("location"),
        "payout_mode":   m["payout_mode"],
        "lnurl_url":     get_lnurlp_url(merchant_id),
        "lnurl_encoded": get_lnurl_encoded(merchant_id),
        "qr_value":      get_qr_value(merchant_id),
    }


# ── Background ─────────────────────────────────────────────────────────────────

async def _poll_payment(payment_hash, merchant_id, gross_sats, payout_mode,
                         merchant_phone, shop_name, amount_zmw, lightning_address,
                         max_polls=40, interval=15):
    import asyncio
    await asyncio.sleep(5)
    for _ in range(max_polls):
        try:
            tx = await get_transaction_by_hash(payment_hash)
            if not tx: break
            if tx["status"] == "paid":
                if not tx.get("sms_sent"):
                    await _send_sms_notification(payment_hash, merchant_phone, shop_name,
                                                  amount_zmw, gross_sats, lightning_address)
                break
            if tx["status"] == "expired": break
        except Exception as e: logger.debug(f"Poll: {e}")
        await asyncio.sleep(interval)


async def _send_sms_notification(payment_hash, merchant_phone, shop_name, amount_zmw, gross_sats, lightning_address):
    r = await send_payment_confirmation(phone_number=merchant_phone, shop_name=shop_name,
                                         amount_zmw=amount_zmw, gross_sats=gross_sats,
                                         lightning_address=lightning_address)
    if r["success"]: await mark_sms_sent(payment_hash); logger.info(f"📱 SMS → {merchant_phone}")
    else: logger.warning(f"⚠️ SMS failed: {r['error']}")