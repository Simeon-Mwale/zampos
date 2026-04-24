# backend/database.py — ZamPOS v2.3 (Production Hardened with Duplicate Prevention & Recovery Codes)
#
# FIXES vs previous version:
#   1. Removed duplicate save_transaction definition
#   2. Fixed `get_transactions = get_merchant_transactions = None` — was
#      clobbering both names to None, breaking all router imports
#   3. os.makedirs now safe when DB_PATH has no directory component
#   4. Added credit() / debit() / get_balance() for settlement_engine.py
#   5. create_withdrawal wrapped in try/except
#   6. Consistent use of _now() everywhere (UTC ISO timestamps)
#   7. Added UNIQUE constraints for shop_name and phone_number
#   8. Added duplicate checking in create_merchant
#   9. Added check_duplicate_merchant function
#   10. Added recovery_code column and recovery functions

import aiosqlite
import os
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _parse_json(raw: Any):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_dir() -> str:
    """Return the directory that contains the DB file, safe for makedirs."""
    d = os.path.dirname(DB_PATH)
    return d if d else "."


def generate_recovery_code() -> str:
    """Generate a 16-character recovery code"""
    return secrets.token_hex(8).upper()


# ─────────────────────────────────────────────────────────────
# INIT DB
# ─────────────────────────────────────────────────────────────

async def init_db():
    try:
        os.makedirs(_db_dir(), exist_ok=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")

            # ── merchants with UNIQUE constraints and recovery_code ─────────────────
            await db.execute("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_name               TEXT    NOT NULL,
                    location                TEXT,
                    phone_number            TEXT    NOT NULL,
                    payout_mode             TEXT    NOT NULL DEFAULT 'direct'
                                                CHECK(payout_mode IN ('direct','custodial')),
                    lightning_address       TEXT,
                    custodial_balance_sats  INTEGER NOT NULL DEFAULT 0,
                    recovery_code           TEXT,
                    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(shop_name),
                    UNIQUE(phone_number)
                )
            """)

            # ── transactions ───────────────────────────────────
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_hash    TEXT    NOT NULL UNIQUE,
                    merchant_id     INTEGER NOT NULL,
                    amount_zmw      REAL    NOT NULL,
                    gross_sats      INTEGER NOT NULL,
                    merchant_sats   INTEGER NOT NULL DEFAULT 0,
                    operator_sats   INTEGER NOT NULL DEFAULT 0,
                    memo            TEXT,
                    payout_mode     TEXT    NOT NULL DEFAULT 'direct',
                    status          TEXT    DEFAULT 'pending'
                                        CHECK(status IN ('pending','paid','expired')),
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at         TIMESTAMP,
                    sms_sent        INTEGER DEFAULT 0,
                    rate_snapshot   TEXT,
                    operator_swept  INTEGER DEFAULT 0,
                    swept_at        TIMESTAMP,
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )
            """)

            # ── withdrawals ────────────────────────────────────
            await db.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_id       INTEGER NOT NULL,
                    amount_sats       INTEGER NOT NULL,
                    lightning_address TEXT    NOT NULL,
                    status            TEXT    NOT NULL DEFAULT 'pending'
                                          CHECK(status IN ('pending','sent','failed')),
                    note              TEXT,
                    requested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at      TIMESTAMP,
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )
            """)

            # ── operator_sweeps ────────────────────────────────
            await db.execute("""
                CREATE TABLE IF NOT EXISTS operator_sweeps (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount_sats INTEGER NOT NULL,
                    status      TEXT    DEFAULT 'pending'
                                    CHECK(status IN ('pending','paid','failed')),
                    bolt11      TEXT,
                    swept_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at     TIMESTAMP
                )
            """)

            # ── ledger (credit/debit audit trail) ─────────────
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ledger_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_id     INTEGER NOT NULL,
                    amount_sats     INTEGER NOT NULL,
                    event_type      TEXT    NOT NULL,
                    withdrawal_id   INTEGER,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (merchant_id)   REFERENCES merchants(id),
                    FOREIGN KEY (withdrawal_id) REFERENCES withdrawals(id)
                )
            """)

            # ── indexes ────────────────────────────────────────
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_payment_hash     ON transactions(payment_hash)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_merchant_status  ON transactions(merchant_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_withdrawals_merchant ON withdrawals(merchant_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ledger_merchant  ON ledger_events(merchant_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_merchants_phone ON merchants(phone_number)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_merchants_shop_name ON merchants(shop_name)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_merchants_recovery ON merchants(recovery_code)"
            )

            await _migrate(db)
            await db.commit()

        logger.info(f"✅ DB ready with duplicate prevention & recovery codes: {DB_PATH}")

    except Exception as e:
        logger.error(f"init_db failed: {e}", exc_info=True)
        raise


# ─────────────────────────────────────────────────────────────
# MIGRATIONS  (safe ALTER TABLE — silently skips existing cols)
# ─────────────────────────────────────────────────────────────

async def _migrate(db):
    _pending_cols = [
        ("merchants",     "payout_mode",             "TEXT DEFAULT 'direct'"),
        ("merchants",     "lightning_address",        "TEXT"),
        ("merchants",     "custodial_balance_sats",   "INTEGER DEFAULT 0"),
        ("merchants",     "recovery_code",            "TEXT"),
        ("transactions",  "merchant_sats",            "INTEGER DEFAULT 0"),
        ("transactions",  "operator_sats",            "INTEGER DEFAULT 0"),
        ("transactions",  "sms_sent",                 "INTEGER DEFAULT 0"),
        ("transactions",  "rate_snapshot",            "TEXT"),
        ("transactions",  "operator_swept",           "INTEGER DEFAULT 0"),
        ("transactions",  "swept_at",                 "TIMESTAMP"),
    ]

    for table, col, definition in _pending_cols:
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
        except Exception:
            pass  # column already exists — harmless


# ─────────────────────────────────────────────────────────────
# DUPLICATE CHECK
# ─────────────────────────────────────────────────────────────

async def check_duplicate_merchant(
    phone_number: Optional[str] = None,
    shop_name: Optional[str] = None
) -> Optional[dict]:
    """Check if a merchant already exists with given phone or shop name.
    
    Returns:
        dict with merchant info if duplicate exists, None otherwise
    """
    if not phone_number and not shop_name:
        return None
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            conditions = []
            params = []
            
            if phone_number:
                conditions.append("phone_number = ?")
                params.append(phone_number.strip())
            if shop_name:
                conditions.append("shop_name = ?")
                params.append(shop_name.strip())
            
            query = f"SELECT id, shop_name, phone_number FROM merchants WHERE {' OR '.join(conditions)}"
            cur = await db.execute(query, params)
            row = await cur.fetchone()
            
            if row:
                return dict(row)
            return None
            
    except Exception as e:
        logger.error(f"check_duplicate_merchant: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# RECOVERY CODE FUNCTIONS
# ─────────────────────────────────────────────────────────────

async def update_recovery_code(merchant_id: int, recovery_code: str) -> bool:
    """Store recovery code for a merchant"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE merchants SET recovery_code = ? WHERE id = ?",
                (recovery_code, merchant_id)
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"update_recovery_code: {e}")
        return False


async def get_merchant_by_recovery_code(recovery_code: str) -> Optional[dict]:
    """Find merchant by recovery code"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM merchants WHERE recovery_code = ?",
                (recovery_code.strip().upper(),)
            )
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_merchant_by_recovery_code: {e}")
        return None


async def verify_recovery(phone_number: str, recovery_code: str) -> Optional[dict]:
    """Verify recovery code matches merchant"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM merchants WHERE phone_number = ? AND recovery_code = ?",
                (phone_number.strip(), recovery_code.strip().upper())
            )
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"verify_recovery: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# MERCHANTS
# ─────────────────────────────────────────────────────────────

async def create_merchant(
    shop_name: str,
    phone_number: str,
    payout_mode: str,
    location: Optional[str] = None,
    lightning_address: Optional[str] = None,
    recovery_code: Optional[str] = None,
) -> dict:
    try:
        shop_name = shop_name.strip()
        phone_number = phone_number.strip()

        # Check for duplicates BEFORE inserting
        duplicate = await check_duplicate_merchant(
            phone_number=phone_number,
            shop_name=shop_name
        )
        
        if duplicate:
            raise ValueError(
                f"Merchant already exists: {duplicate['shop_name']} ({duplicate['phone_number']})"
            )

        if lightning_address:
            lightning_address = lightning_address.strip().lower()
            if "@" not in lightning_address:
                raise ValueError("Invalid lightning address — must be user@domain.com")
        else:
            lightning_address = None

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            cur = await db.execute(
                """
                INSERT INTO merchants
                    (shop_name, location, phone_number, payout_mode, lightning_address, recovery_code)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    shop_name,
                    location.strip() if location else None,
                    phone_number,
                    payout_mode,
                    lightning_address,
                    recovery_code,
                ),
            )
            await db.commit()

            return {
                "id":                     cur.lastrowid,
                "merchant_id":            cur.lastrowid,
                "shop_name":              shop_name,
                "location":               location,
                "phone_number":           phone_number,
                "payout_mode":            payout_mode,
                "lightning_address":      lightning_address,
                "custodial_balance_sats": 0,
                "recovery_code":          recovery_code,
                "created_at":             _now(),
            }

    except ValueError as e:
        raise e  # Re-raise duplicate error
    except Exception as e:
        logger.error(f"create_merchant: {e}", exc_info=True)
        raise


async def get_merchant_by_id(merchant_id: int) -> Optional[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM merchants WHERE id=?", (merchant_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_merchant_by_id: {e}")
        return None


async def get_merchant_by_phone(phone_number: str) -> Optional[dict]:
    """Get merchant by phone number - useful for duplicate checking"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM merchants WHERE phone_number=?", (phone_number.strip(),)
            )
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_merchant_by_phone: {e}")
        return None


async def update_merchant(
    merchant_id: int,
    phone_number: Optional[str]      = None,
    lightning_address: Optional[str] = None,
    location: Optional[str]          = None,
    payout_mode: Optional[str]       = None,
) -> bool:
    try:
        fields, values = [], []

        if phone_number is not None:
            # Check if new phone number is already taken by another merchant
            existing = await get_merchant_by_phone(phone_number)
            if existing and existing["id"] != merchant_id:
                raise ValueError(f"Phone number {phone_number} is already registered to another shop")
            fields.append("phone_number=?")
            values.append(phone_number.strip())

        if lightning_address is not None:
            fields.append("lightning_address=?")
            values.append(
                lightning_address.strip().lower() if lightning_address else None
            )

        if location is not None:
            fields.append("location=?")
            values.append(location.strip())

        if payout_mode is not None:
            fields.append("payout_mode=?")
            values.append(payout_mode)

        if not fields:
            return True  # nothing to update

        values.append(merchant_id)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE merchants SET {', '.join(fields)} WHERE id=?", values
            )
            await db.commit()

        return True

    except ValueError as e:
        raise e
    except Exception as e:
        logger.error(f"update_merchant: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# CUSTODIAL BALANCE
# ─────────────────────────────────────────────────────────────

async def credit_custodial_balance(merchant_id: int, sats: int) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE merchants "
                "SET custodial_balance_sats = custodial_balance_sats + ? "
                "WHERE id=?",
                (sats, merchant_id),
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"credit_custodial_balance: {e}")
        return False


async def debit_custodial_balance(merchant_id: int, sats: int) -> bool:
    """Atomically debit custodial balance; returns False if funds insufficient."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT custodial_balance_sats FROM merchants WHERE id=?",
                (merchant_id,),
            )
            row = await cur.fetchone()
            if not row or row[0] < sats:
                return False

            await db.execute(
                "UPDATE merchants "
                "SET custodial_balance_sats = custodial_balance_sats - ? "
                "WHERE id=?",
                (sats, merchant_id),
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"debit_custodial_balance: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# LEDGER  (used by settlement_engine.py)
# ─────────────────────────────────────────────────────────────

async def get_balance(merchant_id: int) -> int:
    """Return current custodial balance for a merchant (0 if not found)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT custodial_balance_sats FROM merchants WHERE id=?",
                (merchant_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"get_balance: {e}")
        return 0


async def debit(
    merchant_id: int,
    sats: int,
    event_type: str = "payout",
    withdrawal_id: Optional[int] = None,
) -> bool:
    """
    Debit custodial balance and record a ledger event.
    Returns False if balance is insufficient or DB write fails.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Check balance inside the same connection for consistency
            cur = await db.execute(
                "SELECT custodial_balance_sats FROM merchants WHERE id=?",
                (merchant_id,),
            )
            row = await cur.fetchone()
            if not row or row[0] < sats:
                return False

            await db.execute(
                "UPDATE merchants "
                "SET custodial_balance_sats = custodial_balance_sats - ? "
                "WHERE id=?",
                (sats, merchant_id),
            )
            await db.execute(
                "INSERT INTO ledger_events "
                "    (merchant_id, amount_sats, event_type, withdrawal_id) "
                "VALUES (?, ?, ?, ?)",
                (merchant_id, -sats, event_type, withdrawal_id),
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"debit: {e}", exc_info=True)
        return False


async def credit(
    merchant_id: int,
    sats: int,
    event_type: str = "payout_reversal",
    withdrawal_id: Optional[int] = None,
) -> bool:
    """
    Credit custodial balance and record a ledger event.
    Used for payout reversals when a Lightning payment fails.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE merchants "
                "SET custodial_balance_sats = custodial_balance_sats + ? "
                "WHERE id=?",
                (sats, merchant_id),
            )
            await db.execute(
                "INSERT INTO ledger_events "
                "    (merchant_id, amount_sats, event_type, withdrawal_id) "
                "VALUES (?, ?, ?, ?)",
                (merchant_id, sats, event_type, withdrawal_id),
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"credit: {e}", exc_info=True)
        return False


# ─────────────────────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────────────────────

async def save_transaction(
    payment_hash:  str,
    merchant_id:   int,
    amount_zmw:    float,
    gross_sats:    int,
    merchant_sats: int,
    operator_sats: int,
    memo:          str,
    payout_mode:   str,
    rate_snapshot: Optional[dict] = None,
) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO transactions (
                    payment_hash, merchant_id, amount_zmw, gross_sats,
                    merchant_sats, operator_sats, memo, payout_mode,
                    status, rate_snapshot
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    payment_hash, merchant_id, amount_zmw, gross_sats,
                    merchant_sats, operator_sats, memo, payout_mode,
                    json.dumps(rate_snapshot) if rate_snapshot else None,
                ),
            )
            await db.commit()
        return True

    except aiosqlite.IntegrityError:
        # Duplicate payment_hash — idempotent, not an error
        return True
    except Exception as e:
        logger.error(f"save_transaction: {e}", exc_info=True)
        return False


async def get_transaction_by_hash(payment_hash: str) -> Optional[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM transactions WHERE payment_hash=?",
                (payment_hash,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            data = dict(row)
            data["rate_snapshot"] = _parse_json(data.get("rate_snapshot"))
            return data
    except Exception as e:
        logger.error(f"get_transaction_by_hash: {e}")
        return None


async def mark_paid(payment_hash: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                UPDATE transactions
                SET status='paid', paid_at=?
                WHERE payment_hash=? AND status='pending'
                """,
                (_now(), payment_hash),
            )
            await db.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"mark_paid: {e}")
        return False


async def cleanup_expired_transactions(minutes: int = 30) -> int:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                UPDATE transactions
                SET status='expired'
                WHERE status='pending'
                AND (julianday('now') - julianday(created_at)) > ?
                """,
                (minutes / (60 * 24),),
            )
            await db.commit()
            return cur.rowcount
    except Exception as e:
        logger.error(f"cleanup_expired: {e}")
        return 0


async def mark_sms_sent(payment_hash: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE transactions SET sms_sent=1 WHERE payment_hash=?",
                (payment_hash,),
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"mark_sms_sent: {e}")
        return False


async def get_merchant_transactions(
    merchant_id: int,
    limit: int = 50,
    status: Optional[str] = None,
) -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            if status:
                cur = await db.execute(
                    """
                    SELECT * FROM transactions
                    WHERE merchant_id=? AND status=?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (merchant_id, status, limit),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT * FROM transactions
                    WHERE merchant_id=?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (merchant_id, limit),
                )

            rows = await cur.fetchall()
            result = []
            for r in rows:
                row = dict(r)
                row["rate_snapshot"] = _parse_json(row.get("rate_snapshot"))
                result.append(row)
            return result

    except Exception as e:
        logger.error(f"get_merchant_transactions: {e}", exc_info=True)
        return []


async def get_transaction_summary(merchant_id: int) -> dict:
    _empty = {"total": 0, "paid": 0, "pending": 0, "expired": 0, "total_sats": 0}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='paid'    THEN 1 ELSE 0 END) as paid,
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) as expired,
                    COALESCE(SUM(gross_sats), 0) as total_sats
                FROM transactions
                WHERE merchant_id=?
                """,
                (merchant_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else _empty
    except Exception as e:
        logger.error(f"get_transaction_summary: {e}", exc_info=True)
        return _empty


# ─────────────────────────────────────────────────────────────
# WITHDRAWALS
# ─────────────────────────────────────────────────────────────

async def create_withdrawal(
    merchant_id: int,
    amount_sats: int,
    lightning_address: str,
    note: Optional[str] = None,
) -> Optional[int]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                INSERT INTO withdrawals
                    (merchant_id, amount_sats, lightning_address, note)
                VALUES (?, ?, ?, ?)
                """,
                (merchant_id, amount_sats, lightning_address, note),
            )
            await db.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error(f"create_withdrawal: {e}", exc_info=True)
        return None


async def mark_withdrawal_sent(withdrawal_id: int) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE withdrawals SET status='sent', processed_at=? WHERE id=?",
                (_now(), withdrawal_id),
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"mark_withdrawal_sent: {e}")
        return False


async def mark_withdrawal_failed(
    withdrawal_id: int, error_note: Optional[str] = None
) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            if error_note:
                await db.execute(
                    "UPDATE withdrawals "
                    "SET status='failed', processed_at=?, note=? "
                    "WHERE id=?",
                    (_now(), error_note, withdrawal_id),
                )
            else:
                await db.execute(
                    "UPDATE withdrawals "
                    "SET status='failed', processed_at=? "
                    "WHERE id=?",
                    (_now(), withdrawal_id),
                )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"mark_withdrawal_failed: {e}")
        return False


async def get_merchant_withdrawals(merchant_id: int, limit: int = 50) -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT * FROM withdrawals
                WHERE merchant_id=?
                ORDER BY requested_at DESC
                LIMIT ?
                """,
                (merchant_id, limit),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_merchant_withdrawals: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# OPERATOR EARNINGS
# ─────────────────────────────────────────────────────────────

async def get_operator_earnings() -> dict:
    _empty = {
        "total_operator_sats": 0,
        "total_volume_sats":   0,
        "total_transactions":  0,
        "sweep_count":         0,
        "total_fee_sats":      0,
        "total_gross_sats":    0,
        "total_net_sats":      0,
    }
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            cur = await db.execute(
                """
                SELECT
                    COALESCE(SUM(operator_sats), 0) as total_operator_sats,
                    COALESCE(SUM(gross_sats),    0) as total_volume_sats,
                    COUNT(*)                         as total_transactions
                FROM transactions
                WHERE status='paid'
                """
            )
            row = await cur.fetchone()

            cur2 = await db.execute(
                "SELECT COUNT(*) as count FROM operator_sweeps"
            )
            sweep_row = await cur2.fetchone()

            total_fee    = row["total_operator_sats"] if row else 0
            total_volume = row["total_volume_sats"]   if row else 0
            total_tx     = row["total_transactions"]  if row else 0
            sweep_count  = sweep_row["count"]         if sweep_row else 0

            return {
                "total_operator_sats": total_fee,
                "total_volume_sats":   total_volume,
                "total_transactions":  total_tx,
                "sweep_count":         sweep_count,
                "total_fee_sats":      total_fee,
                "total_gross_sats":    total_volume,
                "total_net_sats":      total_volume - total_fee,
            }

    except Exception as e:
        logger.error(f"get_operator_earnings: {e}", exc_info=True)
        return _empty


# ─────────────────────────────────────────────────────────────
# PUBLIC ALIASES
# ─────────────────────────────────────────────────────────────
get_transactions = get_merchant_transactions