# backend/services/ledger_service.py

import aiosqlite
import os
import json
import uuid

DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")


async def _insert_entry(
    merchant_id,
    account_type,
    direction,
    amount_sats,
    payment_hash=None,
    withdrawal_id=None,
    event_type="payment",
    metadata=None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO ledger_entries (
                merchant_id, account_type, direction,
                amount_sats, payment_hash, withdrawal_id,
                event_type, idempotency_key, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                merchant_id,
                account_type,
                direction,
                amount_sats,
                payment_hash,
                withdrawal_id,
                event_type,
                str(uuid.uuid4()),
                json.dumps(metadata or {}),
            ),
        )
        await db.commit()


# ── Public helpers ─────────────────────────────────────────

async def record_payment_split(tx):
    """
    Splits ONE payment into:
    - merchant earnings
    - operator earnings
    """

    # Merchant gets merchant_sats
    if tx["merchant_sats"] > 0:
        await _insert_entry(
            merchant_id=tx["merchant_id"],
            account_type="merchant",
            direction="credit",
            amount_sats=tx["merchant_sats"],
            payment_hash=tx["payment_hash"],
            event_type="payment",
        )

    # Operator gets spread
    if tx["operator_sats"] > 0:
        await _insert_entry(
            merchant_id=None,
            account_type="operator",
            direction="credit",
            amount_sats=tx["operator_sats"],
            payment_hash=tx["payment_hash"],
            event_type="fee",
        )


async def get_operator_earnings():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COALESCE(SUM(amount_sats), 0)
            FROM ledger_entries
            WHERE account_type='operator' AND direction='credit'
            """
        )
        total = (await cur.fetchone())[0]
        return {"operator_earnings_sats": total}


async def get_balance(merchant_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COALESCE(SUM(
                CASE WHEN direction='credit' THEN amount_sats
                     ELSE -amount_sats END
            ), 0)
            FROM ledger_entries
            WHERE merchant_id=?
            """,
            (merchant_id,),
        )
        return (await cur.fetchone())[0]


async def debit(merchant_id, sats, event_type="payout", withdrawal_id=None):
    await _insert_entry(
        merchant_id=merchant_id,
        account_type="merchant",
        direction="debit" if sats > 0 else "credit",
        amount_sats=abs(sats),
        withdrawal_id=withdrawal_id,
        event_type=event_type,
    )