from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.lnbits import create_invoice, check_payment
from services.coingecko import get_zmw_per_btc, zmw_to_sats
from database import save_transaction, mark_paid
import os

router = APIRouter()

MAX_SATS = 100_000  # demo.lnbits.com limit — raise for self-hosted instances


class CreateInvoiceRequest(BaseModel):
    amount_zmw: float
    memo: str = "ZamPOS Payment"


@router.post("/create")
async def new_invoice(body: CreateInvoiceRequest):
    if body.amount_zmw <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    try:
        rate = await get_zmw_per_btc()
        sats = zmw_to_sats(body.amount_zmw, rate)

        if sats > MAX_SATS:
            zmw_max = round((MAX_SATS / 100_000_000) * rate, 2)
            raise HTTPException(
                status_code=400,
                detail=f"Amount too high for this LNbits instance. Maximum is {MAX_SATS:,} sats (≈ K{zmw_max:,.2f}). Split into smaller payments."
            )

        webhook_url = os.getenv("WEBHOOK_URL")
        invoice = await create_invoice(sats, body.memo, webhook_url)

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Invoice creation failed: {str(e)}")


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
        raise HTTPException(status_code=502, detail=f"Status check failed: {str(e)}")
