# backend/services/rate_service.py
import httpx
import os
import time
import logging
import asyncio
from decimal import Decimal
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
CACHE_TTL = int(os.getenv("RATE_CACHE_TTL_SECONDS", "90"))  # Increased from 45 to 90s
REQUEST_DELAY = float(os.getenv("RATE_REQUEST_DELAY_SECONDS", "2.0"))  # Throttle requests

_cache = {
    "zmw_per_btc": None,
    "sats_per_zmw": None,
    "timestamp": 0,
    "source": "none",
}

_last_request_time = 0

# ─────────────────────────────────────────────
# OFFLINE SAFE FALLBACK RATE (UPDATED)
# Used only when ALL live sources fail
# Changed from 1,900,000 to realistic market rate
# ─────────────────────────────────────────────
FALLBACK_ZMW_PER_BTC = Decimal("1350000")  # UPDATED: Realistic market rate for April 2026

# FX fallback used when all FX APIs are unreachable  
FALLBACK_ZMW_PER_USD = Decimal("27.5")  # Updated to current rate


def _throttle_requests():
    """Prevent API rate limiting by spacing out requests"""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def get_cache_metadata() -> dict:
    age = time.time() - _cache["timestamp"]
    return {
        "last_updated": int(_cache["timestamp"]) if _cache["timestamp"] else None,
        "source": _cache["source"],
        "is_valid": _cache["zmw_per_btc"] is not None and age < CACHE_TTL,
        "age_seconds": int(age),
    }


async def fetch_live_rates(force_refresh: bool = False) -> Tuple[Decimal, Decimal]:
    """Fetch current BTC/ZMW rate with improved caching and fallback"""
    now = time.time()

    # ── Cache hit (longer TTL to avoid rate limits) ──
    if (
        not force_refresh
        and _cache["zmw_per_btc"]
        and (now - _cache["timestamp"]) < CACHE_TTL
    ):
        logger.debug(f"📦 Using cached rate (age: {int(now - _cache['timestamp'])}s)")
        return _cache["zmw_per_btc"], _cache["sats_per_zmw"]

    zmw_per_btc = None
    source = "fallback"
    errors = []

    # ─────────────────────────────────────────
    # SOURCE 1: CoinGecko BTC/USD with rate limit protection
    # ─────────────────────────────────────────
    try:
        _throttle_requests()  # Prevent hammering APIs
        btc_usd = await _fetch_btc_usd_with_retry()

        # ─────────────────────────────────────
        # SOURCE 2: Live ZMW/USD FX rate
        # ─────────────────────────────────────
        try:
            zmw_usd, fx_source = await _fetch_zmw_usd_with_retry()
            source = f"coingecko+{fx_source}"
            logger.debug(f"📈 Live FX rate: 1 USD = {zmw_usd} ZMW (via {fx_source})")
        except Exception as fx_err:
            logger.warning(f"⚠️  All FX sources failed, using fallback: {fx_err}")
            zmw_usd = float(FALLBACK_ZMW_PER_USD)
            source = "coingecko+fx-fallback"
            errors.append(f"FX: {fx_err}")

        zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))

    except Exception as e:
        logger.warning(f"❌ BTC price fetch failed: {e}")
        errors.append(f"BTC: {e}")

    # ─────────────────────────────────────────
    # SOURCE 3: Try alternative crypto API if CoinGecko fails
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        try:
            _throttle_requests()
            btc_usd = await _fetch_btc_usd_alternative()
            zmw_usd = float(FALLBACK_ZMW_PER_USD)
            zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))
            source = "alternative-api+fx-fallback"
            logger.info(f"✅ Using alternative BTC API: {btc_usd} USD/BTC")
        except Exception as e:
            logger.warning(f"❌ Alternative BTC API also failed: {e}")
            errors.append(f"Alt-BTC: {e}")

    # ─────────────────────────────────────────
    # FINAL FALLBACK (all sources failed)
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        logger.error(f"🚨 All rate sources failed ({', '.join(errors)}) — using updated static fallback")
        zmw_per_btc = FALLBACK_ZMW_PER_BTC
        source = "static-fallback"

    sats_per_zmw = Decimal("100000000") / zmw_per_btc

    _cache.update({
        "zmw_per_btc": zmw_per_btc,
        "sats_per_zmw": sats_per_zmw,
        "timestamp": now,
        "source": source,
    })

    logger.info(f"💱 Rate updated | {zmw_per_btc:,.2f} ZMW/BTC | {source}")

    return zmw_per_btc, sats_per_zmw


# ─────────────────────────────────────────────
# FETCH BTC/USD — CoinGecko with retry
# ─────────────────────────────────────────────
async def _fetch_btc_usd_with_retry(retries: int = 2) -> float:
    """Fetch BTC/USD from CoinGecko with retry logic"""
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                
                if r.status_code == 429:
                    wait_time = (attempt + 1) * 3
                    logger.warning(f"⚠️  Rate limited (429), waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                    
                r.raise_for_status()
                data = r.json()
                price = float(data["bitcoin"]["usd"])
                
                if price > 0:
                    return price
                    
        except Exception as e:
            if attempt == retries:
                raise
            logger.debug(f"Retry {attempt + 1}/{retries} after error: {e}")
            await asyncio.sleep(2)
    
    raise ValueError("Failed to fetch BTC/USD after retries")


# ─────────────────────────────────────────────
# FETCH BTC/USD — Alternative API (Binance)
# ─────────────────────────────────────────────
async def _fetch_btc_usd_alternative() -> float:
    """Fallback BTC/USD from Binance API"""
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BTCUSDT"})
        r.raise_for_status()
        data = r.json()
        return float(data["price"])


# ─────────────────────────────────────────────
# FETCH ZMW/USD — with retry logic
# ─────────────────────────────────────────────
async def _fetch_zmw_usd_with_retry() -> Tuple[float, str]:
    """Fetch ZMW/USD with provider fallback and retry"""
    providers = [
        (
            "bankofzambia",
            "https://www.boz.zm/ExchangeRates.xml",  # Official Bank of Zambia
             lambda d: parse_boz_rate(d),  # Would need XML parsing
     ),
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

    async with httpx.AsyncClient(timeout=8) as client:
        for name, url, extractor in providers:
            for attempt in range(2):  # 2 attempts per provider
                try:
                    r = await client.get(url)
                    
                    if r.status_code == 429:
                        await asyncio.sleep(2)
                        continue
                        
                    r.raise_for_status()
                    zmw = extractor(r.json())
                    
                    # Sanity check: ZMW should be between 10-35 per USD
                    if zmw and 10 <= zmw <= 35:
                        return zmw, name
                    else:
                        logger.warning(f"⚠️  Suspicious ZMW rate from {name}: {zmw} — skipping")
                        
                except Exception as e:
                    logger.debug(f"Provider {name} attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(1)

    raise ValueError("All ZMW/USD FX providers failed")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def zmw_to_sats(zmw: float, zmw_per_btc: Decimal) -> int:
    """Convert ZMW amount to satoshis"""
    if zmw <= 0:
        return 0
    return int((Decimal(str(zmw)) / zmw_per_btc) * Decimal("100000000"))


def format_btc_display(zmw: float, zmw_per_btc: Decimal) -> str:
    """Format BTC amount for display"""
    if zmw <= 0:
        return "0.00000000"
    return f"{float(Decimal(str(zmw)) / zmw_per_btc):.8f}"


def sats_to_zmw(sats: int, zmw_per_btc: Decimal) -> Decimal:
    """Convert satoshis to ZMW"""
    if sats <= 0:
        return Decimal("0")
    btc_amount = Decimal(str(sats)) / Decimal("100000000")
    return btc_amount * zmw_per_btc