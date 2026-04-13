from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.sweep import get_wallet_balance, sweep_to_lightning_address

router = APIRouter()


@router.get("/balance")
async def wallet_balance():
    try:
        msats = await get_wallet_balance()
        sats = msats // 1000
        return {"balance_sats": sats, "balance_msats": msats}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch balance: {str(e)}")


class SweepRequest(BaseModel):
    lightning_address: str
    amount_sats: int | None = None


@router.post("/send")
async def sweep(body: SweepRequest):
    try:
        msats = await get_wallet_balance()
        available_sats = msats // 1000

        if available_sats <= 0:
            raise HTTPException(status_code=400, detail="No sats available to sweep")

        # Leave just 1 sat for routing fees
        amount = body.amount_sats if body.amount_sats else max(available_sats - 1, 1)

        if amount > available_sats:
            raise HTTPException(
                status_code=400,
                detail=f"Requested {amount} sats but only {available_sats} available"
            )

        result = await sweep_to_lightning_address(body.lightning_address, amount)
        return result

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sweep failed: {str(e)}")
