# backend/services/fees.py — Platform Revenue Collection
import aiosqlite
import os
import json
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any
from datetime import datetime

DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")

# Platform revenue configuration
PLATFORM_TRANSACTION_FEE_PERCENTAGE = float(os.getenv("PLATFORM_TRANSACTION_FEE_PERCENTAGE", "0.5"))  # 0.5%
PLATFORM_WITHDRAWAL_FEE_SATS = int(os.getenv("PLATFORM_WITHDRAWAL_FEE_SATS", "50"))  # 50 sats flat
PLATFORM_FX_SPREAD_PERCENTAGE = float(os.getenv("PLATFORM_FX_SPREAD_PERCENTAGE", "0.5"))  # 0.5% hidden spread

async def calculate_transaction_fee(amount_zmw: float, merchant_id: int) -> Dict[str, float]:
    """
    Calculate platform fee for a transaction.
    Returns: { gross_amount, fee_amount, net_amount, fee_percentage }
    """
    # Get merchant's custom fee rate (if any)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT fee_percentage FROM merchant_settings WHERE merchant_id = ?",
            (merchant_id,)
        )
        row = await cursor.fetchone()
        fee_percentage = row[0] if row else PLATFORM_TRANSACTION_FEE_PERCENTAGE
    
    fee_amount = round(amount_zmw * (fee_percentage / 100), 2)
    net_amount = round(amount_zmw - fee_amount, 2)
    
    return {
        "gross_amount": amount_zmw,
        "fee_amount": fee_amount,
        "net_amount": net_amount,
        "fee_percentage": fee_percentage
    }

async def calculate_withdrawal_fee(amount_sats: int, merchant_id: int) -> Dict[str, int]:
    """
    Calculate platform fee for a withdrawal.
    Returns: { gross_sats, fee_amount, net_amount, fee_percentage }
    """
    # Flat fee for simplicity (can be % based if preferred)
    fee_amount = PLATFORM_WITHDRAWAL_FEE_SATS
    net_amount = max(0, amount_sats - fee_amount)
    
    fee_percentage = round((fee_amount / amount_sats * 100) if amount_sats > 0 else 0, 2)
    
    return {
        "gross_amount": amount_sats,
        "fee_amount": fee_amount,
        "net_amount": net_amount,
        "fee_percentage": fee_percentage
    }

async def record_fee(
    merchant_id: int,
    fee_type: str,
    amount_sats: int,
    amount_zmw: Optional[float] = None,
    transaction_id: Optional[int] = None
) -> bool:
    """Record platform fee in database for owner earnings tracking"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO platform_fees 
                (merchant_id, transaction_id, fee_type, amount_sats, amount_zmw, collected_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (merchant_id, transaction_id, fee_type, amount_sats, amount_zmw, datetime.utcnow()))
            await db.commit()
            return True
    except Exception as e:
        print(f"❌ Failed to record fee: {e}")
        return False

async def get_platform_earnings(
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Get total platform earnings (for admin dashboard)"""
    async with aiosqlite.connect(DB_PATH) as db:
        query = """
            SELECT 
                COUNT(*) as total_fees,
                SUM(amount_sats) as total_sats,
                SUM(amount_zmw) as total_zmw,
                fee_type
            FROM platform_fees
            WHERE 1=1
        """
        params = []
        
        if start_date:
            query += " AND collected_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND collected_at <= ?"
            params.append(end_date)
        
        query += " GROUP BY fee_type"
        
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        
        total_sats = sum(row[1] or 0 for row in rows)
        total_zmw = sum(row[2] or 0 for row in rows)
        
        return {
            "total_fees_collected": len(rows),
            "total_sats": total_sats,
            "total_zmw": round(total_zmw, 2),
            "breakdown": [
                {"type": row[3], "sats": row[1], "zmw": row[2]}
                for row in rows
            ]
        }

def apply_fx_spread(zmw_per_btc: float) -> float:
    """
    Apply FX spread to exchange rate (hidden revenue).
    If real rate is 1,500,000 ZMW/BTC, show merchant 1,507,500 (0.5% worse).
    Merchant pays slightly more sats, you keep the difference.
    """
    spread_multiplier = 1 + (PLATFORM_FX_SPREAD_PERCENTAGE / 100)
    return zmw_per_btc * spread_multiplier

def remove_fx_spread(zmw_per_btc_with_spread: float) -> float:
    """Remove spread to get real market rate (for internal calculations)"""
    spread_multiplier = 1 + (PLATFORM_FX_SPREAD_PERCENTAGE / 100)
    return zmw_per_btc_with_spread / spread_multiplier