# backend/services/rate_service.py - Improved with better rate limiting handling
import httpx
import os
import time
import logging
import asyncio
from decimal import Decimal
from typing import Tuple, Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
CACHE_TTL = int(os.getenv("RATE_CACHE_TTL_SECONDS", "180"))  # Increased to 3 minutes
REQUEST_DELAY = float(os.getenv("RATE_REQUEST_DELAY_SECONDS", "3.0"))  # Throttle more
MAX_RETRIES = 2

_cache = {
    "zmw_per_btc": None,
    "sats_per_zmw": None,
    "timestamp": 0,
    "source": "none",
}

_last_request_time = 0
_rate_limit_backoff = 1  # Start with 1 second backoff

# ─────────────────────────────────────────────
# REALISTIC MARKET RATE FOR APRIL 2026
# 1 BTC ≈ 1,470,000 ZMW → ~68 sats/ZMW
# ─────────────────────────────────────────────
FALLBACK_ZMW_PER_BTC = Decimal("1470000")  # More realistic fallback
FALLBACK_ZMW_PER_USD = Decimal("28.0")     # Current ZMW/USD rate


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
    global _rate_limit_backoff
    now = time.time()

    # ── Cache hit (longer TTL to avoid rate limits) ──
    if not force_refresh and _cache["zmw_per_btc"] and (now - _cache["timestamp"]) < CACHE_TTL:
        logger.debug(f"📦 Using cached rate (age: {int(now - _cache['timestamp'])}s)")
        return _cache["zmw_per_btc"], _cache["sats_per_zmw"]

    zmw_per_btc = None
    source = "fallback"
    errors = []

    # ─────────────────────────────────────────
    # SOURCE 1: CoinGecko BTC/USD (with exponential backoff)
    # ─────────────────────────────────────────
    try:
        await _throttle_requests()
        btc_usd = await _fetch_btc_usd_with_backoff()
        
        # Get ZMW/USD rate
        try:
            zmw_usd, fx_source = await _fetch_zmw_usd_with_retry()
            source = f"coingecko+{fx_source}"
            logger.debug(f"📈 Live FX rate: 1 USD = {zmw_usd} ZMW (via {fx_source})")
        except Exception as fx_err:
            logger.warning(f"⚠️ FX sources failed, using fallback: {fx_err}")
            zmw_usd = float(FALLBACK_ZMW_PER_USD)
            source = "coingecko+fx-fallback"
            errors.append(f"FX: {fx_err}")

        zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))
        
        # Reset backoff on success
        _rate_limit_backoff = 1

    except Exception as e:
        logger.warning(f"❌ BTC price fetch failed: {e}")
        errors.append(f"BTC: {e}")

    # ─────────────────────────────────────────
    # SOURCE 2: Alternative crypto API (CoinCap - no rate limits)
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        try:
            await _throttle_requests()
            btc_usd = await _fetch_btc_usd_coincap()
            zmw_usd = float(FALLBACK_ZMW_PER_USD)
            zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))
            source = "coincap+fx-fallback"
            logger.info(f"✅ Using CoinCap API: {btc_usd} USD/BTC")
        except Exception as e:
            logger.warning(f"❌ CoinCap API failed: {e}")
            errors.append(f"CoinCap: {e}")

    # ─────────────────────────────────────────
    # SOURCE 3: Try Binance as last resort
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        try:
            await _throttle_requests()
            btc_usd = await _fetch_btc_usd_binance()
            zmw_usd = float(FALLBACK_ZMW_PER_USD)
            zmw_per_btc = Decimal(str(btc_usd)) * Decimal(str(zmw_usd))
            source = "binance+fx-fallback"
            logger.info(f"✅ Using Binance API: {btc_usd} USD/BTC")
        except Exception as e:
            logger.warning(f"❌ Binance API failed: {e}")
            errors.append(f"Binance: {e}")

    # ─────────────────────────────────────────
    # FINAL FALLBACK (all sources failed)
    # ─────────────────────────────────────────
    if not zmw_per_btc:
        logger.error(f"🚨 All rate sources failed ({', '.join(errors)}) — using static fallback")
        zmw_per_btc = FALLBACK_ZMW_PER_BTC
        source = "static-fallback"

    sats_per_zmw = Decimal("100000000") / zmw_per_btc

    _cache.update({
        "zmw_per_btc": zmw_per_btc,
        "sats_per_zmw": sats_per_zmw,
        "timestamp": now,
        "source": source,
    })

    logger.info(f"💱 Rate updated | {zmw_per_btc:,.2f} ZMW/BTC | {source} | ≈ {float(sats_per_zmw):.2f} sats/ZMW")

    return zmw_per_btc, sats_per_zmw


async def _throttle_requests():
    """Prevent API rate limiting by spacing out requests"""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < REQUEST_DELAY:
        await asyncio.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


async def _fetch_btc_usd_with_backoff() -> float:
    """Fetch BTC/USD with exponential backoff for rate limits"""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                
                if r.status_code == 429:
                    wait_time = (attempt + 1) * 5  # 5, 10, 15 seconds
                    logger.warning(f"⚠️ Rate limited (429), waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                    
                r.raise_for_status()
                data = r.json()
                price = float(data["bitcoin"]["usd"])
                
                if price > 0:
                    return price
                    
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            logger.debug(f"Retry {attempt + 1}/{MAX_RETRIES} after error: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    raise ValueError("Failed to fetch BTC/USD after retries")


async def _fetch_btc_usd_coincap() -> float:
    """Fetch BTC/USD from CoinCap (no rate limits, free)"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.coincap.io/v2/rates/bitcoin")
        r.raise_for_status()
        data = r.json()
        return float(data["data"]["rateUsd"])


async def _fetch_btc_usd_binance() -> float:
    """Fetch BTC/USDT from Binance"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BTCUSDT"})
        r.raise_for_status()
        data = r.json()
        return float(data["price"])


async def _fetch_zmw_usd_with_retry() -> Tuple[float, str]:
    """Fetch ZMW/USD with provider fallback"""
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
    ]

    async with httpx.AsyncClient(timeout=10) as client:
        for name, url, extractor in providers:
            try:
                r = await client.get(url)
                r.raise_for_status()
                zmw = extractor(r.json())
                
                if zmw and 10 <= zmw <= 35:
                    return zmw, name
                else:
                    logger.warning(f"⚠️ Suspicious ZMW rate from {name}: {zmw} — skipping")
                    
            except Exception as e:
                logger.debug(f"Provider {name} failed: {e}")
                await asyncio.sleep(1)

    raise ValueError("All ZMW/USD FX providers failed")


def parse_boz_rate(xml_content: str) -> float:
    """Parse Bank of Zambia exchange rate from XML"""
    try:
        root = ET.fromstring(xml_content)
        # Find USD/ZMW rate in the XML structure
        for currency in root.findall(".//currency"):
            if currency.findtext("currencyCode") == "USD":
                buying_rate = currency.findtext("buyingRate")
                if buying_rate:
                    return float(buying_rate)
    except Exception as e:
        logger.debug(f"BOZ XML parsing failed: {e}")
    raise ValueError("Could not parse BOZ rate")


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