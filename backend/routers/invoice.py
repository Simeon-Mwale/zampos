from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.lnbits import create_invoice, check_payment
from services.coingecko import get_zmw_per_btc, zmw_to_sats
from database import save_transaction
import os

router = APIRouter()


class CreateInvoiceRequest(BaseModel):
    amount_zmw: float
    memo: str = "ZamPOS Payment"


@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest):
    """Create a Lightning invoice for a ZMW amount."""
    if body.amount_zmw <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    try:
        rate = await get_zmw_per_btc()
        sats = zmw_to_sats(body.amount_zmw, rate)

        webhook_url = os.getenv("WEBHOOK_URL")
        invoice = await create_invoice(sats, body.memo, webhook_url)

        # Save to DB as pending
        save_transaction(
            payment_hash=invoice["payment_hash"],
            amount_zmw=body.amount_zmw,
            amount_sats=sats,
            memo=body.memo,
        )

        return {
            "payment_hash": invoice["payment_hash"],
            "payment_request": invoice["payment_request"],
            "amount_zmw": body.amount_zmw,
            "amount_sats": sats,
            "rate_zmw_per_btc": rate,
            "memo": body.memo,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Invoice creation failed: {str(e)}")


@router.get("/status/{payment_hash}")
async def invoice_status(payment_hash: str):
    """Poll payment status for a given invoice."""
    from database import mark_paid
    try:
        result = await check_payment(payment_hash)
        if result["paid"]:
            mark_paid(payment_hash)
        return {
            "payment_hash": payment_hash,
            "paid": result["paid"],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Status check failed: {str(e)}")
