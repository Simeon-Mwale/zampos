# backend/database.py — Production-Ready SQLite Layer for ZamPOS (with rate_snapshot support)
import aiosqlite
import os
import json  # ✅ Added for JSON serialization
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Database path with fallback
DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")

async def init_db():
    """
    Initialize SQLite database with required tables.
    ✅ Added rate_snapshot column for locked FX rate data
    """
    try:
        # Ensure data directory exists
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Enable foreign keys (SQLite requires this per-connection)
            await db.execute("PRAGMA foreign_keys = ON")
            
            # Create merchants table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_name TEXT NOT NULL,
                    location TEXT,
                    node_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(shop_name, location)
                )
            """)
            
            # Create transactions table with rate_snapshot column ✅
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_hash TEXT NOT NULL UNIQUE,
                    merchant_id INTEGER NOT NULL,
                    amount_zmw REAL NOT NULL,
                    amount_sats INTEGER NOT NULL,
                    memo TEXT,
                    status TEXT CHECK(status IN ('pending', 'paid', 'expired')) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP,
                    rate_snapshot TEXT,  -- ✅ NEW: JSON string storing locked rate data
                    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
                )
            """)
            
            # ✅ Create indexes SEPARATELY (SQLite requirement)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_payment_hash 
                ON transactions(payment_hash)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_merchant_status 
                ON transactions(merchant_id, status)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON transactions(created_at DESC)
            """)
            
            await db.commit()
            logger.info(f"✅ Database initialized at {DB_PATH}")
            
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        raise


# ✅ Helper: Parse rate_snapshot from JSON string to dict
def _parse_rate_snapshot(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Safely parse rate_snapshot JSON string from DB"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"⚠️ Failed to parse rate_snapshot: {raw[:50]}...")
        return None


async def get_merchant_by_id(merchant_id: int) -> Optional[Dict[str, Any]]:
    """Fetch merchant by ID with proper error handling"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, shop_name, location, node_id, created_at FROM merchants WHERE id = ?",
                (merchant_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ Failed to fetch merchant {merchant_id}: {e}")
        return None


async def create_merchant(shop_name: str, location: Optional[str] = None) -> Dict[str, Any]:
    """
    Register new merchant.
    All merchants share the org-level Voltage node (multi-tenant design).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Use Voltage Org ID as node identifier (all merchants share one node)
            node_id = os.getenv("VOLTAGE_ORG_ID", "zampos_default")
            
            cursor = await db.execute(
                """INSERT INTO merchants (shop_name, location, node_id) 
                   VALUES (?, ?, ?)""",
                (shop_name.strip(), location.strip() if location else None, node_id)
            )
            merchant_id = cursor.lastrowid
            await db.commit()
            
            logger.info(f"✅ Merchant registered: {shop_name} (ID: {merchant_id})")
            
            return {
                "merchant_id": merchant_id,
                "shop_name": shop_name.strip(),
                "location": location.strip() if location else None,
                # Mask API key for frontend display (never expose full key)
                "invoice_key": (os.getenv("VOLTAGE_API_KEY", "")[:12] + "...") if os.getenv("VOLTAGE_API_KEY") else "",
                "wallet_id": f"node_{node_id}",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
    except aiosqlite.IntegrityError:
        logger.warning(f"⚠️ Duplicate merchant registration attempt: {shop_name}")
        raise ValueError(f"Shop '{shop_name}' already registered")
    except Exception as e:
        logger.error(f"❌ Failed to create merchant: {e}", exc_info=True)
        raise


async def save_transaction(
    payment_hash: str,
    merchant_id: int,
    amount_zmw: float,
    amount_sats: int,
    memo: str,
    rate_snapshot: Optional[Dict[str, Any]] = None  # ✅ NEW optional parameter
) -> bool:
    """
    Save new pending transaction with optional locked rate snapshot.
    Returns True if saved, False if failed (non-critical — invoice already created).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # ✅ Serialize rate_snapshot dict to JSON string for storage
            rate_snapshot_json = json.dumps(rate_snapshot) if rate_snapshot else None
            
            await db.execute(
                """INSERT INTO transactions 
                   (payment_hash, merchant_id, amount_zmw, amount_sats, memo, status, rate_snapshot)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (payment_hash, merchant_id, amount_zmw, amount_sats, memo.strip(), rate_snapshot_json)
            )
            await db.commit()
            logger.debug(f"💾 Transaction saved: {payment_hash[:12]}...")
            return True
    except aiosqlite.IntegrityError:
        # Payment hash already exists — idempotent, not an error
        logger.debug(f"⚠️ Transaction already exists: {payment_hash[:12]}...")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save transaction {payment_hash[:12]}...: {e}")
        # Non-critical: invoice was already created on Voltage
        return False


async def mark_paid(payment_hash: str) -> bool:
    """Mark transaction as paid with UTC timestamp"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            result = await db.execute(
                "UPDATE transactions SET status = 'paid', paid_at = ? WHERE payment_hash = ?",
                (datetime.now(timezone.utc), payment_hash)
            )
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(f"✅ Payment confirmed: {payment_hash[:12]}...")
                return True
            else:
                logger.warning(f"⚠️ No transaction found to mark paid: {payment_hash[:12]}...")
                return False
    except Exception as e:
        logger.error(f"❌ Failed to mark paid {payment_hash[:12]}...: {e}")
        return False


async def get_transaction_by_hash(payment_hash: str) -> Optional[Dict[str, Any]]:
    """Fetch single transaction by payment hash — with rate_snapshot parsed ✅"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT id, payment_hash, merchant_id, amount_zmw, amount_sats, 
                          memo, status, created_at, paid_at, rate_snapshot 
                   FROM transactions WHERE payment_hash = ?""",
                (payment_hash,)
            )
            row = await cursor.fetchone()
            if row:
                result = dict(row)
                # ✅ Parse rate_snapshot from JSON string back to dict
                result["rate_snapshot"] = _parse_rate_snapshot(result.get("rate_snapshot"))
                return result
            return None
    except Exception as e:
        logger.error(f"❌ Failed to fetch transaction {payment_hash[:12]}...: {e}")
        return None


async def get_merchant_transactions(
    merchant_id: int, 
    limit: int = 50,
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get transactions for a merchant with optional status filter.
    Optimized for dashboard pagination — with rate_snapshot parsed ✅
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            query = """
                SELECT id, payment_hash, amount_zmw, amount_sats, memo, 
                       status, created_at, paid_at, rate_snapshot 
                FROM transactions 
                WHERE merchant_id = ?
            """
            params: List[Any] = [merchant_id]
            
            if status and status in ('pending', 'paid', 'expired'):
                query += " AND status = ?"
                params.append(status)
                
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            # ✅ Parse rate_snapshot for each transaction
            results = []
            for row in rows:
                result = dict(row)
                result["rate_snapshot"] = _parse_rate_snapshot(result.get("rate_snapshot"))
                results.append(result)
            return results
            
    except Exception as e:
        logger.error(f"❌ Failed to fetch transactions for merchant {merchant_id}: {e}")
        return []


async def get_transaction_summary(merchant_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get sales summary: total ZMW, total sats, transaction counts.
    Optional merchant_id filter for per-merchant stats.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            if merchant_id:
                cursor = await db.execute("""
                    SELECT 
                        COUNT(*) as total_count,
                        COUNT(CASE WHEN status = 'paid' THEN 1 END) as paid_count,
                        COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_zmw END), 0) as total_zmw,
                        COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_sats END), 0) as total_sats
                    FROM transactions 
                    WHERE merchant_id = ?
                """, (merchant_id,))
            else:
                cursor = await db.execute("""
                    SELECT 
                        COUNT(*) as total_count,
                        COUNT(CASE WHEN status = 'paid' THEN 1 END) as paid_count,
                        COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_zmw END), 0) as total_zmw,
                        COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_sats END), 0) as total_sats
                    FROM transactions
                """)
            
            row = await cursor.fetchone()
            return dict(row) if row else {
                "total_count": 0, "paid_count": 0, "total_zmw": 0, "total_sats": 0
            }
    except Exception as e:
        logger.error(f"❌ Failed to fetch transaction summary: {e}")
        return {"total_count": 0, "paid_count": 0, "total_zmw": 0, "total_sats": 0}


async def cleanup_expired_transactions(expiry_minutes: int = 30) -> int:
    """
    Mark unpaid invoices as 'expired' after timeout.
    Run periodically via background task or cron.
    Zambia-optimized: 30 min default for low-connectivity areas.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cutoff = datetime.now(timezone.utc).timestamp() - (expiry_minutes * 60)
            result = await db.execute("""
                UPDATE transactions 
                SET status = 'expired' 
                WHERE status = 'pending' 
                AND created_at < datetime(?, 'unixepoch')
            """, (cutoff,))
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(f"🧹 Cleaned up {result.rowcount} expired transactions")
            return result.rowcount
    except Exception as e:
        logger.error(f"❌ Failed to cleanup expired transactions: {e}")
        return 0