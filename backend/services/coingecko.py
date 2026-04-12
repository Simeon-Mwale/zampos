import httpx
import os
from datetime import datetime, timedelta

COINGECKO_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")

# Simple in-memory cache to avoid hammering CoinGecko
_cache: dict = {"rate": None, "fetched_at": None}
CACHE_TTL_SECONDS = 60


async def get_zmw_per_btc() -> float:
    """Fetch ZMW/BTC rate from CoinGecko, with 60s cache."""
    now = datetime.utcnow()

    if _cache["rate"] and _cache["fetched_at"]:
        age = (now - _cache["fetched_at"]).total_seconds()
        if age < CACHE_TTL_SECONDS:
            return _cache["rate"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{COINGECKO_URL}/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "zmw"},
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data["bitcoin"]["zmw"]

    _cache["rate"] = rate
    _cache["fetched_at"] = now
    return rate


def zmw_to_sats(zmw_amount: float, zmw_per_btc: float) -> int:
    """Convert a ZMW amount to satoshis."""
    btc_amount = zmw_amount / zmw_per_btc
    sats = int(btc_amount * 100_000_000)
    return max(sats, 1)  # Minimum 1 sat
