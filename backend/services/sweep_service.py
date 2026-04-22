# backend/services/sweep_service.py
import os
import logging
import asyncio
from datetime import datetime
from typing import Tuple, Dict, Any
import aiosqlite

from services.lnurl_pay import fetch_invoice_from_lightning_address

logger = logging.getLogger(__name__)

# Operator wallet (YOUR wallet for gas fees)
OPERATOR_WALLET = os.getenv("OPERATOR_WALLET", "flashysuit96@walletofsatoshi.com")
MIN_SWEEP_SATS = int(os.getenv("MIN_SWEEP_SATS", "10000"))  # Min 10k sats to auto-sweep
DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")


async def get_accumulated_gas_fees() -> Tuple[int, Dict[str, Any]]:
    """Get total accumulated gas fees and details"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Get total operator fees
        cur = await db.execute("""
            SELECT 
                COALESCE(SUM(operator_sats), 0) as total_fees,
                COUNT(*) as transaction_count,
                MIN(created_at) as first_transaction,
                MAX(created_at) as last_transaction
            FROM transactions 
            WHERE status='paid' AND (operator_swept IS NULL OR operator_swept=0)
        """)
        row = await cur.fetchone()
        
        # Get last sweep time
        cur2 = await db.execute("""
            SELECT swept_at, amount_sats 
            FROM operator_sweeps 
            ORDER BY swept_at DESC LIMIT 1
        """)
        last_sweep = await cur2.fetchone()
        
        return row["total_fees"] if row else 0, {
            "transaction_count": row["transaction_count"] if row else 0,
            "first_transaction": row["first_transaction"] if row else None,
            "last_transaction": row["last_transaction"] if row else None,
            "last_sweep_at": last_sweep["swept_at"] if last_sweep else None,
            "last_sweep_amount": last_sweep["amount_sats"] if last_sweep else 0,
        }


async def sweep_gas_fees(force: bool = False) -> Dict[str, Any]:
    """
    Automatically sweep accumulated gas fees to operator wallet.
    Returns sweep result.
    """
    total_fees, details = await get_accumulated_gas_fees()
    
    if total_fees == 0:
        return {"success": False, "message": "No gas fees to sweep", "amount": 0}
    
    if not force and total_fees < MIN_SWEEP_SATS:
        return {
            "success": False, 
            "message": f"Not enough fees. Need {MIN_SWEEP_SATS} sats, have {total_fees} sats",
            "amount": total_fees,
            "min_required": MIN_SWEEP_SATS
        }
    
    try:
        logger.info(f"💰 Auto-sweeping {total_fees} sats to {OPERATOR_WALLET}")
        
        # Fetch invoice from operator's wallet to receive the fees
        bolt11 = await fetch_invoice_from_lightning_address(
            OPERATOR_WALLET, 
            total_fees, 
            comment=f"Auto-sweep of gas fees from {details['transaction_count']} transactions"
        )
        
        # Record the sweep
        async with aiosqlite.connect(DB_PATH) as db:
            # Insert sweep record
            cursor = await db.execute("""
                INSERT INTO operator_sweeps (amount_sats, status, bolt11, swept_at)
                VALUES (?, 'pending', ?, ?)
            """, (total_fees, bolt11, datetime.now().isoformat()))
            sweep_id = cursor.lastrowid
            
            # Mark transactions as swept
            await db.execute("""
                UPDATE transactions 
                SET operator_swept=1, swept_at=?
                WHERE status='paid' AND (operator_swept IS NULL OR operator_swept=0)
            """, (datetime.now().isoformat(),))
            
            await db.commit()
        
        logger.info(f"✅ Auto-sweep initiated: {total_fees} sats to {OPERATOR_WALLET}")
        
        return {
            "success": True,
            "sweep_id": sweep_id,
            "amount": total_fees,
            "transaction_count": details["transaction_count"],
            "bolt11": bolt11,
            "wallet": OPERATOR_WALLET,
            "message": f"Sweeping {total_fees} sats to your wallet"
        }
        
    except Exception as e:
        logger.error(f"❌ Auto-sweep failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "amount": total_fees,
            "message": f"Sweep failed: {str(e)}"
        }


async def check_sweep_status(sweep_id: int) -> Dict[str, Any]:
    """Check if a sweep has been paid"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM operator_sweeps WHERE id=?", (sweep_id,)
        )
        row = await cur.fetchone()
        
        if not row:
            return {"success": False, "message": "Sweep not found"}
        
        return {
            "id": row["id"],
            "amount": row["amount_sats"],
            "status": row["status"],
            "swept_at": row["swept_at"],
            "paid_at": row["paid_at"],
            "bolt11": row["bolt11"]
        }


async def get_sweep_history(limit: int = 50) -> list:
    """Get history of operator sweeps"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT * FROM operator_sweeps 
            ORDER BY swept_at DESC 
            LIMIT ?
        """, (limit,))
        rows = await cur.fetchall()
        return [dict(row) for row in rows]