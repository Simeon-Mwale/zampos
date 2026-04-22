# backend/database.py — ZamPOS v2.1 (Production Hardened)

import aiosqlite, os, json, logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")


# ---------------------------------------------
# INIT DB
# ---------------------------------------------

async def init_db():
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_name TEXT NOT NULL,
                    location TEXT,
                    phone_number TEXT NOT NULL,
                    payout_mode TEXT NOT NULL DEFAULT 'direct'
                        CHECK(payout_mode IN ('direct','custodial')),
                    lightning_address TEXT,
                    custodial_balance_sats INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(shop_name, phone_number)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_hash TEXT NOT NULL UNIQUE,
                    merchant_id INTEGER NOT NULL,
                    amount_zmw REAL NOT NULL,
                    gross_sats INTEGER NOT NULL,
                    merchant_sats INTEGER NOT NULL DEFAULT 0,
                    operator_sats INTEGER NOT NULL DEFAULT 0,
                    memo TEXT,
                    payout_mode TEXT NOT NULL DEFAULT 'direct',
                    status TEXT DEFAULT 'pending'
                        CHECK(status IN ('pending','paid','expired')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP,
                    sms_sent INTEGER DEFAULT 0,
                    rate_snapshot TEXT,
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_id INTEGER NOT NULL,
                    amount_sats INTEGER NOT NULL,
                    lightning_address TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','sent','failed')),
                    note TEXT,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_payment_hash ON transactions(payment_hash)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_merchant_status ON transactions(merchant_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_merchant ON withdrawals(merchant_id)")
            await _migrate(db)
            await db.commit()
            logger.info(f"DB ready: {DB_PATH}")
    except Exception as e:
        logger.error(f"init_db failed: {e}", exc_info=True)
        raise


# ---------------------------------------------
# SAFE MIGRATION
# ---------------------------------------------

async def _migrate(db):
    cols = [
        ("merchants", "payout_mode", "TEXT DEFAULT 'direct'"),
        ("merchants", "lightning_address", "TEXT"),
        ("merchants", "custodial_balance_sats", "INTEGER DEFAULT 0"),
        ("transactions", "merchant_sats", "INTEGER DEFAULT 0"),
        ("transactions", "operator_sats", "INTEGER DEFAULT 0"),
        ("transactions", "sms_sent", "INTEGER DEFAULT 0"),
        ("transactions", "rate_snapshot", "TEXT"),
    ]
    for table, col, definition in cols:
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
        except Exception:
            pass


# ---------------------------------------------
# HELPERS
# ---------------------------------------------

def _parse_json(raw: Any):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------
# MERCHANTS
# ---------------------------------------------

async def create_merchant(shop_name, phone_number, payout_mode, location=None, lightning_address=None):
    try:
        shop_name = shop_name.strip()
        phone_number = phone_number.strip()
        if lightning_address:
            lightning_address = lightning_address.strip().lower()
            if "@" not in lightning_address:
                raise ValueError("Invalid lightning address")
        else:
            lightning_address = None
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM merchants WHERE shop_name=? AND phone_number=?",
                (shop_name, phone_number)
            )
            existing = await cur.fetchone()
            if existing:
                return dict(existing)
            if payout_mode == "direct" and not lightning_address:
                raise ValueError("Lightning address required for direct mode")
            cur = await db.execute("""
                INSERT INTO merchants (shop_name, location, phone_number, payout_mode, lightning_address)
                VALUES (?, ?, ?, ?, ?)
            """, (shop_name, location.strip() if location else None, phone_number, payout_mode, lightning_address))
            await db.commit()
            return {
                "id": cur.lastrowid, "merchant_id": cur.lastrowid, "shop_name": shop_name,
                "location": location, "phone_number": phone_number, "payout_mode": payout_mode,
                "lightning_address": lightning_address, "custodial_balance_sats": 0, "created_at": _now()
            }
    except Exception as e:
        logger.error(f"create_merchant: {e}", exc_info=True)
        raise

async def get_merchant_by_id(merchant_id: int):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM merchants WHERE id=?", (merchant_id,))
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_merchant_by_id: {e}")
        return None

async def update_merchant(merchant_id, phone_number=None, lightning_address=None, location=None, payout_mode=None):
    try:
        fields, values = [], []
        if phone_number is not None:
            fields.append("phone_number=?"); values.append(phone_number.strip())
        if lightning_address is not None:
            fields.append("lightning_address=?"); values.append(lightning_address.strip().lower() if lightning_address else None)
        if location is not None:
            fields.append("location=?"); values.append(location.strip())
        if payout_mode is not None:
            fields.append("payout_mode=?"); values.append(payout_mode)
        if not fields:
            return True
        values.append(merchant_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f"UPDATE merchants SET {', '.join(fields)} WHERE id=?", values)
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"update_merchant: {e}")
        return False


# ---------------------------------------------
# CUSTODIAL
# ---------------------------------------------

async def credit_custodial_balance(merchant_id, sats):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE merchants SET custodial_balance_sats = custodial_balance_sats + ? WHERE id=?",
                (sats, merchant_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"credit_custodial_balance: {e}")
        return False

async def debit_custodial_balance(merchant_id, sats):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT custodial_balance_sats FROM merchants WHERE id=?", (merchant_id,))
            row = await cur.fetchone()
            if not row or row[0] < sats:
                return False
            await db.execute(
                "UPDATE merchants SET custodial_balance_sats = custodial_balance_sats - ? WHERE id=?",
                (sats, merchant_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"debit_custodial_balance: {e}")
        return False


# ---------------------------------------------
# TRANSACTIONS
# ---------------------------------------------

async def save_transaction(payment_hash, merchant_id, amount_zmw, gross_sats,
                           merchant_sats, operator_sats, memo, payout_mode, rate_snapshot=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO transactions (
                    payment_hash, merchant_id, amount_zmw, gross_sats, merchant_sats, operator_sats,
                    memo, payout_mode, status, rate_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (payment_hash, merchant_id, amount_zmw, gross_sats, merchant_sats, operator_sats,
                  memo, payout_mode, json.dumps(rate_snapshot) if rate_snapshot else None))
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        return True
    except Exception as e:
        logger.error(f"save_transaction: {e}")
        return False

async def get_transaction_by_hash(payment_hash):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM transactions WHERE payment_hash=?", (payment_hash,))
            row = await cur.fetchone()
            if not row:
                return None
            data = dict(row)
            data["rate_snapshot"] = _parse_json(data.get("rate_snapshot"))
            return data
    except Exception as e:
        logger.error(f"get_transaction_by_hash: {e}")
        return None

async def mark_paid(payment_hash):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "UPDATE transactions SET status='paid', paid_at=? WHERE payment_hash=? AND status='pending'",
                (_now(), payment_hash)
            )
            await db.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"mark_paid: {e}")
        return False

async def cleanup_expired_transactions(minutes=30):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                UPDATE transactions SET status='expired'
                WHERE status='pending' AND julianday('now') - julianday(created_at) > ?
            """, (minutes / (60 * 24),))
            await db.commit()
            return cur.rowcount
    except Exception as e:
        logger.error(f"cleanup_expired: {e}")
        return 0

async def mark_sms_sent(payment_hash: str):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE transactions SET sms_sent=1 WHERE payment_hash=?", (payment_hash,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"mark_sms_sent: {e}")
        return False

async def get_merchant_transactions(merchant_id: int, limit: int = 50, status: Optional[str] = None):
    """Get merchant transactions with optional status filter"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            if status:
                cur = await db.execute("""
                    SELECT * FROM transactions 
                    WHERE merchant_id = ? AND status = ? 
                    ORDER BY id DESC LIMIT ?
                """, (merchant_id, status, limit))
            else:
                cur = await db.execute("""
                    SELECT * FROM transactions 
                    WHERE merchant_id = ? 
                    ORDER BY id DESC LIMIT ?
                """, (merchant_id, limit))
            
            rows = await cur.fetchall()
            results = []
            for row in rows:
                data = dict(row)
                data["rate_snapshot"] = _parse_json(data.get("rate_snapshot"))
                results.append(data)
            return results
    except Exception as e:
        logger.error(f"get_merchant_transactions: {e}")
        return []
    
async def get_transaction_summary(merchant_id: int):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) as paid,
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) as expired,
                    COALESCE(SUM(gross_sats), 0) as total_sats
                FROM transactions WHERE merchant_id=?
            """, (merchant_id,))
            row = await cur.fetchone()
            if not row:
                return {"total": 0, "paid": 0, "pending": 0, "expired": 0, "total_sats": 0}
            return dict(row)
    except Exception as e:
        logger.error(f"get_transaction_summary: {e}")
        return {"total": 0, "paid": 0, "pending": 0, "expired": 0, "total_sats": 0}

async def get_operator_earnings():
    """Get total operator earnings across all merchants"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT COALESCE(SUM(operator_sats), 0) as total_operator_sats,
                       COALESCE(SUM(gross_sats), 0) as total_volume_sats,
                       COUNT(*) as total_transactions
                FROM transactions WHERE status='paid'
            """)
            row = await cur.fetchone()
            if not row:
                return {"total_operator_sats": 0, "total_volume_sats": 0, "total_transactions": 0}
            return dict(row)
    except Exception as e:
        logger.error(f"get_operator_earnings: {e}")
        return {"total_operator_sats": 0, "total_volume_sats": 0, "total_transactions": 0}

# ---------------------------------------------
# WITHDRAWALS
# ---------------------------------------------

async def create_withdrawal(merchant_id, amount_sats, lightning_address, note=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO withdrawals (merchant_id, amount_sats, lightning_address, note)
            VALUES (?, ?, ?, ?)
        """, (merchant_id, amount_sats, lightning_address, note))
        await db.commit()
        return cur.lastrowid

async def mark_withdrawal_sent(withdrawal_id: int):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE withdrawals SET status='sent', processed_at=? WHERE id=?",
                (_now(), withdrawal_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"mark_withdrawal_sent: {e}")
        return False

async def mark_withdrawal_failed(withdrawal_id: int, error_note: str = None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            if error_note:
                await db.execute(
                    "UPDATE withdrawals SET status='failed', processed_at=?, note=? WHERE id=?",
                    (_now(), error_note, withdrawal_id)
                )
            else:
                await db.execute(
                    "UPDATE withdrawals SET status='failed', processed_at=? WHERE id=?",
                    (_now(), withdrawal_id)
                )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"mark_withdrawal_failed: {e}")
        return False

# >>>>> NEW: Missing function router.py needs <<<<<
async def get_merchant_withdrawals(merchant_id: int, limit: int = 50):
    """Get withdrawal history for a merchant"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT * FROM withdrawals 
                WHERE merchant_id = ? 
                ORDER BY requested_at DESC 
                LIMIT ?
            """, (merchant_id, limit))
            rows = await cur.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"get_merchant_withdrawals: {e}")
        return []