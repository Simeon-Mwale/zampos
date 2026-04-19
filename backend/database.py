# backend/database.py — ZamPOS v2.1: Direct + Custodial payout modes
import aiosqlite, os, json, logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger  = logging.getLogger(__name__)
DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")


async def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir: os.makedirs(db_dir, exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_name              TEXT    NOT NULL,
                    location               TEXT,
                    phone_number           TEXT    NOT NULL,
                    payout_mode            TEXT    NOT NULL DEFAULT 'direct'
                                           CHECK(payout_mode IN ('direct','custodial')),
                    lightning_address      TEXT,
                    custodial_balance_sats INTEGER NOT NULL DEFAULT 0,
                    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(shop_name, phone_number)
                )""")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_hash     TEXT    NOT NULL UNIQUE,
                    merchant_id      INTEGER NOT NULL,
                    amount_zmw       REAL    NOT NULL,
                    gross_sats       INTEGER NOT NULL,
                    merchant_sats    INTEGER NOT NULL DEFAULT 0,
                    operator_sats    INTEGER NOT NULL DEFAULT 0,
                    memo             TEXT,
                    payout_mode      TEXT    NOT NULL DEFAULT 'direct',
                    status           TEXT    CHECK(status IN ('pending','paid','expired')) DEFAULT 'pending',
                    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at          TIMESTAMP,
                    sms_sent         INTEGER DEFAULT 0,
                    rate_snapshot    TEXT,
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )""")
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
                )""")
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_payment_hash ON transactions(payment_hash)",
                "CREATE INDEX IF NOT EXISTS idx_merchant_status ON transactions(merchant_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_withdrawals_merchant ON withdrawals(merchant_id)",
            ]: await db.execute(idx_sql)
            await _migrate(db)
            await db.commit()
            logger.info(f"✅ Database v2.1 initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"❌ DB init failed: {e}", exc_info=True); raise


async def _migrate(db):
    cols = [
        ("merchants",    "payout_mode",            "TEXT NOT NULL DEFAULT 'direct'"),
        ("merchants",    "lightning_address",       "TEXT"),
        ("merchants",    "custodial_balance_sats",  "INTEGER NOT NULL DEFAULT 0"),
        ("transactions", "payout_mode",             "TEXT NOT NULL DEFAULT 'direct'"),
        ("transactions", "merchant_sats",           "INTEGER NOT NULL DEFAULT 0"),
        ("transactions", "operator_sats",           "INTEGER NOT NULL DEFAULT 0"),
        ("transactions", "sms_sent",                "INTEGER DEFAULT 0"),
        ("transactions", "rate_snapshot",           "TEXT"),
    ]
    for table, col, defn in cols:
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
            logger.info(f"🔧 Migrated: {table}.{col}")
        except Exception: pass


def _parse_json(raw):
    if not raw: return None
    try: return json.loads(raw)
    except Exception: return None


# ── Merchant ───────────────────────────────────────────────────────────────────

async def create_merchant(shop_name, phone_number, payout_mode, location=None, lightning_address=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            shop_name = shop_name.strip()
            phone_number = phone_number.strip()

            # ✅ FIX 1: normalize lightning_address safely
            if lightning_address:
                lightning_address = lightning_address.strip().lower()
                if "@" not in lightning_address:
                    raise ValueError("Invalid lightning address")
            else:
                lightning_address = None

            # 🔍 Check existing merchant
            cur = await db.execute(
                "SELECT id,shop_name,location,phone_number,payout_mode,lightning_address,custodial_balance_sats,created_at "
                "FROM merchants WHERE shop_name=? AND phone_number=?",
                (shop_name, phone_number)
            )
            existing = await cur.fetchone()

            if existing:
                logger.info(f"♻️ Existing merchant reused: {shop_name}")
                return dict(existing)

            # ✅ FIX 2: NEVER pass NULL into NOT NULL column unexpectedly
            if payout_mode == "direct" and not lightning_address:
                raise ValueError("Lightning address required for direct mode")

            # ➕ Insert merchant
            cur = await db.execute(
                """
                INSERT INTO merchants
                (shop_name, location, phone_number, payout_mode, lightning_address)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    shop_name,
                    location.strip() if location else None,
                    phone_number,
                    payout_mode,
                    lightning_address
                )
            )

            mid = cur.lastrowid
            await db.commit()

            logger.info(f"✅ Merchant created: {shop_name} (ID={mid}) mode={payout_mode}")

            return {
                "merchant_id": mid,
                "shop_name": shop_name,
                "location": location.strip() if location else None,
                "phone_number": phone_number,
                "payout_mode": payout_mode,
                "lightning_address": lightning_address,
                "custodial_balance_sats": 0,
                "created_at": datetime.now(timezone.utc).isoformat()
            }

    except Exception as e:
        logger.error(f"❌ create_merchant: {e}", exc_info=True)
        raise

async def get_merchant_by_id(merchant_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id,shop_name,location,phone_number,payout_mode,lightning_address,custodial_balance_sats,created_at FROM merchants WHERE id=?",
                (merchant_id,))
            row = await cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ get_merchant_by_id: {e}"); return None


async def update_merchant(merchant_id, phone_number=None, lightning_address=None, location=None, payout_mode=None):
    try:
        fields, values = [], []
        if phone_number      is not None: fields.append("phone_number=?");      values.append(phone_number.strip())
        if lightning_address is not None: fields.append("lightning_address=?"); values.append(lightning_address.strip().lower())
        if location          is not None: fields.append("location=?");          values.append(location.strip())
        if payout_mode       is not None: fields.append("payout_mode=?");       values.append(payout_mode)
        if not fields: return True
        values.append(merchant_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f"UPDATE merchants SET {', '.join(fields)} WHERE id=?", values)
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"❌ update_merchant: {e}"); return False


async def credit_custodial_balance(merchant_id, sats):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE merchants SET custodial_balance_sats=custodial_balance_sats+? WHERE id=?", (sats, merchant_id))
            await db.commit(); return True
    except Exception as e:
        logger.error(f"❌ credit_custodial_balance: {e}"); return False


async def debit_custodial_balance(merchant_id, sats):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT custodial_balance_sats FROM merchants WHERE id=?", (merchant_id,))
            row = await cur.fetchone()
            if not row or row[0] < sats:
                logger.warning(f"⚠️ Insufficient balance merchant={merchant_id}"); return False
            await db.execute("UPDATE merchants SET custodial_balance_sats=custodial_balance_sats-? WHERE id=?", (sats, merchant_id))
            await db.commit(); return True
    except Exception as e:
        logger.error(f"❌ debit_custodial_balance: {e}"); return False


# ── Transactions ───────────────────────────────────────────────────────────────

async def save_transaction(payment_hash, merchant_id, amount_zmw, gross_sats, merchant_sats, operator_sats, memo, payout_mode, rate_snapshot=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO transactions (payment_hash,merchant_id,amount_zmw,gross_sats,merchant_sats,operator_sats,memo,payout_mode,status,rate_snapshot) VALUES(?,?,?,?,?,?,?,?,'pending',?)",
                (payment_hash, merchant_id, amount_zmw, gross_sats, merchant_sats, operator_sats, memo.strip(), payout_mode, json.dumps(rate_snapshot) if rate_snapshot else None))
            await db.commit(); return True
    except aiosqlite.IntegrityError: return True
    except Exception as e:
        logger.error(f"❌ save_transaction: {e}"); return False


async def mark_paid(payment_hash):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            r = await db.execute(
                "UPDATE transactions SET status='paid', paid_at=? WHERE payment_hash=? AND status='pending'",
                (datetime.now(timezone.utc), payment_hash))
            await db.commit()
            if r.rowcount > 0: logger.info(f"✅ Paid: {payment_hash[:12]}..."); return True
            return False
    except Exception as e:
        logger.error(f"❌ mark_paid: {e}"); return False


async def mark_sms_sent(payment_hash):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE transactions SET sms_sent=1 WHERE payment_hash=?", (payment_hash,))
            await db.commit(); return True
    except Exception as e:
        logger.error(f"❌ mark_sms_sent: {e}"); return False


async def get_transaction_by_hash(payment_hash):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id,payment_hash,merchant_id,amount_zmw,gross_sats,merchant_sats,operator_sats,memo,payout_mode,status,created_at,paid_at,sms_sent,rate_snapshot FROM transactions WHERE payment_hash=?",
                (payment_hash,))
            row = await cur.fetchone()
            if row:
                r = dict(row); r["rate_snapshot"] = _parse_json(r.get("rate_snapshot")); return r
            return None
    except Exception as e:
        logger.error(f"❌ get_transaction_by_hash: {e}"); return None


async def get_merchant_transactions(merchant_id, limit=50, status=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            q = "SELECT id,payment_hash,amount_zmw,gross_sats,merchant_sats,operator_sats,memo,payout_mode,status,created_at,paid_at,sms_sent,rate_snapshot FROM transactions WHERE merchant_id=?"
            params = [merchant_id]
            if status and status in ("pending","paid","expired"): q += " AND status=?"; params.append(status)
            q += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
            cur = await db.execute(q, params); rows = await cur.fetchall()
            result = []
            for row in rows:
                r = dict(row); r["rate_snapshot"] = _parse_json(r.get("rate_snapshot")); result.append(r)
            return result
    except Exception as e:
        logger.error(f"❌ get_merchant_transactions: {e}"); return []


async def get_transaction_summary(merchant_id=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE merchant_id=?" if merchant_id else ""
            params = (merchant_id,) if merchant_id else ()
            cur = await db.execute(
                f"SELECT COUNT(*) as total_count, COUNT(CASE WHEN status='paid' THEN 1 END) as paid_count, COALESCE(SUM(CASE WHEN status='paid' THEN amount_zmw END),0) as total_zmw, COALESCE(SUM(CASE WHEN status='paid' THEN gross_sats END),0) as total_sats, COALESCE(SUM(CASE WHEN status='paid' THEN operator_sats END),0) as total_operator_sats FROM transactions {where}", params)
            row = await cur.fetchone()
            return dict(row) if row else {"total_count":0,"paid_count":0,"total_zmw":0.0,"total_sats":0,"total_operator_sats":0}
    except Exception as e:
        logger.error(f"❌ get_transaction_summary: {e}")
        return {"total_count":0,"paid_count":0,"total_zmw":0.0,"total_sats":0,"total_operator_sats":0}


async def get_operator_earnings():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT COALESCE(SUM(operator_sats),0) as total_virtual_spread_sats, COUNT(*) as total_paid_count, COALESCE(SUM(amount_zmw),0) as total_volume_zmw FROM transactions WHERE status='paid'")
            row = await cur.fetchone()
            return dict(row) if row else {"total_virtual_spread_sats":0,"total_paid_count":0,"total_volume_zmw":0.0}
    except Exception as e:
        logger.error(f"❌ get_operator_earnings: {e}")
        return {"total_virtual_spread_sats":0,"total_paid_count":0,"total_volume_zmw":0.0}


# ── Withdrawals ────────────────────────────────────────────────────────────────

async def create_withdrawal(merchant_id, amount_sats, lightning_address, note=None):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT INTO withdrawals (merchant_id,amount_sats,lightning_address,note) VALUES(?,?,?,?)",
                (merchant_id, amount_sats, lightning_address.strip().lower(), note))
            wid = cur.lastrowid; await db.commit()
            return {"withdrawal_id": wid, "merchant_id": merchant_id, "amount_sats": amount_sats,
                    "lightning_address": lightning_address.strip().lower(), "status": "pending",
                    "requested_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"❌ create_withdrawal: {e}"); raise


async def mark_withdrawal_sent(withdrawal_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE withdrawals SET status='sent', processed_at=? WHERE id=?", (datetime.now(timezone.utc), withdrawal_id))
            await db.commit(); return True
    except Exception as e:
        logger.error(f"❌ mark_withdrawal_sent: {e}"); return False


async def mark_withdrawal_failed(withdrawal_id, reason):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE withdrawals SET status='failed', note=?, processed_at=? WHERE id=?", (reason, datetime.now(timezone.utc), withdrawal_id))
            await db.commit(); return True
    except Exception as e:
        logger.error(f"❌ mark_withdrawal_failed: {e}"); return False


async def get_merchant_withdrawals(merchant_id, limit=20):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id,merchant_id,amount_sats,lightning_address,status,note,requested_at,processed_at FROM withdrawals WHERE merchant_id=? ORDER BY requested_at DESC LIMIT ?",
                (merchant_id, limit))
            rows = await cur.fetchall(); return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"❌ get_merchant_withdrawals: {e}"); return []


async def cleanup_expired_transactions(expiry_minutes=30):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cutoff = datetime.now(timezone.utc).timestamp() - (expiry_minutes * 60)
            r = await db.execute("UPDATE transactions SET status='expired' WHERE status='pending' AND created_at < datetime(?,'unixepoch')", (cutoff,))
            await db.commit()
            if r.rowcount > 0: logger.info(f"🧹 Expired {r.rowcount} transactions")
            return r.rowcount
    except Exception as e:
        logger.error(f"❌ cleanup_expired: {e}"); return 0