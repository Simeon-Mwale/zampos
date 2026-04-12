from fastapi import APIRouter, HTTPException
from services.coingecko import get_zmw_per_btc, zmw_to_sats

router = APIRouter()


@router.get("/rate")
async def get_rate():
    """Get current ZMW/BTC exchange rate."""
    try:
        rate = await get_zmw_per_btc()
        return {"zmw_per_btc": rate, "sats_per_zmw": round(100_000_000 / rate, 2)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Price feed unavailable: {str(e)}")


@router.get("/convert")
async def convert(zmw: float):
    """Convert a ZMW amount to satoshis."""
    if zmw <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
    try:
        rate = await get_zmw_per_btc()
        sats = zmw_to_sats(zmw, rate)
        return {
            "zmw": zmw,
            "sats": sats,
            "btc": round(sats / 100_000_000, 8),
            "rate_zmw_per_btc": rate,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
