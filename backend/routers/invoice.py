from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.lnbits import create_invoice, check_payment
from services.coingecko import get_zmw_per_btc, zmw_to_sats
from database import save_transaction, mark_paid, get_merchant_by_id
import os

router = APIRouter()

MAX_SATS = 100_000  # adjust if needed


# ------------------------
# REQUEST MODEL (UPDATED)
# ------------------------

class CreateInvoiceRequest(BaseModel):
    merchant_id: int = Field(..., gt=0, description="Merchant ID")  # ✅ Now in body
    amount_zmw: float = Field(..., gt=0, le=1_000_000, description="Amount in ZMW")
    memo: str = Field(default="ZamPOS Payment", max_length=200)
    
    class Config:
        extra = "forbid"  # Reject unexpected fields for security


# ------------------------
# CREATE INVOICE (UPDATED)
# ------------------------

@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest):
    """
    Create invoice for a specific merchant.
    merchant_id is now in request body (not query param).
    """

    if body.amount_zmw <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    try:
        # 🔥 Get merchant from DB
        merchant = get_merchant_by_id(body.merchant_id)

        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")

        merchant_invoice_key = merchant["invoice_key"]

        # 💱 Convert ZMW → sats
        rate = await get_zmw_per_btc()
        sats = zmw_to_sats(body.amount_zmw, rate)

        if sats > MAX_SATS:
            zmw_max = round((MAX_SATS / 100_000_000) * rate, 2)
            raise HTTPException(
                status_code=400,
                detail=f"Amount too high. Max is {MAX_SATS:,} sats (≈ K{zmw_max:,.2f})"
            )

        webhook_url = os.getenv("WEBHOOK_URL")

        # 🔥 KEY: use merchant wallet
        invoice = await create_invoice(
            sats,
            body.memo,
            wallet_key=merchant_invoice_key,
            webhook_url=webhook_url
        )

        # 💾 Save transaction with merchant
        save_transaction(
            payment_hash=invoice["payment_hash"],
            amount_zmw=body.amount_zmw,
            amount_sats=sats,
            memo=body.memo,
            merchant_id=body.merchant_id
        )

        return {
            "payment_hash": invoice["payment_hash"],
            "payment_request": invoice["payment_request"],
            "amount_zmw": body.amount_zmw,
            "amount_sats": sats,
            "rate_zmw_per_btc": rate,
            "memo": body.memo,
            "merchant_id": body.merchant_id,  # Echo back for frontend confirmation
        }

    except HTTPException:
        raise
    except Exception as e:
        # Log full error server-side, return sanitized message to client
        print(f"❌ Invoice creation error: {e}")
        raise HTTPException(status_code=502, detail="Invoice creation failed. Please try again.")


# ------------------------
# CHECK STATUS (unchanged)
# ------------------------

@router.get("/status/{payment_hash}")
async def invoice_status(payment_hash: str):
    try:
        result = await check_payment(payment_hash)

        if result["paid"]:
            mark_paid(payment_hash)

        return {
            "payment_hash": payment_hash,
            "paid": result["paid"],
        }

    except Exception as e:
        print(f"❌ Status check error: {e}")
        raise HTTPException(status_code=502, detail="Status check failed")