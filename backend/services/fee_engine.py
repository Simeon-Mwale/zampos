# backend/services/fee_engine.py
"""
ZamPOS Gas Fee Engine
─────────────────────
Deducts routing/gas fee from merchant payout before sweep to Phoenix.

Revenue model:
  - Flat 50 sats per withdrawal (matches ROADMAP withdrawal fee stream)
  - Fee goes to platform owner (fossilbean17@phoenixwallet.me)
  - Merchant receives: gross_sats - 50 sats
"""

import logging
import aiosqlite
import os
from datetime import datetime, timezone
from typing import TypedDict

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")

# ── Fee configuration ──────────────────────────────────────────────────────────
GAS_FEE_SATS = int(os.getenv("GAS_FEE_SATS", "50"))       # flat sats per sweep
MIN_PAYOUT_SATS = int(os.getenv("MIN_PAYOUT_SATS", "100")) # minimum after fee


class FeeResult(TypedDict):
    gross_sats: int
    fee_sats: int
    net_sats: int
    fee_type: str
    sweepable: bool
    reason: str


def calculate_gas_fee(gross_sats: int) -> FeeResult:
    """
    Calculate gas fee for a given gross amount.
    Returns a FeeResult dict with all breakdown details.

    Rules:
      - Fee is flat GAS_FEE_SATS (default 50 sats)
      - If net_sats < MIN_PAYOUT_SATS, mark as not sweepable
    """
    fee_sats = GAS_FEE_SATS
    net_sats = gross_sats - fee_sats

    if net_sats < MIN_PAYOUT_SATS:
        return FeeResult(
            gross_sats=gross_sats,
            fee_sats=fee_sats,
            net_sats=net_sats,
            fee_type="gas_flat",
            sweepable=False,
            reason=f"Net payout ({net_sats} sats) below minimum ({MIN_PAYOUT_SATS} sats)"
        )

    return FeeResult(
        gross_sats=gross_sats,
        fee_sats=fee_sats,
        net_sats=net_sats,
        fee_type="gas_flat",
        sweepable=True,
        reason="OK"
    )


async def log_gas_fee(
    payment_hash: str,
    merchant_id: int,
    gross_sats: int,
    fee_sats: int,
    net_sats: int,
) -> bool:
    """
    Persist gas fee record to DB after successful Phoenix sweep.
    Creates gas_fees table if it doesn't exist yet (safe to call repeatedly).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Ensure table exists (idempotent)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS gas_fees (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_hash   TEXT NOT NULL,
                    merchant_id    INTEGER NOT NULL,
                    gross_sats     INTEGER NOT NULL,
                    fee_sats       INTEGER NOT NULL,
                    net_sats       INTEGER NOT NULL,
                    swept_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_gas_fees_merchant
                ON gas_fees(merchant_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_gas_fees_hash
                ON gas_fees(payment_hash)
            """)

            await db.execute("""
                INSERT INTO gas_fees
                    (payment_hash, merchant_id, gross_sats, fee_sats, net_sats, swept_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                payment_hash,
                merchant_id,
                gross_sats,
                fee_sats,
                net_sats,
                datetime.now(timezone.utc).isoformat()
            ))
            await db.commit()

        logger.info(
            f"💰 Gas fee logged | hash={payment_hash[:12]}... "
            f"gross={gross_sats} fee={fee_sats} net={net_sats}"
        )
        return True

    except Exception as e:
        logger.error(f"❌ Failed to log gas fee for {payment_hash[:12]}...: {e}")
        return False


async def get_total_fees_collected(merchant_id: int | None = None) -> dict:
    """
    Platform owner dashboard helper.
    Returns total gas fees collected (all merchants or one merchant).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if merchant_id:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*)        AS sweep_count,
                        SUM(fee_sats)   AS total_fee_sats,
                        SUM(gross_sats) AS total_gross_sats,
                        SUM(net_sats)   AS total_net_sats
                    FROM gas_fees WHERE merchant_id = ?
                """, (merchant_id,))
            else:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*)        AS sweep_count,
                        SUM(fee_sats)   AS total_fee_sats,
                        SUM(gross_sats) AS total_gross_sats,
                        SUM(net_sats)   AS total_net_sats
                    FROM gas_fees
                """)
            row = await cursor.fetchone()
            return dict(row) if row else {
                "sweep_count": 0,
                "total_fee_sats": 0,
                "total_gross_sats": 0,
                "total_net_sats": 0,
            }
    except Exception as e:
        logger.error(f"❌ Failed to fetch fee totals: {e}")
        return {"sweep_count": 0, "total_fee_sats": 0, "total_gross_sats": 0, "total_net_sats": 0}