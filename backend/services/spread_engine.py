# backend/services/spread_engine.py — ZamPOS v2 (Production Fixed)
#
# SPREAD LOGIC (corrected):
#   Real rate    = ZMW per sat (e.g. 0.0135 ZMW/sat)
#   We inflate the sats-per-ZMW conversion so the customer pays
#   slightly MORE sats than the real-rate equivalent.
#   The difference is operator revenue.
#
#   gross_sats    = sats customer is invoiced  (inflated)
#   real_sats     = sats the ZMW amount is worth at true market rate
#   operator_sats = gross_sats - real_sats     (always ≥ 0)
#   merchant_sats = real_sats                  (what merchant actually "earned")
#
# Previous bug: code LOWERED the rate (ZMW/BTC), which caused the customer
# to pay FEWER sats → operator_sats clamped to 0 → zero revenue.

import os
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

SPREAD_PCT = Decimal(os.getenv("ZAMPOS_SPREAD_PCT", "0.5"))   # e.g. 0.5 = 0.5%
MIN_SATS   = int(os.getenv("MIN_FORWARD_SATS", "1"))


# ─────────────────────────────────────────────────────────────
# INTERNAL: rate manipulation
# ─────────────────────────────────────────────────────────────

def _inflated_sats_per_zmw(real_sats_per_zmw: Decimal) -> Decimal:
    """
    Inflate the sats-per-ZMW ratio by SPREAD_PCT so the customer pays
    more sats.  A 0.5% spread means we multiply sats-per-ZMW by 1.005.

    Args:
        real_sats_per_zmw: True market sats per 1 ZMW

    Returns:
        Inflated ratio used for the invoice amount
    """
    factor = Decimal("1") + (SPREAD_PCT / Decimal("100"))
    return real_sats_per_zmw * factor


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

def apply_spread_to_rate(real_sats_per_zmw: float) -> float:
    """
    Return the *inflated* sats-per-ZMW ratio used when generating invoices.
    Keeping the signature compatible with existing callers.

    Note: real_sats_per_zmw is sats/ZMW (i.e. 100_000_000 / zmw_per_btc).
    Callers that previously passed zmw_per_btc should be updated;
    this function now works on sats_per_zmw.
    """
    inflated = _inflated_sats_per_zmw(Decimal(str(real_sats_per_zmw)))
    return float(inflated)


def calculate_spread(
    amount_zmw: float,
    real_sats_per_zmw: float,          # ← sats per ZMW (not ZMW per BTC)
) -> Tuple[int, int, int]:
    """
    Calculate invoice amounts with operator spread applied.

    Args:
        amount_zmw:        Sale amount in Zambian Kwacha
        real_sats_per_zmw: True market rate — how many sats equal 1 ZMW

    Returns:
        (gross_sats, merchant_sats, operator_sats)

        gross_sats    → amount on the Lightning invoice the customer pays
        merchant_sats → real-rate sats the merchant is credited
        operator_sats → spread revenue (gross − real)
    """
    if amount_zmw <= 0 or real_sats_per_zmw <= 0:
        return 0, 0, 0

    zmw     = Decimal(str(amount_zmw))
    real_sp = Decimal(str(real_sats_per_zmw))
    infl_sp = _inflated_sats_per_zmw(real_sp)

    # Truncate (floor) to avoid over-charging by rounding artefacts
    real_sats  = int((zmw * real_sp).to_integral_value(rounding=ROUND_DOWN))
    gross_sats = int((zmw * infl_sp).to_integral_value(rounding=ROUND_DOWN))

    # Spread is always non-negative by construction (infl_sp ≥ real_sp)
    operator_sats = max(0, gross_sats - real_sats)
    merchant_sats = real_sats   # merchant is credited at fair-market value

    logger.debug(
        f"SPREAD | ZMW={amount_zmw:.2f} | "
        f"real_sp={real_sats_per_zmw:.6f} | infl_sp={float(infl_sp):.6f} | "
        f"gross={gross_sats} | real={real_sats} | op={operator_sats}"
    )

    return gross_sats, merchant_sats, operator_sats


def is_invoiceable(gross_sats: int) -> Tuple[bool, str]:
    """Return (ok, reason) — False when invoice would be too small to route."""
    if gross_sats < MIN_SATS:
        return False, f"Invoice too small: {gross_sats} sats (minimum {MIN_SATS})"
    return True, ""


def spread_summary(gross: int, operator: int) -> dict:
    """Human-readable spread breakdown for API responses / logging."""
    real_sats = gross - operator
    return {
        "gross_sats":         gross,
        "merchant_sats":      real_sats,
        "operator_sats":      operator,
        "spread_pct_actual":  round((operator / gross * 100), 4) if gross else 0,
        "spread_pct_config":  float(SPREAD_PCT),
    }