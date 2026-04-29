# backend/router.py — ZamPOS v2.5 (+ USSD via Africa's Talking + Merchant Short Codes)
#
# CHANGES vs v2.4:
#   + GET  /merchant/code/{short_code}  — lookup merchant by 4-digit short code
#   + POST /ussd                        — Africa's Talking USSD session handler
#   + short_code column auto-assigned on register (zero-padded merchant ID, e.g. 0042)
#   + USSDSession state machine: MAIN_MENU → MERCHANT_PAY | MERCHANT_SELL
#   Everything else is identical to v2.4

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query, Form
from fastapi.responses import PlainTextResponse
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

# ZamPay / BitZed config
BITZED_ENABLED = os.getenv("BITZED_ENABLED", "false").lower() == "true"
BITZED_API_KEY = os.getenv("BITZED_API_KEY", "")
BITZED_API_URL = os.getenv("BITZED_API_URL", "https://api.bitzed.com/v1")


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def generate_recovery_code() -> str:
    """Generate a 16-character recovery code for FREE account recovery"""
    return secrets.token_hex(8).upper()


def _make_zampay_reference() -> str:
    return "ZP-" + secrets.token_hex(6).upper()


def _short_code_from_id(merchant_id: int) -> str:
    """
    Derive a 4-digit short code from merchant ID.
    merchant_id=1  → '0001'
    merchant_id=42 → '0042'
    Codes above 9999 wrap: merchant_id=10001 → '0001' (collision handled in lookup)
    """
    return str(merchant_id % 10000).zfill(4)


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


class ZamPayChargeRequest(BaseModel):
    merchant_id:    int   = Field(..., gt=0)
    customer_phone: str   = Field(..., min_length=9, max_length=20)
    amount_zmw:     float = Field(..., gt=0, le=50_000)
    memo:           str   = Field(default="ZamPay Payment", max_length=200)

    @validator("customer_phone")
    def clean_phone(cls, v):
        v = v.strip().replace(" ", "").replace("-", "")
        if v.startswith("+260"):
            v = "0" + v[4:]
        elif v.startswith("260") and len(v) == 12:
            v = "0" + v[3:]
        if not v.isdigit():
            raise ValueError("Phone number must contain digits only")
        if len(v) < 9 or len(v) > 13:
            raise ValueError("Enter a valid Zambian mobile number")
        valid_prefixes = ("097", "096", "095", "076", "077", "075", "078")
        if not any(v.startswith(p) for p in valid_prefixes):
            raise ValueError("Number must be Airtel (097/096/095) or MTN/Zamtel (076-078)")
        return v

    @validator("memo")
    def clean_memo(cls, v):
        return v.strip() or "ZamPay Payment"

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
# MERCHANT SHORT CODE LOOKUP
# GET /merchant/code/{short_code}
# e.g. GET /merchant/code/0042
# Africa's Talking USSD handler calls this to resolve merchant from customer input
# ─────────────────────────────────────────────────────────────

@router.get("/merchant/code/{short_code}")
async def get_merchant_by_short_code(short_code: str):
    """
    Resolve a 4-digit merchant short code to a merchant record.
    Short code = zero-padded merchant ID (e.g. merchant_id=42 → '0042').
    Used by the USSD flow so customers can enter a short code instead of a phone number.
    """
    short_code = short_code.strip().zfill(4)

    # Validate format
    if not short_code.isdigit() or len(short_code) != 4:
        raise HTTPException(400, "Short code must be 4 digits e.g. 0042")

    # Derive merchant_id from short code (reverse of _short_code_from_id)
    merchant_id = int(short_code)
    if merchant_id == 0:
        raise HTTPException(404, "Merchant not found")

    m = await get_merchant_by_id(merchant_id)
    if not m:
        raise HTTPException(404, f"No merchant found for code {short_code}")

    return {
        "short_code":       short_code,
        "merchant_id":      m["id"],
        "shop_name":        m["shop_name"],
        "location":         m.get("location"),
        "payout_mode":      m["payout_mode"],
        "lightning_address": m.get("lightning_address"),
    }


# ─────────────────────────────────────────────────────────────
# USSD — Africa's Talking Session Handler
# POST /ussd
#
# Register this URL in your Africa's Talking dashboard:
#   https://yourdomain.com/ussd
#
# AT posts these form fields on every USSD request:
#   sessionId   — unique per USSD dial session
#   serviceCode — your shortcode e.g. *384*xx#
#   phoneNumber — caller's number e.g. +260971234567
#   text        — all user inputs joined by * e.g. "1*0042*50"
#
# Response must be plain text:
#   "CON <message>"  — continue session (show menu, await input)
#   "END <message>"  — end session (final screen, no input)
#
# State machine:
#   text=""          → MAIN MENU
#   text="1"         → PAY a merchant (customer flow)
#   text="1*XXXX"    → customer entered merchant code → confirm merchant name
#   text="1*XXXX*A"  → customer entered amount → confirm screen
#   text="1*XXXX*A*1"→ customer confirmed → create invoice + end session
#   text="2"         → I AM A MERCHANT (merchant flow)
#   text="2*A"       → merchant entered amount → confirm screen
#   text="2*A*1"     → merchant confirmed → create invoice, await payment
# ─────────────────────────────────────────────────────────────

@router.post("/ussd", response_class=PlainTextResponse)
async def ussd_handler(
    sessionId:   str = Form(...),
    serviceCode: str = Form(...),
    phoneNumber: str = Form(...),
    text:        str = Form(default=""),
):
    """
    Africa's Talking USSD gateway handler.
    Returns CON (continue) or END (terminate) plain text responses.
    """
    # Split input chain — AT joins steps with *
    parts = [p.strip() for p in text.split("*")] if text.strip() else []

    logger.info(f"USSD | session={sessionId} | phone={phoneNumber} | text='{text}' | parts={parts}")

    # ── MAIN MENU ────────────────────────────────────────────
    if not parts or parts == [""]:
        return (
            "CON Welcome to ZamPOS ⚡\n"
            "Bitcoin Lightning Payments\n"
            "━━━━━━━━━━━━━━━━━\n"
            "1. Pay a Merchant\n"
            "2. I am a Merchant\n"
            "0. Exit"
        )

    # ── CUSTOMER FLOW: Pay a Merchant ────────────────────────
    if parts[0] == "1":

        # Step 1: Ask for merchant short code
        if len(parts) == 1:
            return (
                "CON Enter merchant code:\n"
                "(4-digit code e.g. 0042)\n"
                "Ask the merchant for their code"
            )

        # Step 2: Validate short code + confirm merchant name
        if len(parts) == 2:
            short_code = parts[1].zfill(4)
            merchant_id = int(short_code) if short_code.isdigit() else 0
            if merchant_id == 0:
                return "END ❌ Invalid merchant code.\nPlease try again."

            m = await get_merchant_by_id(merchant_id)
            if not m:
                return f"END ❌ No merchant found\nfor code {short_code}.\nPlease check and try again."

            return (
                f"CON Merchant found:\n"
                f"{m['shop_name']}\n"
                f"{m.get('location') or 'Zambia'}\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"Enter amount in ZMW (K):\n"
                f"e.g. 50"
            )

        # Step 3: Amount entered → show confirmation
        if len(parts) == 3:
            short_code  = parts[1].zfill(4)
            amount_text = parts[2].strip()

            try:
                amount_zmw = float(amount_text)
                if amount_zmw < MIN_ZMW:
                    return f"END ❌ Minimum amount is K{MIN_ZMW:.0f}"
            except ValueError:
                return "END ❌ Invalid amount.\nEnter numbers only e.g. 50"

            merchant_id = int(short_code) if short_code.isdigit() else 0
            m = await get_merchant_by_id(merchant_id)
            if not m:
                return "END ❌ Merchant not found.\nPlease try again."

            # Get live rate for sats preview
            try:
                _, sats_per_zmw = await fetch_live_rates(force_refresh=False)
                gross_sats, _, _ = calculate_spread(amount_zmw, float(sats_per_zmw))
                sats_line = f"≈ {gross_sats:,} sats ⚡\n"
            except Exception:
                sats_line = ""

            return (
                f"CON Confirm Payment:\n"
                f"To: {m['shop_name']}\n"
                f"Amount: K{amount_zmw:.2f}\n"
                f"{sats_line}"
                f"━━━━━━━━━━━━━━━━━\n"
                f"1. Confirm & Pay\n"
                f"2. Cancel"
            )

        # Step 4: Customer confirmed → create Lightning invoice
        if len(parts) == 4:
            choice = parts[3].strip()

            if choice == "2":
                return "END ❌ Payment cancelled."

            if choice != "1":
                return "END ❌ Invalid choice.\nPlease try again."

            short_code  = parts[1].zfill(4)
            amount_text = parts[2].strip()

            try:
                amount_zmw  = float(amount_text)
                merchant_id = int(short_code) if short_code.isdigit() else 0
            except ValueError:
                return "END ❌ Something went wrong.\nPlease try again."

            m = await get_merchant_by_id(merchant_id)
            if not m:
                return "END ❌ Merchant not found."

            # Create Lightning invoice
            try:
                zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=True)
                gross_sats, merchant_sats, operator_sats = calculate_spread(
                    amount_zmw, float(sats_per_zmw)
                )
                if gross_sats == 0:
                    return "END ❌ Amount too small to convert.\nTry a higher amount."

                invoice_address = (
                    m["lightning_address"] if m["payout_mode"] == "direct"
                    else OPERATOR_LIGHTNING_ADDRESS
                )
                bolt11       = await fetch_invoice_from_lightning_address(
                    invoice_address, gross_sats,
                    comment=f"ZamPOS USSD | {m['shop_name']}"
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
                    memo=f"USSD payment | {phoneNumber}",
                    payout_mode=m["payout_mode"],
                    rate_snapshot={
                        "zmw_per_btc":  float(zmw_per_btc),
                        "sats_per_zmw": float(sats_per_zmw),
                        "source":       "ussd",
                        "timestamp":    cache_meta.get("last_updated"),
                        "customer_phone": phoneNumber,
                    },
                )

                # Kick off payment polling + SMS in background
                asyncio.create_task(_poll_payment(
                    payment_hash=payment_hash,
                    merchant_id=merchant_id,
                    gross_sats=gross_sats,
                    payout_mode=m["payout_mode"],
                    merchant_phone=m["phone_number"],
                    shop_name=m["shop_name"],
                    amount_zmw=amount_zmw,
                    lightning_address=invoice_address,
                ))

                logger.info(
                    f"⚡ USSD invoice | merchant={merchant_id} | "
                    f"K{amount_zmw:.2f} | {gross_sats} sats | customer={phoneNumber}"
                )

                # Return invoice string — customer pays via any Lightning wallet
                # Truncated for USSD display (182 char limit per screen)
                short_bolt11 = bolt11[:60] + "..."
                return (
                    f"END ✅ Invoice created!\n"
                    f"Pay K{amount_zmw:.2f} to {m['shop_name']}\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"Open your Lightning wallet\n"
                    f"and paste this invoice:\n"
                    f"{short_bolt11}\n"
                    f"Or ask merchant to show QR"
                )

            except Exception as e:
                logger.error(f"❌ USSD invoice create failed: {e}", exc_info=True)
                return "END ❌ Payment service unavailable.\nTry again or use the ZamPOS app."

        return "END ❌ Invalid input.\nPlease dial again."

    # ── MERCHANT FLOW: I am a Merchant ──────────────────────
    elif parts[0] == "2":

        # Step 1: Ask for amount
        if len(parts) == 1:
            return (
                "CON Enter sale amount (ZMW):\n"
                "e.g. 150\n"
                "Customer will pay via Lightning"
            )

        # Step 2: Amount entered → look up merchant by phone, confirm
        if len(parts) == 2:
            amount_text = parts[1].strip()
            try:
                amount_zmw = float(amount_text)
                if amount_zmw < MIN_ZMW:
                    return f"END ❌ Minimum amount is K{MIN_ZMW:.0f}"
            except ValueError:
                return "END ❌ Invalid amount.\nEnter numbers only e.g. 150"

            # Look up merchant by the caller's phone number
            m = await _get_merchant_by_phone(phoneNumber)
            if not m:
                return (
                    "END ❌ Phone not registered.\n"
                    "Register at zampos.vercel.app\n"
                    "or ask your ZamPOS agent."
                )

            try:
                _, sats_per_zmw = await fetch_live_rates(force_refresh=False)
                gross_sats, _, _ = calculate_spread(amount_zmw, float(sats_per_zmw))
                sats_line = f"≈ {gross_sats:,} sats ⚡\n"
            except Exception:
                sats_line = ""

            return (
                f"CON Sale for {m['shop_name']}:\n"
                f"Amount: K{amount_zmw:.2f}\n"
                f"{sats_line}"
                f"━━━━━━━━━━━━━━━━━\n"
                f"1. Generate Invoice\n"
                f"2. Cancel"
            )

        # Step 3: Merchant confirmed → create invoice
        if len(parts) == 3:
            choice      = parts[2].strip()
            amount_text = parts[1].strip()

            if choice == "2":
                return "END ❌ Cancelled."

            if choice != "1":
                return "END ❌ Invalid choice."

            try:
                amount_zmw = float(amount_text)
            except ValueError:
                return "END ❌ Something went wrong.\nPlease try again."

            m = await _get_merchant_by_phone(phoneNumber)
            if not m:
                return "END ❌ Merchant not found."

            try:
                zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=True)
                gross_sats, merchant_sats, operator_sats = calculate_spread(
                    amount_zmw, float(sats_per_zmw)
                )
                if gross_sats == 0:
                    return "END ❌ Amount too small.\nTry a higher amount."

                invoice_address = (
                    m["lightning_address"] if m["payout_mode"] == "direct"
                    else OPERATOR_LIGHTNING_ADDRESS
                )
                bolt11       = await fetch_invoice_from_lightning_address(
                    invoice_address, gross_sats,
                    comment=f"ZamPOS USSD | {m['shop_name']}"
                )
                payment_hash = extract_payment_hash(bolt11)
                cache_meta   = get_cache_metadata()

                await save_transaction(
                    payment_hash=payment_hash,
                    merchant_id=m["id"],
                    amount_zmw=amount_zmw,
                    gross_sats=gross_sats,
                    merchant_sats=merchant_sats,
                    operator_sats=operator_sats,
                    memo=f"USSD merchant sale",
                    payout_mode=m["payout_mode"],
                    rate_snapshot={
                        "zmw_per_btc":  float(zmw_per_btc),
                        "sats_per_zmw": float(sats_per_zmw),
                        "source":       "ussd_merchant",
                        "timestamp":    cache_meta.get("last_updated"),
                    },
                )

                asyncio.create_task(_poll_payment(
                    payment_hash=payment_hash,
                    merchant_id=m["id"],
                    gross_sats=gross_sats,
                    payout_mode=m["payout_mode"],
                    merchant_phone=m["phone_number"],
                    shop_name=m["shop_name"],
                    amount_zmw=amount_zmw,
                    lightning_address=invoice_address,
                ))

                short_code = _short_code_from_id(m["id"])
                logger.info(
                    f"⚡ USSD merchant invoice | merchant={m['id']} | "
                    f"K{amount_zmw:.2f} | {gross_sats} sats"
                )

                return (
                    f"END ✅ Invoice ready!\n"
                    f"K{amount_zmw:.2f} | {gross_sats:,} sats\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"Show QR in ZamPOS app\n"
                    f"OR tell customer:\n"
                    f"Merchant code: {short_code}\n"
                    f"You'll get SMS when paid ⚡"
                )

            except Exception as e:
                logger.error(f"❌ USSD merchant invoice: {e}", exc_info=True)
                return "END ❌ Service unavailable.\nTry again shortly."

        return "END ❌ Invalid input."

    # ── EXIT ─────────────────────────────────────────────────
    elif parts[0] == "0":
        return "END Thank you for using ZamPOS ⚡\n🇿🇲 Bitcoin Lightning Payments"

    return (
        "END ❌ Invalid option.\n"
        "Please dial again and\n"
        "choose 1 or 2."
    )


async def _get_merchant_by_phone(phone: str) -> Optional[dict]:
    """
    Look up a merchant by their registered phone number.
    Normalizes Zambian number formats before matching.
    """
    # Normalize to local format (0971234567) for DB match
    p = phone.strip().replace(" ", "").replace("-", "")
    if p.startswith("+260"):
        p = "0" + p[4:]
    elif p.startswith("260") and len(p) == 12:
        p = "0" + p[3:]

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Try both normalized and original formats
            cur = await db.execute(
                "SELECT * FROM merchants WHERE phone_number = ? OR phone_number = ? LIMIT 1",
                (p, phone),
            )
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ _get_merchant_by_phone: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# RECOVERY CODE ENDPOINTS (FREE - No SMS Costs)
# ─────────────────────────────────────────────────────────────

@router.post("/merchant/recover")
async def recover_merchant(req: RecoverRequest):
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
        
        last_updated = cache_meta.get("last_updated")
        if last_updated:
            if hasattr(last_updated, 'isoformat'):
                last_updated = last_updated.isoformat()
            elif isinstance(last_updated, str):
                pass
            else:
                last_updated = None
        else:
            last_updated = None
            
        return {
            "zmw_per_btc":           real_rate,
            "displayed_zmw_per_btc": apply_spread_to_rate(real_sats_sp),
            "sats_per_zmw":          real_sats_sp,
            "last_updated":          last_updated,
            "source":                cache_meta.get("source", "coingecko+exchangerate"),
            "cache_valid":           cache_meta.get("is_valid", True),
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

        # Attach short code to response (derived from assigned merchant ID)
        short_code = _short_code_from_id(m["id"])
        
        return {
            **m,
            **wallet_info,
            "short_code": short_code,
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
    return {**m, "short_code": _short_code_from_id(m["id"])}


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
        "short_code":  _short_code_from_id(merchant_id),
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
            merchants = [
                {**dict(r), "short_code": _short_code_from_id(r["id"])}
                for r in rows
            ]
            return {"merchants": merchants, "total": len(merchants)}
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
        "short_code":     _short_code_from_id(merchant_id),
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


# ═════════════════════════════════════════════════════════════
# ZAMPAY — Mobile Money → Sats (BitZed Bridge)
# ═════════════════════════════════════════════════════════════
#
# STATUS: Production-ready stub.
#   BITZED_ENABLED=false  → runs in stub mode (logs, saves to DB, returns success)
#   BITZED_ENABLED=true   → un-comment the httpx block inside _call_bitzed()
#
# Endpoints:
#   POST /zampay/charge    ← called by the frontend ZamPay button
#   POST /zampay/webhook   ← BitZed posts here when customer approves/declines
#
# When you have BitZed credentials:
#   1. Add to .env:  BITZED_ENABLED=true  BITZED_API_KEY=xxx
#   2. Un-comment the httpx block in _call_bitzed() below
#   3. Give BitZed this webhook URL: https://yourdomain.com/zampay/webhook
# ─────────────────────────────────────────────────────────────

async def _call_bitzed(
    customer_phone: str,
    amount_zmw: float,
    merchant_lightning_address: str,
    memo: str,
    reference: str,
) -> dict:
    """
    ── BitZed integration point ──────────────────────────────────────────────
    When BitZed gives you their API, un-comment the httpx block below and
    delete the stub return. No other code needs to change.

    Expected return shape:
    {
        "success":    bool,
        "bitzed_ref": str,    # BitZed's own transaction ID
        "status":     str,    # "pending" | "approved" | "failed"
        "error":      str | None,
    }
    ─────────────────────────────────────────────────────────────────────────
    """
    if not BITZED_ENABLED:
        # ── STUB: logs intent, returns "pending" so frontend shows success ──
        logger.info(
            f"[ZamPay STUB] Would charge {customer_phone} K{amount_zmw:.2f} "
            f"→ {merchant_lightning_address} | ref={reference}"
        )
        return {
            "success":    True,
            "bitzed_ref": f"STUB-{reference}",
            "status":     "pending",
            "error":      None,
        }

    # ── REAL BitZed call — un-comment when ready ──────────────────────────
    # import httpx
    # try:
    #     async with httpx.AsyncClient() as client:
    #         r = await client.post(
    #             f"{BITZED_API_URL}/mobile-money/charge",
    #             headers={"Authorization": f"Bearer {BITZED_API_KEY}"},
    #             json={
    #                 "phone":             customer_phone,
    #                 "amount_zmw":        amount_zmw,
    #                 "lightning_address": merchant_lightning_address,
    #                 "reference":         reference,
    #                 "memo":              memo,
    #             },
    #             timeout=30,
    #         )
    #         data = r.json()
    #         return {
    #             "success":    r.status_code == 200,
    #             "bitzed_ref": data.get("id", reference),
    #             "status":     data.get("status", "pending"),
    #             "error":      data.get("error"),
    #         }
    # except Exception as e:
    #     logger.error(f"BitZed HTTP error: {e}")
    #     return {"success": False, "bitzed_ref": reference, "status": "failed", "error": str(e)}

    raise HTTPException(503, "BitZed not yet enabled — set BITZED_ENABLED=true in .env")


@router.post("/zampay/charge")
async def zampay_charge(req: ZamPayChargeRequest, background_tasks: BackgroundTasks):
    """
    Initiate a ZamPay (Airtel/MTN → sats) charge.
    Frontend ZamPay button posts here.
    """
    merchant = await get_merchant_by_id(req.merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")

    lightning_address = merchant.get("lightning_address") or OPERATOR_LIGHTNING_ADDRESS

    try:
        zmw_per_btc, sats_per_zmw = await fetch_live_rates(force_refresh=False)
        real_sats_per_zmw = float(sats_per_zmw)
        gross_sats, merchant_sats, operator_sats = calculate_spread(
            req.amount_zmw, real_sats_per_zmw
        )
        if gross_sats == 0:
            raise ValueError("Rate produced 0 sats — amount too small")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ZamPay rate error: {e}")
        raise HTTPException(502, "Could not fetch exchange rate. Try again.")

    reference = _make_zampay_reference()
    try:
        bitzed_result = await _call_bitzed(
            customer_phone=req.customer_phone,
            amount_zmw=req.amount_zmw,
            merchant_lightning_address=lightning_address,
            memo=req.memo,
            reference=reference,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"BitZed call failed: {e}")
        raise HTTPException(502, "Mobile money service unavailable. Try again.")

    if not bitzed_result["success"]:
        raise HTTPException(
            400,
            f"ZamPay charge failed: {bitzed_result.get('error', 'Unknown error')}"
        )

    cache_meta   = get_cache_metadata()
    payment_hash = bitzed_result["bitzed_ref"]

    await save_transaction(
        payment_hash=payment_hash,
        merchant_id=req.merchant_id,
        amount_zmw=req.amount_zmw,
        gross_sats=gross_sats,
        merchant_sats=merchant_sats,
        operator_sats=operator_sats,
        memo=req.memo,
        payout_mode="zampay",
        rate_snapshot={
            "zmw_per_btc":    float(zmw_per_btc),
            "sats_per_zmw":   real_sats_per_zmw,
            "customer_phone": req.customer_phone,
            "reference":      reference,
            "bitzed_ref":     payment_hash,
            "timestamp":      cache_meta.get("last_updated"),
        },
    )

    logger.info(
        f"📱 ZamPay initiated | merchant={req.merchant_id} | "
        f"K{req.amount_zmw:.2f} → {req.customer_phone} | ref={reference} | "
        f"{gross_sats} sats → {lightning_address}"
    )

    return {
        "success":           True,
        "reference":         reference,
        "bitzed_ref":        payment_hash,
        "status":            bitzed_result["status"],
        "amount_zmw":        req.amount_zmw,
        "gross_sats":        gross_sats,
        "merchant_sats":     merchant_sats,
        "operator_sats":     operator_sats,
        "customer_phone":    req.customer_phone,
        "lightning_address": lightning_address,
        "memo":              req.memo,
        "message":           f"✅ Mobile money prompt sent to {req.customer_phone}. Waiting for customer approval.",
    }


@router.post("/zampay/webhook")
async def zampay_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    BitZed calls this when a customer approves or declines their mobile money prompt.

    Register this URL in your BitZed dashboard:
        https://yourdomain.com/zampay/webhook

    Expected payload:
    {
        "reference":  "ZP-XXXXXX",
        "status":     "approved" | "declined" | "failed",
        "amount_zmw": 50.00,
        "phone":      "0971234567"
    }
    """
    try:
        body      = await request.json()
        reference = body.get("reference") or body.get("bitzed_ref")
        status    = body.get("status", "").lower()

        if not reference:
            logger.warning("ZamPay webhook: missing reference")
            return {"status": "ignored", "reason": "no reference"}

        if status not in ("approved", "success", "declined", "failed"):
            logger.info(f"ZamPay webhook: unhandled status '{status}' ref={reference}")
            return {"status": "ignored", "reason": f"unhandled status: {status}"}

        if status in ("approved", "success"):
            paid = await mark_paid(reference)
            if paid:
                tx = await get_transaction_by_hash(reference)
                if tx:
                    m = await get_merchant_by_id(tx["merchant_id"])
                    if m:
                        background_tasks.add_task(
                            _send_zampay_sms,
                            payment_hash=reference,
                            merchant_phone=m["phone_number"],
                            shop_name=m["shop_name"],
                            amount_zmw=tx["amount_zmw"],
                            gross_sats=tx["gross_sats"],
                            lightning_address=m.get("lightning_address") or OPERATOR_LIGHTNING_ADDRESS,
                            customer_phone=body.get("phone", ""),
                        )
            logger.info(f"✅ ZamPay approved | ref={reference}")

        else:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE transactions SET status='expired' "
                    "WHERE payment_hash=? AND status='pending'",
                    (reference,),
                )
                await db.commit()
            logger.info(f"❌ ZamPay {status} | ref={reference}")

        return {"status": "received", "reference": reference}

    except Exception as e:
        logger.error(f"❌ ZamPay webhook: {e}", exc_info=True)
        return {"status": "error"}


async def _send_zampay_sms(
    payment_hash: str,
    merchant_phone: str,
    shop_name: str,
    amount_zmw: float,
    gross_sats: int,
    lightning_address: str,
    customer_phone: str,
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
        logger.info(f"📱 ZamPay SMS sent to {merchant_phone} (customer: {customer_phone})")
    else:
        logger.warning(f"⚠️ ZamPay SMS failed to {merchant_phone}: {r['error']}")