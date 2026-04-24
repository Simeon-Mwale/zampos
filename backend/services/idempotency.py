# backend/services/idempotency.py

import aiosqlite
import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")


def generate_key(*parts) -> str:
    """Generate deterministic idempotency key"""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


async def exists(idempotency_key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM ledger_entries WHERE idempotency_key=? LIMIT 1",
            (idempotency_key,)
        )
        return await cur.fetchone() is not None


async def safe_insert(query: str, params: tuple) -> bool:
    """Generic safe insert guard (optional utility)"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(query, params)
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"Idempotency insert failed: {e}")
        return False