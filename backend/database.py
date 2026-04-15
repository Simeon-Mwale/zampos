import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.getenv("DATABASE_PATH", "./zampos.db")
WALLET_POOL_PATH = os.getenv("WALLET_POOL_PATH", "./config/wallet_pool.json")


# ------------------------
# CONNECTION
# ------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------
# INIT DB
# ------------------------

def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()

    # 🏪 Merchants table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT,
            wallet_id TEXT,
            admin_key TEXT,
            invoice_key TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(invoice_key)
        )
    """)

    # 💳 Transactions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_hash TEXT UNIQUE NOT NULL,
            amount_zmw REAL NOT NULL,
            amount_sats INTEGER NOT NULL,
            memo TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            merchant_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            paid_at TEXT,
            FOREIGN KEY (merchant_id) REFERENCES merchants(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized ✓")


# ------------------------
# MERCHANTS
# ------------------------

def save_merchant(name: str, wallet_id: str, admin_key: str, invoice_key: str, location: str = None) -> int:
    """Save new merchant to DB. Returns the newly created merchant_id."""
    conn = get_conn()
    try:
        cursor = conn.execute(
            """INSERT INTO merchants (name, location, wallet_id, admin_key, invoice_key)
               VALUES (?, ?, ?, ?, ?)""",
            (name, location, wallet_id, admin_key, invoice_key),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_merchant_by_id(merchant_id: int):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_merchant_by_invoice_key(invoice_key: str):
    """Lookup merchant by their invoice key (for webhook validation)"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM merchants WHERE invoice_key = ?", (invoice_key,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_merchants():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, name, location, created_at FROM merchants ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ------------------------
# WALLET POOL FUNCTIONS (NEW — FOR MERCHANT REGISTRATION)
# ------------------------

def _load_wallet_pool():
    """Load wallet pool JSON file"""
    if not os.path.exists(WALLET_POOL_PATH):
        raise RuntimeError(f"Wallet pool file not found: {WALLET_POOL_PATH}")
    with open(WALLET_POOL_PATH, "r") as f:
        return json.load(f)


def _save_wallet_pool(pool):
    """Save wallet pool JSON file"""
    os.makedirs(os.path.dirname(WALLET_POOL_PATH) or ".", exist_ok=True)
    with open(WALLET_POOL_PATH, "w") as f:
        json.dump(pool, f, indent=2)


def get_available_wallet_from_pool():
    """
    Get next unassigned wallet from pool.
    Returns wallet dict or raises RuntimeError if none available.
    """
    pool = _load_wallet_pool()
    for wallet in pool["wallets"]:
        if not wallet.get("assigned", False):
            return wallet.copy()  # Return copy to avoid modifying original
    raise RuntimeError(
        "No available wallets in pool. "
        f"Add more wallets to {WALLET_POOL_PATH} or create new wallets in LNBits Admin UI."
    )


def mark_wallet_assigned(wallet_inkey: str, merchant_id: int):
    """Mark a wallet as assigned to a merchant"""
    pool = _load_wallet_pool()
    for wallet in pool["wallets"]:
        if wallet["inkey"] == wallet_inkey:
            wallet["assigned"] = True
            wallet["merchant_id"] = merchant_id
            wallet["assigned_at"] = datetime.now().isoformat()
            break
    _save_wallet_pool(pool)
    print(f"[WalletPool] Assigned {wallet_inkey[:8]}... to merchant {merchant_id}")


def get_wallet_by_inkey(inkey: str):
    """Lookup wallet by invoice key (for webhook validation)"""
    pool = _load_wallet_pool()
    for wallet in pool["wallets"]:
        if wallet["inkey"] == inkey:
            return wallet
    return None


# ------------------------
# TRANSACTIONS
# ------------------------

def save_transaction(payment_hash: str, amount_zmw: float, amount_sats: int, memo: str, merchant_id: int):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO transactions
               (payment_hash, amount_zmw, amount_sats, memo, status, merchant_id)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (payment_hash, amount_zmw, amount_sats, memo, merchant_id)
        )
        conn.commit()
    finally:
        conn.close()


def mark_paid(payment_hash: str):
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE transactions SET status = 'paid', paid_at = datetime('now') WHERE payment_hash = ?""",
            (payment_hash,)
        )
        conn.commit()
    finally:
        conn.close()


def get_transactions(limit: int = 50):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT t.*, m.name as merchant_name
               FROM transactions t
               LEFT JOIN merchants m ON t.merchant_id = m.id
               ORDER BY t.created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_transactions_by_merchant(merchant_id: int, limit: int = 50):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM transactions WHERE merchant_id = ? ORDER BY created_at DESC LIMIT ?""",
            (merchant_id, limit)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ------------------------
# ANALYTICS
# ------------------------

def get_daily_totals(days: int = 7):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT date(paid_at) as day, COUNT(*) as count,
                      SUM(amount_zmw) as total_zmw, SUM(amount_sats) as total_sats
               FROM transactions WHERE status = 'paid'
                 AND paid_at >= datetime('now', ? || ' days')
               GROUP BY date(paid_at) ORDER BY day DESC""",
            (f"-{days}",)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_summary():
    conn = get_conn()
    try:
        today = conn.execute(
            """SELECT COUNT(*) as count, COALESCE(SUM(amount_zmw),0) as zmw,
                      COALESCE(SUM(amount_sats),0) as sats
               FROM transactions WHERE status = 'paid' AND date(paid_at) = date('now')"""
        ).fetchone()
        all_time = conn.execute(
            """SELECT COUNT(*) as count, COALESCE(SUM(amount_zmw),0) as zmw,
                      COALESCE(SUM(amount_sats),0) as sats
               FROM transactions WHERE status = 'paid'"""
        ).fetchone()
        return {"today": dict(today), "all_time": dict(all_time)}
    finally:
        conn.close()