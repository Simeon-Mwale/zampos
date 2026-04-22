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
# OFFLINE SAFE FALLBACK RATE
# Used only when ALL live sources fail
# ─────────────────────────────────────────────
FALLBACK_ZMW_PER_BTC = Decimal("1900000")

# FX fallback used when all FX APIs are unreachable
FALLBACK_ZMW_PER_USD = Decimal("27.8")


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
    # SOURCE 1: CoinGecko BTC/USD (primary)
    # ─────────────────────────────────────────
    try:
        btc_usd = await _fetch_btc_usd()

        # ─────────────────────────────────────
        # SOURCE 2: Live ZMW/USD FX rate
        # Tries 3 providers — falls back to
        # FALLBACK_ZMW_PER_USD if all fail
        # ─────────────────────────────────────
        try:
            zmw_usd, fx_source = await _fetch_zmw_usd()
            source = f"coingecko+{fx_source}"
            logger.debug(f"📈 Live FX rate: 1 USD = {zmw_usd} ZMW (via {fx_source})")
        except Exception as fx_err:
            logger.warning(f"⚠️  All FX sources failed, using hardcoded fallback: {fx_err}")
            zmw_usd = float(FALLBACK_ZMW_PER_USD)
            source = "coingecko+fx-fallback"

        zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))

    except Exception as e:
        logger.warning(f"❌ BTC price fetch failed: {e}")

    # ─────────────────────────────────────────
    # FINAL FALLBACK (all sources failed)
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        logger.warning("🚨 All rate sources failed — using static fallback rate")
        zmw_per_btc = FALLBACK_ZMW_PER_BTC
        source = "static-fallback"

    sats_per_zmw = Decimal("100000000") / zmw_per_btc

    _cache.update({
        "zmw_per_btc": zmw_per_btc,
        "sats_per_zmw": sats_per_zmw,
        "timestamp": now,
        "source": source,
    })

    logger.info(f"💱 Rate updated | {zmw_per_btc:.2f} ZMW/BTC | {source}")

    return zmw_per_btc, sats_per_zmw


# ─────────────────────────────────────────────
# FETCH BTC/USD — CoinGecko (no key needed)
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


# ─────────────────────────────────────────────
# FETCH ZMW/USD — 3 providers, first one wins
# Returns (rate_float, source_name)
# ─────────────────────────────────────────────
async def _fetch_zmw_usd() -> Tuple[float, str]:
    providers = [
        (
            "exchangerate-api",
            "https://api.exchangerate-api.com/v4/latest/USD",
            lambda d: float(d["rates"]["ZMW"]),
        ),
        (
            "open-er-api",
            "https://open.er-api.com/v6/latest/USD",
            lambda d: float(d["rates"]["ZMW"]),
        ),
        (
            "fxratesapi",
            "https://api.fxratesapi.com/latest?base=USD",
            lambda d: float(d["rates"]["ZMW"]),
        ),
    ]

    async with httpx.AsyncClient(timeout=6) as client:
        for name, url, extractor in providers:
            try:
                r = await client.get(url)
                r.raise_for_status()
                zmw = extractor(r.json())
                if zmw and zmw > 10:  # sanity check — ZMW never < 20 per USD
                    return zmw, name
                else:
                    logger.warning(f"⚠️  Suspicious ZMW rate from {name}: {zmw} — skipping")
            except Exception as e:
                logger.warning(f"⚠️  FX provider failed [{name}]: {e}")

    raise ValueError("All ZMW/USD FX providers failed")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def zmw_to_sats(zmw: float, zmw_per_btc: Decimal) -> int:
    if zmw <= 0:
        return 0
    return int((Decimal(str(zmw)) / zmw_per_btc) * Decimal("100000000"))


def format_btc_display(zmw: float, zmw_per_btc: Decimal) -> str:
    if zmw <= 0:
        return "0.00000000"
    return f"{float(Decimal(str(zmw)) / zmw_per_btc):.8f}"