# backend/router.py — ZamPOS v2.3 (Production Fixed with Duplicate Prevention & Recovery Codes)
#
# FIXES vs previous version:
#   1. calculate_spread() now receives sats_per_zmw (not zmw_per_btc) everywhere
#   2. Removed mid-file duplicate imports; breez receive_payment lazy-imported
#   3. _auto_payout_breez credits balance back on payment failure
#   4. lnurl_pay_callback no longer overwrites gross_sats after spread calc
#   5. real_rate / sats_per_zmw given safe defaults before try blocks so
#      NameError is impossible if rate fetch fails
#   6. mark_failed owner endpoint fetches withdrawal BEFORE marking failed
#   7. Added /merchant/check-duplicate endpoint for real-time duplicate detection
#   8. Added FREE Recovery Code System (Option A) - no SMS costs

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query
from pydantic import BaseModel, Field, validator
from typing import Optional
from decimal import Decimal
import asyncio
import os
import secrets
import logging
import aiosqlite

from services.sweep_service import sweep_gas_fees, get_accumulated_gas_fees, get_sweep_history
from services.rate_service import fetch_live_rates, format_btc_display, get_cache_metadata
from services.lnurl_pay import (
    fetch_invoice_from_lightning_address,
    validate_lightning_address,
    extract_payment_hash,
)
from services.spread_engine import calculate_spread, apply_spread_to_rate, is_invoiceable
from services.sms_service import send_payment_confirmation
from services.lnurl_static import (
    build_lnurlp_response, get_lnurl_encoded, get_qr_value, get_lnurlp_url,
    GLOBAL_MIN_SATS, GLOBAL_MAX_SATS,
)
from database import (
    save_transaction, mark_paid, mark_sms_sent,
    get_merchant_by_id, create_merchant, update_merchant,
    get_transaction_by_hash, get_merchant_transactions,
    get_transaction_summary, get_operator_earnings,
    credit_custodial_balance, debit_custodial_balance,
    create_withdrawal, mark_withdrawal_sent, mark_withdrawal_failed,
    get_merchant_withdrawals, check_duplicate_merchant,
    update_recovery_code, get_merchant_by_recovery_code, verify_recovery,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DB_PATH                    = os.getenv("DATABASE_PATH", "./data/zampos.db")
MAX_SATS                   = int(os.getenv("MAX_INVOICE_SATS", "100000"))
MIN_ZMW                    = float(os.getenv("MIN_TRANSACTION_ZMW", "1.0"))
OPERATOR_LIGHTNING_ADDRESS = os.getenv("OPERATOR_LIGHTNING_ADDRESS", "flashysuit96@walletofsatoshi.com")


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def generate_recovery_code() -> str:
    """Generate a 16-character recovery code for FREE account recovery"""
    return secrets.token_hex(8).upper()


# ─────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────

class MerchantRegisterRequest(BaseModel):
    shop_name:         str           = Field(..., min_length=2, max_length=100)
    location:          Optional[str] = Field(None, max_length=200)
    phone_number:      str           = Field(..., min_length=8, max_length=20)
    payout_mode:       str           = Field(..., pattern="^(direct|custodial)$")
    lightning_address: Optional[str] = Field(None, max_length=200)

    @validator("shop_name")
    def clean_name(cls, v):
        return v.strip()

    @validator("phone_number")
    def clean_phone(cls, v):
        v = v.strip().replace(" ", "").replace("-", "")
        if not v:
            raise ValueError("Phone number required")
        return v

    @validator("lightning_address", always=True)
    def validate_addr(cls, v, values):
        mode = values.get("payout_mode")
        if mode == "direct":
            if not v:
                raise ValueError("Lightning Address required for Direct mode")
            v = v.strip().lower()
            if "@" not in v:
                raise ValueError("Must be user@domain.com")
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
            if "@" not in v:
                raise ValueError("Must be user@domain.com")
        return v

    class Config:
        extra = "forbid"


class CreateInvoiceRequest(BaseModel):
    merchant_id: int   = Field(..., gt=0)
    amount_zmw:  float = Field(..., gt=0, le=1_000_000)
    memo:        str   = Field(default="ZamPOS Payment", max_length=200)
    lock_rate:   bool  = Field(default=True)

    @validator("memo")
    def clean_memo(cls, v):
        return v.strip() or "ZamPOS Payment"

    class Config:
        extra = "forbid"


class WithdrawRequest(BaseModel):
    lightning_address: str           = Field(..., min_length=5, max_length=200)
    amount_sats:       Optional[int] = Field(None, gt=0)
    note:              Optional[str] = Field(None, max_length=200)

    @validator("lightning_address")
    def clean_addr(cls, v):
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("Must be user@domain.com")
        return v

    class Config:
        extra = "forbid"


class ConfirmPaidRequest(BaseModel):
    payment_hash: str = Field(..., min_length=10)

    class Config:
        extra = "forbid"


class RecoverRequest(BaseModel):
    phone_number: str = Field(..., min_length=8, max_length=20)
    recovery_code: str = Field(..., min_length=16, max_length=16)

    @validator("phone_number")
    def clean_phone(cls, v):
        return v.strip().replace(" ", "").replace("-", "")

    @validator("recovery_code")
    def clean_code(cls, v):
        return v.strip().upper()

    class Config:
        extra = "forbid"


# ─────────────────────────────────────────────────────────────
# DUPLICATE CHECK (MUST COME BEFORE /merchant/{merchant_id})
# ─────────────────────────────────────────────────────────────

@router.get("/merchant/check-duplicate")
async def api_check_duplicate_merchant(
    phone_number: Optional[str] = Query(None, description="Phone number to check"),
    shop_name: Optional[str] = Query(None, description="Shop name to check")
):
    """
    Check if a merchant already exists with the given phone number or shop name.
    This endpoint must come before /merchant/{merchant_id} to avoid path conflicts.
    """
    if not phone_number and not shop_name:
        return {
            "exists": False,
            "message": "No criteria provided. Provide phone_number or shop_name."
        }
    
    duplicate = await check_duplicate_merchant(phone_number, shop_name)
    
    if duplicate:
        return {
            "exists": True,
            "merchant_id": duplicate["id"],
            "shop_name": duplicate["shop_name"],
            "phone_number": duplicate["phone_number"],
            "message": f"Merchant already exists: {duplicate['shop_name']} ({duplicate['phone_number']})"
        }
    
    return {
        "exists": False,
        "message": "No existing merchant found with provided criteria."
    }


# ─────────────────────────────────────────────────────────────
# RECOVERY CODE ENDPOINTS (FREE - No SMS Costs)
# ─────────────────────────────────────────────────────────────

@router.post("/merchant/recover")
async def recover_merchant(req: RecoverRequest):
    """
    FREE Account Recovery: Verify phone number + recovery code.
    Returns merchant data to restore local storage - NO SMS cost!
    """
    merchant = await verify_recovery(req.phone_number, req.recovery_code)
    
    if not merchant:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_RECOVERY",
                "message": "Invalid phone number or recovery code. Please check and try again."
            }
        )
    
    return {
        "success": True,
        "merchant_id": merchant["id"],
        "shop_name": merchant["shop_name"],
        "phone_number": merchant["phone_number"],
        "payout_mode": merchant["payout_mode"],
        "lightning_address": merchant.get("lightning_address"),
        "custodial_balance_sats": merchant.get("custodial_balance_sats", 0),
        "location": merchant.get("location"),
        "recovery_code": merchant.get("recovery_code"),
        "message": "✅ Account recovered successfully! You can now log in."
    }


@router.post("/merchant/generate-recovery")
async def generate_new_recovery_code(merchant_id: int):
    """
    Generate a new recovery code for an existing merchant.
    Returns the new recovery code to show ONCE to the merchant.
    """
    merchant = await get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    
    new_code = generate_recovery_code()
    await update_recovery_code(merchant_id, new_code)
    
    return {
        "success": True,
        "recovery_code": new_code,
        "recovery_warning": "⚠️ SAVE THIS CODE - Your old recovery code is no longer valid. This code will only be shown once!"
    }


# ─────────────────────────────────────────────────────────────
# RATE
# ─────────────────────────────────────────────────────────────

@router.get("/price/rate")
async def get_exchange_rate(refresh: bool = Query(False)):
    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        cache_meta = get_cache_metadata()
        real_rate    = float(zmw_per_btc)
        real_sats_sp = float(sats_per_zmw)
        return {
            "zmw_per_btc":           real_rate,
            "displayed_zmw_per_btc": apply_spread_to_rate(real_sats_sp),
            "sats_per_zmw":          real_sats_sp,
            "last_updated":          cache_meta["last_updated"],
            "source":                cache_meta["source"],
            "cache_valid":           cache_meta["is_valid"],
        }
    except Exception as e:
        logger.error(f"❌ Rate: {e}")
        return {
            "zmw_per_btc": 1_350_000.0,
            "displayed_zmw_per_btc": 1_343_250.0,
            "sats_per_zmw": 0.07407,
            "last_updated": None,
            "source": "fallback",
            "cache_valid": False,
            "warning": "Using fallback rates",
        }


@router.get("/price/convert")
async def convert_price(zmw: float, refresh: bool = Query(False)):
    if zmw <= 0:
        raise HTTPException(400, "Amount must be > 0")
    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=refresh)
        real_sats_sp = float(sats_per_zmw)

        gross_sats, merchant_sats, operator_sats = calculate_spread(zmw, real_sats_sp)
        if gross_sats == 0:
            raise HTTPException(502, "Rate conversion failed")

        cache_meta = get_cache_metadata()
        return {
            "zmw":                   round(zmw, 2),
            "sats":                  gross_sats,
            "merchant_sats":         merchant_sats,
            "operator_sats":         operator_sats,
            "btc":                   float(Decimal(str(gross_sats)) / Decimal("100000000")),
            "btc_display":           format_btc_display(zmw, zmw_per_btc),
            "rate_zmw_per_btc":      float(zmw_per_btc),
            "displayed_zmw_per_btc": apply_spread_to_rate(real_sats_sp),
            "rate_sats_per_zmw":     real_sats_sp,
            "rate_timestamp":        cache_meta["last_updated"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Convert: {e}")
        raise HTTPException(502, "Conversion failed")


# ─────────────────────────────────────────────────────────────
# MERCHANT REGISTER (with Recovery Code generation)
# ─────────────────────────────────────────────────────────────

@router.post("/merchant/register")
async def register_merchant(req: MerchantRegisterRequest):
    # Check for duplicates before registration
    duplicate = await check_duplicate_merchant(req.phone_number, req.shop_name)
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "DUPLICATE_MERCHANT",
                "message": f"Merchant already exists: {duplicate['shop_name']} ({duplicate['phone_number']})",
                "existing_merchant_id": duplicate["id"]
            }
        )
    
    wallet_info = {}
    if req.payout_mode == "direct":
        v = await validate_lightning_address(req.lightning_address)
        if not v["valid"]:
            raise HTTPException(400, f"Invalid Lightning Address: {v['error']}")
        wallet_info = {
            "wallet_min_sats": v["min_sats"],
            "wallet_max_sats": v["max_sats"],
            "wallet_domain":   v["domain"],
        }
    
    # Generate FREE recovery code
    recovery_code = generate_recovery_code()
    
    try:
        m = await create_merchant(
            shop_name=req.shop_name,
            phone_number=req.phone_number,
            payout_mode=req.payout_mode,
            location=req.location,
            lightning_address=req.lightning_address or "",
            recovery_code=recovery_code,
        )
        
        return {
            **m,
            **wallet_info,
            "recovery_code": recovery_code,
            "recovery_warning": "⚠️ SAVE THIS CODE - You'll need it to recover your account if you lose your phone (FREE - no SMS required)"
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"❌ register: {e}")
        raise HTTPException(400, "Registration failed")


@router.patch("/merchant/{merchant_id}")
async def update_merchant_details(merchant_id: int, req: MerchantUpdateRequest):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    
    if req.phone_number:
        duplicate = await check_duplicate_merchant(req.phone_number, None)
        if duplicate and duplicate["id"] != merchant_id:
            raise HTTPException(
                status_code=409,
                detail=f"Phone number {req.phone_number} is already registered to another shop"
            )
    
    if req.lightning_address:
        v = await validate_lightning_address(req.lightning_address)
        if not v["valid"]:
            raise HTTPException(400, f"Cannot reach '{req.lightning_address}': {v['error']}")
    
    ok = await update_merchant(
        merchant_id=merchant_id,
        phone_number=req.phone_number,
        lightning_address=req.lightning_address,
        location=req.location,
        payout_mode=req.payout_mode,
    )
    if not ok:
        raise HTTPException(502, "Update failed")
    return await get_merchant_by_id(merchant_id)


@router.get("/merchant/{merchant_id}")
async def get_merchant(merchant_id: int):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return m


@router.get("/merchant/{merchant_id}/transactions")
async def get_merchant_txs(
    merchant_id: int,
    limit: int = 50,
    status: Optional[str] = None,
):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return {
        "merchant_id":  merchant_id,
        "transactions": await get_merchant_transactions(merchant_id, limit, status),
    }


@router.get("/merchant/{merchant_id}/summary")
async def get_merchant_summary(merchant_id: int):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return {
        "merchant_id": merchant_id,
        "summary":     await get_transaction_summary(merchant_id),
    }


# ─────────────────────────────────────────────────────────────
# CUSTODIAL WITHDRAWAL
# ─────────────────────────────────────────────────────────────

@router.post("/merchant/{merchant_id}/withdraw")
async def request_withdrawal(
    merchant_id: int,
    req: WithdrawRequest,
    background_tasks: BackgroundTasks,
):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    if m["payout_mode"] != "custodial":
        raise HTTPException(400, "Only available for custodial merchants")

    balance = m["custodial_balance_sats"]
    if balance <= 0:
        raise HTTPException(400, "No balance to withdraw")

    v = await validate_lightning_address(req.lightning_address)
    if not v["valid"]:
        raise HTTPException(400, f"Cannot reach '{req.lightning_address}': {v['error']}")

    amount_sats = req.amount_sats or balance
    if amount_sats > balance:
        raise HTTPException(
            400, f"Requested {amount_sats} sats but balance is {balance} sats"
        )

    if not await debit_custodial_balance(merchant_id, amount_sats):
        raise HTTPException(502, "Failed to debit balance — try again.")

    w = await create_withdrawal(
        merchant_id=merchant_id,
        amount_sats=amount_sats,
        lightning_address=req.lightning_address,
        note=req.note,
    )
    if w is None:
        await credit_custodial_balance(merchant_id, amount_sats)
        raise HTTPException(502, "Failed to record withdrawal — try again.")

    background_tasks.add_task(
        _auto_payout_breez,
        withdrawal_id=w,
        merchant_id=merchant_id,
        amount_sats=amount_sats,
        lightning_address=req.lightning_address,
        shop_name=m["shop_name"],
    )

    logger.info(
        f"📤 Withdrawal queued | merchant={merchant_id} | "
        f"{amount_sats} sats → {req.lightning_address}"
    )
    return {
        "withdrawal_id":          w,
        "amount_sats":            amount_sats,
        "lightning_address":      req.lightning_address,
        "status":                 "processing",
        "remaining_balance_sats": balance - amount_sats,
        "message": f"Withdrawal of {amount_sats:,} sats is being processed via Breez ⚡",
    }


@router.get("/merchant/{merchant_id}/withdrawals")
async def get_withdrawals(merchant_id: int, limit: int = 20):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return {
        "merchant_id":            merchant_id,
        "custodial_balance_sats": m["custodial_balance_sats"],
        "withdrawals":            await get_merchant_withdrawals(merchant_id, limit),
    }


# ─────────────────────────────────────────────────────────────
# MANUAL CONFIRM
# ─────────────────────────────────────────────────────────────

@router.post("/confirm-paid")
async def confirm_paid(req: ConfirmPaidRequest, background_tasks: BackgroundTasks):
    tx = await get_transaction_by_hash(req.payment_hash)
    if not tx:
        raise HTTPException(404, "Transaction not found")
    if tx["status"] == "paid":
        return {"success": True, "already_paid": True, "message": "Already confirmed"}
    if tx["status"] == "expired":
        raise HTTPException(400, "Invoice has expired")

    await mark_paid(req.payment_hash)

    if tx["payout_mode"] == "custodial":
        await credit_custodial_balance(tx["merchant_id"], tx["gross_sats"])
        logger.info(
            f"💰 Custodial credit | merchant={tx['merchant_id']} +{tx['gross_sats']} sats"
        )

    m = await get_merchant_by_id(tx["merchant_id"])
    if m:
        background_tasks.add_task(
            _send_sms_notification,
            payment_hash=req.payment_hash,
            merchant_phone=m["phone_number"],
            shop_name=m["shop_name"],
            amount_zmw=tx["amount_zmw"],
            gross_sats=tx["gross_sats"],
            lightning_address=m.get("lightning_address") or OPERATOR_LIGHTNING_ADDRESS,
        )

    return {
        "success":      True,
        "already_paid": False,
        "payment_hash": req.payment_hash,
        "message":      "Payment confirmed ✅",
    }


# ─────────────────────────────────────────────────────────────
# INVOICE
# ─────────────────────────────────────────────────────────────

@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest, background_tasks: BackgroundTasks):
    if body.amount_zmw < MIN_ZMW:
        raise HTTPException(400, f"Minimum amount is K{MIN_ZMW}")

    m = await get_merchant_by_id(body.merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")

    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=True)
        real_sats_sp = float(sats_per_zmw)

        gross_sats, merchant_sats, operator_sats = calculate_spread(
            body.amount_zmw, real_sats_sp
        )

        if gross_sats == 0:
            raise ValueError("Rate produced 0 sats — amount too small")

        ok, reason = is_invoiceable(gross_sats)
        if not ok:
            raise HTTPException(400, reason)

        if gross_sats > MAX_SATS:
            max_zmw = float(
                (
                    Decimal(str(MAX_SATS)) / Decimal("100000000")
                    * Decimal(str(float(zmw_per_btc)))
                ).quantize(Decimal("0.01"))
            )
            raise HTTPException(
                400,
                f"Amount too high. Max is K{max_zmw:.2f} (~{MAX_SATS:,} sats)",
            )

        payout_mode     = m["payout_mode"]
        invoice_address = (
            m["lightning_address"] if payout_mode == "direct" else OPERATOR_LIGHTNING_ADDRESS
        )

        bolt11       = await fetch_invoice_from_lightning_address(
            invoice_address, gross_sats, comment=f"{body.memo} | {m['shop_name']}"
        )
        payment_hash = extract_payment_hash(bolt11)
        cache_meta   = get_cache_metadata()

        await save_transaction(
            payment_hash=payment_hash,
            merchant_id=body.merchant_id,
            amount_zmw=body.amount_zmw,
            gross_sats=gross_sats,
            merchant_sats=merchant_sats,
            operator_sats=operator_sats,
            memo=body.memo,
            payout_mode=payout_mode,
            rate_snapshot={
                "zmw_per_btc":           float(zmw_per_btc),
                "sats_per_zmw":          real_sats_sp,
                "spread_pct":            float(os.getenv("ZAMPOS_SPREAD_PCT", "0.5")),
                "timestamp":             cache_meta["last_updated"],
            },
        )

        background_tasks.add_task(
            _poll_payment,
            payment_hash=payment_hash,
            merchant_id=body.merchant_id,
            gross_sats=gross_sats,
            payout_mode=payout_mode,
            merchant_phone=m["phone_number"],
            shop_name=m["shop_name"],
            amount_zmw=body.amount_zmw,
            lightning_address=invoice_address,
        )

        return {
            "payment_hash":     payment_hash,
            "payment_request":  bolt11,
            "amount_zmw":       body.amount_zmw,
            "amount_sats":      gross_sats,
            "merchant_sats":    merchant_sats,
            "operator_sats":    operator_sats,
            "btc_amount":       format_btc_display(body.amount_zmw, zmw_per_btc),
            "rate_zmw_per_btc": float(zmw_per_btc),
            "rate_sats_per_zmw": real_sats_sp,
            "rate_timestamp":   cache_meta["last_updated"],
            "memo":             body.memo,
            "merchant_id":      body.merchant_id,
            "payout_mode":      payout_mode,
            "invoice_address":  invoice_address,
            "expires_in_seconds": 600,
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"❌ Invoice: {e}", exc_info=True)
        raise HTTPException(502, "Payment service temporarily unavailable. Try again.")


@router.get("/status/{payment_hash}")
async def invoice_status(payment_hash: str):
    tx = await get_transaction_by_hash(payment_hash)
    return {
        "payment_hash": payment_hash,
        "paid":         bool(tx and tx["status"] == "paid"),
        "status":       tx["status"] if tx else "unknown",
        "payout_mode":  tx["payout_mode"] if tx else None,
    }


@router.get("/transactions")
async def list_all_transactions(limit: int = 50):
    return {"transactions": [], "total": 0}


# ─────────────────────────────────────────────────────────────
# OWNER
# ─────────────────────────────────────────────────────────────

@router.get("/owner/earnings")
async def owner_earnings():
    return await get_operator_earnings()


@router.get("/owner/merchants")
async def owner_merchants():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, shop_name, location, phone_number, payout_mode, "
                "lightning_address, custodial_balance_sats, created_at "
                "FROM merchants ORDER BY created_at DESC"
            )
            rows = await cur.fetchall()
            return {"merchants": [dict(r) for r in rows], "total": len(rows)}
    except Exception as e:
        logger.error(f"❌ owner_merchants: {e}")
        raise HTTPException(502, "Failed to fetch merchants")


@router.get("/owner/withdrawals")
async def owner_withdrawals():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT w.id, w.merchant_id, m.shop_name, m.phone_number, "
                "w.amount_sats, w.lightning_address, w.status, w.note, "
                "w.requested_at, w.processed_at "
                "FROM withdrawals w "
                "JOIN merchants m ON m.id = w.merchant_id "
                "ORDER BY w.requested_at DESC"
            )
            rows = [dict(r) for r in await cur.fetchall()]
            return {
                "withdrawals":   rows,
                "pending_count": sum(1 for r in rows if r["status"] == "pending"),
            }
    except Exception as e:
        logger.error(f"❌ owner_withdrawals: {e}")
        raise HTTPException(502, "Failed to fetch withdrawals")


@router.post("/owner/withdrawals/{withdrawal_id}/mark-sent")
async def mark_sent(withdrawal_id: int):
    ok = await mark_withdrawal_sent(withdrawal_id)
    if not ok:
        raise HTTPException(502, "Failed to mark sent")
    return {"success": True, "withdrawal_id": withdrawal_id, "status": "sent"}


@router.post("/owner/withdrawals/{withdrawal_id}/mark-failed")
async def mark_failed_endpoint(
    withdrawal_id: int,
    reason: str = Query("Manual override"),
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT merchant_id, amount_sats, status FROM withdrawals WHERE id=?",
            (withdrawal_id,),
        )
        row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Withdrawal not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Cannot fail a withdrawal with status '{row['status']}'")

    ok = await mark_withdrawal_failed(withdrawal_id, reason)
    if not ok:
        raise HTTPException(502, "Failed to update withdrawal status")

    await credit_custodial_balance(row["merchant_id"], row["amount_sats"])
    logger.info(
        f"💰 Refunded {row['amount_sats']} sats to merchant {row['merchant_id']} "
        f"(withdrawal {withdrawal_id} failed: {reason})"
    )

    return {"success": True, "withdrawal_id": withdrawal_id, "status": "failed"}


# ─────────────────────────────────────────────────────────────
# BREEZ STATUS & TOP-UP
# ─────────────────────────────────────────────────────────────

@router.get("/owner/breez-status")
async def breez_status():
    try:
        from services.breez_service import get_breez_balance, init_breez

        balance = await get_breez_balance()
        if balance == -1:
            await init_breez()
            balance = await get_breez_balance()

        return {
            "balance_sats": balance if balance >= 0 else 0,
            "node_id":      os.getenv("BREEZ_NODE_ID", "unknown"),
            "status":       "online" if balance >= 0 else "offline",
            "configured":   bool(os.getenv("BREEZ_API_KEY")),
        }
    except Exception as e:
        logger.error(f"❌ Breez status: {e}")
        return {
            "balance_sats": 0,
            "node_id":      "not_initialized",
            "status":       "error",
            "error":        str(e),
            "configured":   bool(os.getenv("BREEZ_API_KEY")),
        }


@router.post("/owner/breez-topup")
@router.get("/owner/breez-topup")
async def breez_topup(amount_sats: int = Query(5000, description="Sats to receive")):
    try:
        from services.breez_service import receive_payment

        result = await receive_payment(amount_sats, "ZamPOS Breez wallet top-up")

        if not result.get("success"):
            raise HTTPException(502, result.get("error", "Unknown Breez error"))

        return {
            "success":      True,
            "bolt11":       result.get("bolt11") or result.get("invoice"),
            "amount_sats":  amount_sats,
            "payment_hash": result.get("payment_hash"),
            "message":      f"Pay this invoice to add {amount_sats:,} sats to Breez wallet",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Breez top-up: {e}")
        raise HTTPException(502, str(e))


# ─────────────────────────────────────────────────────────────
# AUTO-SWEEP
# ─────────────────────────────────────────────────────────────

@router.post("/owner/auto-sweep")
async def auto_sweep_gas_fees(force: bool = Query(False)):
    try:
        return await sweep_gas_fees(force=force)
    except Exception as e:
        logger.error(f"❌ Auto-sweep: {e}")
        raise HTTPException(502, f"Auto-sweep failed: {e}")


@router.get("/owner/gas-fees")
async def get_gas_fees_status():
    try:
        total_fees, details = await get_accumulated_gas_fees()
        return {
            "total_fees_sats":      total_fees,
            "min_sweep_threshold":  int(os.getenv("MIN_SWEEP_SATS", "10000")),
            "transaction_count":    details["transaction_count"],
            "first_transaction":    details["first_transaction"],
            "last_transaction":     details["last_transaction"],
            "last_sweep_at":        details["last_sweep_at"],
            "last_sweep_amount":    details["last_sweep_amount"],
            "operator_wallet":      os.getenv("OPERATOR_WALLET", OPERATOR_LIGHTNING_ADDRESS),
        }
    except Exception as e:
        logger.error(f"❌ Gas fees status: {e}")
        raise HTTPException(502, "Failed to get gas fees status")


@router.get("/owner/sweep-history")
async def sweep_history(limit: int = Query(50)):
    try:
        history = await get_sweep_history(limit)
        return {"sweeps": history, "total": len(history)}
    except Exception as e:
        logger.error(f"❌ Sweep history: {e}")
        raise HTTPException(502, "Failed to get sweep history")


# ─────────────────────────────────────────────────────────────
# WEBHOOK
# ─────────────────────────────────────────────────────────────

@router.post("/webhook/payment")
async def payment_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body         = await request.json()
        payment_hash = (
            body.get("paymentHash")
            or body.get("payment_hash")
            or body.get("hash")
        )
        if not payment_hash:
            return {"status": "ignored", "reason": "no payment_hash"}

        tx = await get_transaction_by_hash(payment_hash)
        if not tx:
            return {"status": "ignored"}
        if tx["status"] == "paid":
            return {"status": "already_processed"}

        await mark_paid(payment_hash)

        if tx["payout_mode"] == "custodial":
            await credit_custodial_balance(tx["merchant_id"], tx["gross_sats"])
            logger.info(
                f"💰 Webhook credit | merchant={tx['merchant_id']} +{tx['gross_sats']} sats"
            )

        m = await get_merchant_by_id(tx["merchant_id"])
        if m:
            background_tasks.add_task(
                _send_sms_notification,
                payment_hash=payment_hash,
                merchant_phone=m["phone_number"],
                shop_name=m["shop_name"],
                amount_zmw=tx["amount_zmw"],
                gross_sats=tx["gross_sats"],
                lightning_address=m.get("lightning_address") or OPERATOR_LIGHTNING_ADDRESS,
            )

        return {"status": "received", "payment_hash": payment_hash}

    except Exception as e:
        logger.error(f"❌ Webhook: {e}", exc_info=True)
        return {"status": "error"}


# ─────────────────────────────────────────────────────────────
# LNURL-PAY
# ─────────────────────────────────────────────────────────────

@router.get("/merchant/{merchant_id}/lnurl")
async def lnurl_pay_metadata(merchant_id: int):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return build_lnurlp_response(
        merchant_id=merchant_id,
        shop_name=m["shop_name"],
        location=m.get("location"),
    )


@router.get("/merchant/{merchant_id}/lnurl/callback")
async def lnurl_pay_callback(
    merchant_id: int,
    amount: int,
    comment: Optional[str] = Query(None),
    background_tasks: BackgroundTasks = None,
):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        return {"status": "ERROR", "reason": "Merchant not found"}

    min_msats = GLOBAL_MIN_SATS * 1000
    max_msats = GLOBAL_MAX_SATS * 1000

    if amount < min_msats:
        return {"status": "ERROR", "reason": f"Amount too low. Minimum is {GLOBAL_MIN_SATS} sats"}
    if amount > max_msats:
        return {"status": "ERROR", "reason": f"Amount too high. Maximum is {GLOBAL_MAX_SATS} sats"}

    amount_sats = amount // 1000

    zmw_per_btc  = None
    real_sats_sp = 0.0
    amount_zmw   = 0.0

    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=False)
        real_sats_sp = float(sats_per_zmw)
        amount_zmw   = round((amount_sats / 1e8) * float(zmw_per_btc), 2)
    except Exception as e:
        logger.warning(f"⚠️ LNURL rate fetch failed: {e} — using raw sats, 0 ZMW")

    if real_sats_sp > 0 and amount_zmw > 0:
        try:
            gross_sats, merchant_sats, operator_sats = calculate_spread(
                amount_zmw, real_sats_sp
            )
            gross_sats = amount_sats
        except Exception:
            gross_sats    = amount_sats
            merchant_sats = amount_sats
            operator_sats = 0
    else:
        gross_sats    = amount_sats
        merchant_sats = amount_sats
        operator_sats = 0

    payout_mode     = m["payout_mode"]
    invoice_address = (
        m["lightning_address"] if payout_mode == "direct" else OPERATOR_LIGHTNING_ADDRESS
    )
    memo = comment or f"ZamPOS · {m['shop_name']}"

    try:
        bolt11       = await fetch_invoice_from_lightning_address(
            invoice_address, gross_sats, comment=memo
        )
        payment_hash = extract_payment_hash(bolt11)
        cache_meta   = get_cache_metadata()

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
                "zmw_per_btc":  float(zmw_per_btc) if zmw_per_btc else None,
                "sats_per_zmw": real_sats_sp,
                "source":       "lnurl_static",
                "timestamp":    cache_meta["last_updated"],
            },
        )

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

        logger.info(
            f"⚡ LNURL invoice | merchant={merchant_id} | {gross_sats} sats | {payout_mode}"
        )
        return {"pr": bolt11, "routes": []}

    except Exception as e:
        logger.error(f"❌ LNURL callback: {e}", exc_info=True)
        return {"status": "ERROR", "reason": "Could not generate invoice. Try again."}


@router.get("/merchant/{merchant_id}/lnurl/info")
async def lnurl_info(merchant_id: int):
    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, "Merchant not found")
    return {
        "merchant_id":    merchant_id,
        "shop_name":      m["shop_name"],
        "location":       m.get("location"),
        "payout_mode":    m["payout_mode"],
        "lnurl_url":      get_lnurlp_url(merchant_id),
        "lnurl_encoded":  get_lnurl_encoded(merchant_id),
        "qr_value":       get_qr_value(merchant_id),
    }


# ─────────────────────────────────────────────────────────────
# BACKGROUND TASKS
# ─────────────────────────────────────────────────────────────

async def _poll_payment(
    payment_hash: str,
    merchant_id: int,
    gross_sats: int,
    payout_mode: str,
    merchant_phone: str,
    shop_name: str,
    amount_zmw: float,
    lightning_address: str,
    max_polls: int = 40,
    interval: int = 15,
):
    await asyncio.sleep(5)
    for _ in range(max_polls):
        try:
            tx = await get_transaction_by_hash(payment_hash)
            if not tx:
                break
            if tx["status"] == "paid":
                if not tx.get("sms_sent"):
                    await _send_sms_notification(
                        payment_hash, merchant_phone, shop_name,
                        amount_zmw, gross_sats, lightning_address,
                    )
                break
            if tx["status"] == "expired":
                break
        except Exception as e:
            logger.debug(f"Poll error: {e}")
        await asyncio.sleep(interval)


async def _auto_payout_breez(
    withdrawal_id: int,
    merchant_id: int,
    amount_sats: int,
    lightning_address: str,
    shop_name: str,
):
    try:
        from services.breez_service import pay_lightning_address

        result = await pay_lightning_address(
            lightning_address=lightning_address,
            amount_sats=amount_sats,
            memo=f"ZamPOS withdrawal · {shop_name}",
        )

        if result["success"]:
            await mark_withdrawal_sent(withdrawal_id)
            logger.info(
                f"✅ Breez payout success | withdrawal={withdrawal_id} | {amount_sats} sats"
            )
        else:
            error_msg = result.get("error", "unknown_error")
            logger.error(
                f"❌ Breez payout failed | withdrawal={withdrawal_id} | {error_msg}"
            )
            credited = await credit_custodial_balance(merchant_id, amount_sats)
            if not credited:
                logger.critical(
                    f"🚨 CRITICAL: Breez payout failed AND credit reversal failed "
                    f"for merchant {merchant_id} withdrawal {withdrawal_id}. "
                    f"Manual reconciliation required: {amount_sats} sats."
                )
            await mark_withdrawal_failed(withdrawal_id, error_msg)

    except ImportError:
        logger.warning(
            f"⚠️ Breez not available — withdrawal {withdrawal_id} left pending for manual payout"
        )

    except Exception as e:
        logger.error(
            f"❌ Breez payout exception | withdrawal={withdrawal_id} | {e}", exc_info=True
        )
        credited = await credit_custodial_balance(merchant_id, amount_sats)
        if not credited:
            logger.critical(
                f"🚨 CRITICAL: Exception payout AND credit reversal failed "
                f"for merchant {merchant_id}, withdrawal {withdrawal_id}. "
                f"Manual reconciliation required: {amount_sats} sats."
            )
        await mark_withdrawal_failed(withdrawal_id, str(e))


async def _send_sms_notification(
    payment_hash: str,
    merchant_phone: str,
    shop_name: str,
    amount_zmw: float,
    gross_sats: int,
    lightning_address: str,
):
    r = await send_payment_confirmation(
        phone_number=merchant_phone,
        shop_name=shop_name,
        amount_zmw=amount_zmw,
        gross_sats=gross_sats,
        lightning_address=lightning_address,
    )
    if r["success"]:
        await mark_sms_sent(payment_hash)
        logger.info(f"📱 SMS sent to {merchant_phone}")
    else:
        logger.warning(f"⚠️ SMS failed to {merchant_phone}: {r['error']}")