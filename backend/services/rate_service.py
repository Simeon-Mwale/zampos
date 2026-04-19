# backend/services/rate_service.py
import httpx
import os
import time
import logging
from decimal import Decimal
from typing import Tuple

logger = logging.getLogger(__name__)

FX_API_KEY      = os.getenv("FX_API_KEY", "")
FX_API_BASE_URL = os.getenv("FX_API_BASE_URL", "https://v6.exchangerate-api.com/v6")
CACHE_TTL       = int(os.getenv("RATE_CACHE_TTL_SECONDS", "45"))

_cache: dict = {
    "zmw_per_btc":  None,
    "sats_per_zmw": None,
    "timestamp":    0,
    "source":       "none",
}


def get_cache_metadata() -> dict:
    age      = time.time() - _cache["timestamp"]
    is_valid = _cache["zmw_per_btc"] is not None and age < CACHE_TTL
    return {
        "last_updated": int(_cache["timestamp"]) if _cache["timestamp"] else None,
        "source":       _cache["source"],
        "is_valid":     is_valid,
        "age_seconds":  int(age),
    }


async def fetch_live_rates(force_refresh: bool = False) -> Tuple[Decimal, Decimal]:
    """
    ZMW/USD via ExchangeRate-API → BTC/USD via CoinGecko → ZMW/BTC
    Returns (zmw_per_btc, sats_per_zmw).
    """
    now = time.time()
    if (
        not force_refresh
        and _cache["zmw_per_btc"] is not None
        and (now - _cache["timestamp"]) < CACHE_TTL
    ):
        return _cache["zmw_per_btc"], _cache["sats_per_zmw"]

    try:
        zmw_per_usd = await _fetch_zmw_per_usd()
        btc_usd     = await _fetch_btc_usd()

        zmw_per_btc  = Decimal(str(zmw_per_usd)) * Decimal(str(btc_usd))
        sats_per_zmw = Decimal("100000000") / zmw_per_btc

        _cache.update({
            "zmw_per_btc":  zmw_per_btc,
            "sats_per_zmw": sats_per_zmw,
            "timestamp":    now,
            "source":       "live",
        })
        logger.info(f"💱 Rates refreshed | 1 BTC = {float(zmw_per_btc):,.0f} ZMW")
        return zmw_per_btc, sats_per_zmw

    except Exception as e:
        logger.warning(f"⚠️ Rate fetch failed: {e} — using fallback")
        if _cache["zmw_per_btc"] is not None:
            _cache["source"] = "cached"
            return _cache["zmw_per_btc"], _cache["sats_per_zmw"]
        fallback = Decimal("1500000")
        fallback_sats = Decimal("100000000") / fallback
        _cache.update({
            "zmw_per_btc":  fallback,
            "sats_per_zmw": fallback_sats,
            "timestamp":    now,
            "source":       "fallback",
        })
        return fallback, fallback_sats


async def _fetch_zmw_per_usd() -> float:
    if not FX_API_KEY:
        raise ValueError("FX_API_KEY not configured")
    url = f"{FX_API_BASE_URL}/{FX_API_KEY}/latest/USD"
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    zmw = data["conversion_rates"]["ZMW"]
    if not zmw or zmw <= 0:
        raise ValueError(f"Bad ZMW rate: {zmw}")
    return float(zmw)


async def _fetch_btc_usd() -> float:
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
        )
        resp.raise_for_status()
        data = resp.json()
    price = data["bitcoin"]["usd"]
    if not price or price <= 0:
        raise ValueError(f"Bad BTC/USD price: {price}")
    return float(price)


def zmw_to_sats(zmw: float, zmw_per_btc: Decimal) -> int:
    if zmw <= 0 or zmw_per_btc <= 0:
        return 0
    return max(1, int((Decimal(str(zmw)) / zmw_per_btc * Decimal("100000000")).to_integral_value()))


def format_btc_display(zmw: float, zmw_per_btc: Decimal) -> str:
    if zmw <= 0 or zmw_per_btc <= 0:
        return "0.00000000"
    return f"{float(Decimal(str(zmw)) / zmw_per_btc):.8f}"