import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DATABASE_PATH", "./zampos.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_hash TEXT UNIQUE NOT NULL,
            amount_zmw REAL NOT NULL,
            amount_sats INTEGER NOT NULL,
            memo TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            paid_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Database initialized ✓")


def save_transaction(payment_hash: str, amount_zmw: float, amount_sats: int, memo: str):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO transactions
               (payment_hash, amount_zmw, amount_sats, memo, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (payment_hash, amount_zmw, amount_sats, memo)
        )
        conn.commit()
    finally:
        conn.close()


def mark_paid(payment_hash: str):
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE transactions
               SET status = 'paid', paid_at = datetime('now')
               WHERE payment_hash = ?""",
            (payment_hash,)
        )
        conn.commit()
    finally:
        conn.close()


def get_transactions(limit: int = 50):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM transactions
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_daily_totals(days: int = 7):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT
                date(paid_at) as day,
                COUNT(*) as count,
                SUM(amount_zmw) as total_zmw,
                SUM(amount_sats) as total_sats
               FROM transactions
               WHERE status = 'paid'
                 AND paid_at >= datetime('now', ? || ' days')
               GROUP BY date(paid_at)
               ORDER BY day DESC""",
            (f"-{days}",)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_summary():
    conn = get_conn()
    try:
        today = conn.execute(
            """SELECT COUNT(*) as count, COALESCE(SUM(amount_zmw),0) as zmw, COALESCE(SUM(amount_sats),0) as sats
               FROM transactions
               WHERE status = 'paid' AND date(paid_at) = date('now')"""
        ).fetchone()
        all_time = conn.execute(
            """SELECT COUNT(*) as count, COALESCE(SUM(amount_zmw),0) as zmw, COALESCE(SUM(amount_sats),0) as sats
               FROM transactions WHERE status = 'paid'"""
        ).fetchone()
        return {
            "today": dict(today),
            "all_time": dict(all_time)
        }
    finally:
        conn.close()
