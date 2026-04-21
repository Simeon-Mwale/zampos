# backend/services/rate_service.py
import httpx
import os
import time
import logging
from decimal import Decimal
from typing import Tuple

logger = logging.getLogger(__name__)

CACHE_TTL = int(os.getenv("RATE_CACHE_TTL_SECONDS", "45"))

_cache = {
    "zmw_per_btc": None,
    "sats_per_zmw": None,
    "timestamp": 0,
    "source": "none",
}

# ─────────────────────────────────────────────
# OFFLINE SAFE FALLBACK RATE (IMPORTANT)
# ─────────────────────────────────────────────
FALLBACK_ZMW_PER_BTC = Decimal("1500000")


def get_cache_metadata() -> dict:
    age = time.time() - _cache["timestamp"]
    return {
        "last_updated": int(_cache["timestamp"]) if _cache["timestamp"] else None,
        "source": _cache["source"],
        "is_valid": _cache["zmw_per_btc"] is not None and age < CACHE_TTL,
        "age_seconds": int(age),
    }


async def fetch_live_rates(force_refresh: bool = False) -> Tuple[Decimal, Decimal]:
    now = time.time()

    # ── Cache hit ─────────────────────────────
    if (
        not force_refresh
        and _cache["zmw_per_btc"]
        and (now - _cache["timestamp"]) < CACHE_TTL
    ):
        return _cache["zmw_per_btc"], _cache["sats_per_zmw"]

    zmw_per_btc = None
    source = "fallback"

    # ─────────────────────────────────────────
    # SOURCE 1: CoinGecko BTC price (stable)
    # ─────────────────────────────────────────
    try:
        btc_usd = await _fetch_btc_usd()

        # ZMW/USD fallback (hardcoded stable approximation)
        zmw_usd = 26.5  # Zambia FX approximation (stable baseline)

        zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))
        source = "coingecko+fx-fallback"

    except Exception as e:
        logger.warning(f"BTC source failed: {e}")

    # ─────────────────────────────────────────
    # FINAL FALLBACK
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        zmw_per_btc = FALLBACK_ZMW_PER_BTC
        source = "static-fallback"

    sats_per_zmw = Decimal("100000000") / zmw_per_btc

    _cache.update({
        "zmw_per_btc": zmw_per_btc,
        "sats_per_zmw": sats_per_zmw,
        "timestamp": now,
        "source": source,
    })

    logger.info(f"💱 Rate updated | {zmw_per_btc} ZMW/BTC | {source}")

    return zmw_per_btc, sats_per_zmw


# ─────────────────────────────────────────────
# BTC PRICE ONLY (reliable source)
# ─────────────────────────────────────────────
async def _fetch_btc_usd() -> float:
    async with httpx.AsyncClient(timeout=6) as client:
        r = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
        )
        r.raise_for_status()
        data = r.json()
    return float(data["bitcoin"]["usd"])


def zmw_to_sats(zmw: float, zmw_per_btc: Decimal) -> int:
    if zmw <= 0:
        return 0
    return int((Decimal(str(zmw)) / zmw_per_btc) * Decimal("100000000"))


def format_btc_display(zmw: float, zmw_per_btc: Decimal) -> str:
    if zmw <= 0:
        return "0.00000000"
    return f"{float(Decimal(str(zmw)) / zmw_per_btc):.8f}"