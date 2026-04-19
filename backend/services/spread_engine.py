# backend/services/spread_engine.py
# FX Spread Revenue Engine — ZamPOS v2
#
# Model: Single Invoice (WoS-compatible)
# ─────────────────────────────────────
# Since WoS has no outbound payment API, we use ONE invoice model:
#
#   Real rate:      1 BTC = 1,457,675 ZMW
#   Displayed rate: 1 BTC = 1,450,337 ZMW  (SPREAD_PCT % lower)
#
#   Merchant enters: K100
#   Displayed rate gives: 6,894 sats  ← customer is invoiced THIS amount
#   Real rate gives:      6,860 sats  ← merchant "should" receive
#   Spread = 34 sats ← this is your revenue, ALREADY IN the invoice
#
#   Since the invoice goes to MERCHANT's wallet directly,
#   operator_sats is VIRTUAL — it's the theoretical spread you earn
#   as a premium on the displayed rate. The merchant receives gross_sats
#   but the rate they were shown was already marked down.
#
#   In practice: merchant receives MORE sats than the real rate.
#   Your revenue = brand value, volume, potential future subscription model.
#
# ALTERNATIVE: Dual Invoice (future upgrade)
#   Invoice A → merchant's wallet (merchant_sats)
#   Invoice B → your WoS wallet  (operator_sats)
#   Both shown as one checkout. Requires frontend change.

import os
import logging
from decimal import Decimal, ROUND_FLOOR
from typing import Tuple

logger = logging.getLogger(__name__)

# Spread percentage shown as lower BTC/ZMW rate to merchant
SPREAD_PCT: float      = float(os.getenv("ZAMPOS_SPREAD_PCT", "0.5"))
MIN_FORWARD_SATS: int  = int(os.getenv("MIN_FORWARD_SATS", "100"))


def apply_spread_to_rate(real_zmw_per_btc: float) -> float:
    """
    Return the DISPLAYED rate (spread_pct % lower than real).
    This is what the merchant UI shows. Lower rate = more sats per ZMW.

    At 0.5% spread:
        real    = 1,457,675 ZMW/BTC
        display = 1,450,337 ZMW/BTC  (shown to merchant)
    """
    factor = 1.0 - (SPREAD_PCT / 100.0)
    return round(real_zmw_per_btc * factor, 2)


def calculate_spread(
    amount_zmw: float,
    real_zmw_per_btc: float,
) -> Tuple[int, int, int]:
    """
    Compute sats breakdown for a ZMW invoice amount.

    Returns (gross_sats, merchant_sats, operator_sats) where:
      gross_sats    = sats invoiced at DISPLAYED rate (customer pays this)
      merchant_sats = sats at REAL rate (baseline merchant value)
      operator_sats = gross - merchant (virtual spread — ZamPOS revenue)

    Since invoice goes directly to merchant wallet in v2 WoS model,
    merchant physically receives gross_sats.
    operator_sats is recorded as platform revenue metric.
    """
    if real_zmw_per_btc <= 0 or amount_zmw <= 0:
        return (0, 0, 0)

    displayed_rate = apply_spread_to_rate(real_zmw_per_btc)

    gross_sats = int(
        (Decimal(str(amount_zmw)) / Decimal(str(displayed_rate)) * Decimal("100000000"))
        .to_integral_value(rounding=ROUND_FLOOR)
    )
    merchant_sats = int(
        (Decimal(str(amount_zmw)) / Decimal(str(real_zmw_per_btc)) * Decimal("100000000"))
        .to_integral_value(rounding=ROUND_FLOOR)
    )
    operator_sats = max(0, gross_sats - merchant_sats)

    logger.debug(
        f"💱 Spread | ZMW={amount_zmw} | real={real_zmw_per_btc:,.0f} "
        f"| displayed={displayed_rate:,.0f} | gross={gross_sats} "
        f"| merchant={merchant_sats} | operator(virtual)={operator_sats}"
    )
    return (gross_sats, merchant_sats, operator_sats)


def is_invoiceable(gross_sats: int, min_sats: int = 1) -> Tuple[bool, str]:
    """Check if the sats amount is valid for invoicing."""
    if gross_sats < min_sats:
        return (False, f"Amount too small: {gross_sats} sats (min {min_sats})")
    return (True, "")


def spread_summary(gross_sats: int, merchant_sats: int, operator_sats: int) -> dict:
    pct = round((operator_sats / gross_sats) * 100, 3) if gross_sats > 0 else 0.0
    return {
        "gross_sats":    gross_sats,
        "merchant_sats": merchant_sats,
        "operator_sats": operator_sats,
        "spread_pct":    pct,
        "spread_config": SPREAD_PCT,
    }