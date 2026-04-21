# backend/services/spread_engine.py
import os
import logging
from decimal import Decimal, ROUND_FLOOR
from typing import Tuple

logger = logging.getLogger(__name__)

SPREAD_PCT = float(os.getenv("ZAMPOS_SPREAD_PCT", "0.5"))
MIN_SATS = int(os.getenv("MIN_FORWARD_SATS", "1"))


def apply_spread_to_rate(real_rate: float) -> float:
    """
    Lower displayed rate → increases sats per ZMW slightly
    This is your margin engine (price-layer spread).
    """
    factor = 1.0 - (SPREAD_PCT / 100.0)
    return float(Decimal(str(real_rate)) * Decimal(str(factor)))


def calculate_spread(amount_zmw: float, real_rate: float) -> Tuple[int, int, int]:
    """
    RETURNS:
        gross_sats    → customer invoice
        merchant_sats → what merchant receives
        operator_sats → your revenue (virtual tracking)
    """

    if amount_zmw <= 0 or real_rate <= 0:
        return 0, 0, 0

    displayed_rate = apply_spread_to_rate(real_rate)

    gross_sats = int(
        (Decimal(str(amount_zmw)) / Decimal(str(displayed_rate)))
        * Decimal("100000000")
    )

    real_value_sats = int(
        (Decimal(str(amount_zmw)) / Decimal(str(real_rate)))
        * Decimal("100000000")
    )

    operator_sats = max(0, real_value_sats - gross_sats)

    merchant_sats = gross_sats

    logger.debug(
        f"SPREAD | ZMW={amount_zmw} | real={real_rate} | "
        f"display={displayed_rate} | gross={gross_sats} | op={operator_sats}"
    )

    return gross_sats, merchant_sats, operator_sats


def is_invoiceable(gross_sats: int) -> Tuple[bool, str]:
    if gross_sats < MIN_SATS:
        return False, "Invoice too small"
    return True, ""


def spread_summary(gross: int, operator: int) -> dict:
    return {
        "gross_sats": gross,
        "merchant_sats": gross,
        "operator_sats": operator,
        "spread_pct_actual": (operator / gross * 100) if gross else 0,
        "spread_config": SPREAD_PCT,
    }