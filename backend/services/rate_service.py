# backend/services/rate_service.py
import httpx
import os
import logging
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)

COINGECKO_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
FX_API_URL = os.getenv("FX_API_BASE_URL", "https://v6.exchangerate-api.com/v6")
FX_API_KEY = os.getenv("FX_API_KEY", "")
RATE_CACHE_TTL = int(os.getenv("RATE_CACHE_TTL_SECONDS", "45"))

_rate_cache: Dict = {
    "zmw_per_btc": None,
    "sats_per_zmw": None,
    "fetched_at": None,
    "source": None
}

SATOSHI_PER_BTC = Decimal("100000000")


def _is_cache_valid() -> bool:
    if not _rate_cache["fetched_at"] or not _rate_cache["zmw_per_btc"]:
        return False
    age = (datetime.utcnow() - _rate_cache["fetched_at"]).total_seconds()
    return age < RATE_CACHE_TTL


def get_cache_metadata() -> Dict:
    return {
        "last_updated": int(_rate_cache["fetched_at"].timestamp()) if _rate_cache["fetched_at"] else None,
        "source": _rate_cache.get("source", "unknown"),
        "is_valid": _is_cache_valid(),
        "zmw_per_btc": float(_rate_cache["zmw_per_btc"]) if _rate_cache["zmw_per_btc"] else None,
        "sats_per_zmw": float(_rate_cache["sats_per_zmw"]) if _rate_cache["sats_per_zmw"] else None
    }


async def _fetch_btc_usd_price() -> Optional[Decimal]:
    """Fetch BTC price in USD from CoinGecko with API key."""
    try:
        params = {"ids": "bitcoin", "vs_currencies": "usd"}
        if COINGECKO_API_KEY:
            params["x_cg_demo_api_key"] = COINGECKO_API_KEY

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COINGECKO_URL}/simple/price", params=params)
            resp.raise_for_status()
            data = resp.json()
            price_usd = Decimal(str(data["bitcoin"]["usd"]))
            if price_usd > 0:
                logger.info(f"✅ CoinGecko: 1 BTC = {price_usd:,.2f} USD")
                return price_usd
    except Exception as e:
        logger.warning(f"⚠️ CoinGecko BTC/USD fetch failed: {e}")
    return None


async def _fetch_usd_zmw_rate() -> Optional[Decimal]:
    """Fetch USD/ZMW FX rate."""
    if FX_API_KEY and FX_API_URL:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{FX_API_URL}/{FX_API_KEY}/latest/USD")
                resp.raise_for_status()
                data = resp.json()
                rate = Decimal(str(data["conversion_rates"]["ZMW"]))
                if rate > 0:
                    logger.info(f"💱 FX API: 1 USD = {rate:.4f} ZMW")
                    return rate
        except Exception as e:
            logger.warning(f"⚠️ FX API fetch failed: {e}")

    # Fallback: CoinGecko direct ZMW
    try:
        params = {"ids": "bitcoin", "vs_currencies": "usd,zmw"}
        if COINGECKO_API_KEY:
            params["x_cg_demo_api_key"] = COINGECKO_API_KEY

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{COINGECKO_URL}/simple/price", params=params)
            resp.raise_for_status()
            data = resp.json()
            btc_usd = Decimal(str(data["bitcoin"]["usd"]))
            btc_zmw = Decimal(str(data["bitcoin"]["zmw"]))
            if btc_usd > 0 and btc_zmw > 0:
                usd_zmw = btc_zmw / btc_usd
                logger.info(f"💱 CoinGecko fallback: 1 USD = {usd_zmw:.4f} ZMW")
                return usd_zmw
    except Exception as e:
        logger.warning(f"⚠️ CoinGecko ZMW fallback failed: {e}")

    return None


async def fetch_live_rates(force_refresh: bool = False) -> Tuple[Decimal, Decimal]:
    if not force_refresh and _is_cache_valid():
        return _rate_cache["zmw_per_btc"], _rate_cache["sats_per_zmw"]

    logger.info("🔄 Fetching fresh exchange rates...")

    btc_usd = await _fetch_btc_usd_price()
    usd_zmw = await _fetch_usd_zmw_rate()

    if not btc_usd or not usd_zmw:
        if _rate_cache["zmw_per_btc"] and _rate_cache["sats_per_zmw"]:
            logger.warning("⚠️ Using cached rates due to API failure")
            return _rate_cache["zmw_per_btc"], _rate_cache["sats_per_zmw"]
        logger.error("❌ All rate sources failed - using emergency fallback")
        emergency_zmw_per_btc = Decimal("1500000")
        emergency_sats_per_zmw = (SATOSHI_PER_BTC / emergency_zmw_per_btc).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN)
        return emergency_zmw_per_btc, emergency_sats_per_zmw

    zmw_per_btc = (btc_usd * usd_zmw).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    sats_per_zmw = (SATOSHI_PER_BTC / zmw_per_btc).quantize(
        Decimal("0.00000001"), rounding=ROUND_DOWN)

    _rate_cache.update({
        "zmw_per_btc": zmw_per_btc,
        "sats_per_zmw": sats_per_zmw,
        "fetched_at": datetime.utcnow(),
        "source": "live"
    })

    logger.info(f"✅ Rates: 1 BTC = {zmw_per_btc:,.2f} ZMW | 1 ZMW = {sats_per_zmw:.8f} sats")
    return zmw_per_btc, sats_per_zmw


def zmw_to_sats(zmw_amount: float, zmw_per_btc: Optional[Decimal] = None) -> int:
    try:
        amount = Decimal(str(zmw_amount))
        if amount <= 0:
            return 0
        rate = zmw_per_btc
        if rate is None:
            if _is_cache_valid():
                rate = _rate_cache["zmw_per_btc"]
            else:
                return 0
        sats = (amount / rate * SATOSHI_PER_BTC).to_integral_value(rounding=ROUND_DOWN)
        return max(int(sats), 1)
    except (InvalidOperation, ValueError, TypeError) as e:
        logger.error(f"❌ Conversion error: {e}")
        return 0


def format_btc_display(zmw_amount: float, zmw_per_btc: Decimal) -> str:
    try:
        amount = Decimal(str(zmw_amount))
        btc = amount / zmw_per_btc
        return f"{btc:.8f}"
    except:
        return "0.00000000"