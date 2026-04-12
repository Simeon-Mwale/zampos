from fastapi import APIRouter, Query
from database import get_transactions, get_daily_totals, get_summary

router = APIRouter()


@router.get("/")
async def list_transactions(limit: int = Query(default=50, le=200)):
    """Get recent transactions."""
    return get_transactions(limit)


@router.get("/summary")
async def summary():
    """Get today's totals and all-time totals."""
    return get_summary()


@router.get("/daily")
async def daily_totals(days: int = Query(default=7, le=30)):
    """Get daily totals for the past N days."""
    return get_daily_totals(days)
