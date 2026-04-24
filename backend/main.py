# backend/main.py — ZamPOS v2.1 (Production Hardened with Duplicate Prevention)
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os, logging, asyncio
from typing import Optional

from database import init_db, check_duplicate_merchant, get_merchant_by_phone
from router import router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ZamPOS v2.1 starting...")
    logger.info(f"   Spread:  {os.getenv('ZAMPOS_SPREAD_PCT', '0.5')}%")
    logger.info(f"   SMS:     Africa's Talking ({os.getenv('AFRICASTALKING_USERNAME', 'sandbox')})")
    logger.info(f"   DB:      {os.getenv('DATABASE_PATH', './data/zampos.db')}")
    logger.info(f"   Duplicate Prevention: ENABLED (unique phone & shop name)")

    await init_db()
    logger.info("✅ Database ready")

    # Initialize Breez for auto-withdrawals
    try:
        from services.breez_service import init_breez
        breez_ok = await init_breez()
        if breez_ok:
            logger.info("⚡ Breez SDK ready for withdrawals")
        else:
            logger.warning("⚠️ Breez SDK not available (withdrawals will need manual processing)")
    except Exception as e:
        logger.warning(f"⚠️ Breez init failed: {e}")

    # Start rate cache warming
    try:
        from services.rate_service import fetch_live_rates
        asyncio.create_task(fetch_live_rates(force_refresh=True))
        logger.info("💱 Rate cache warming started")
    except Exception as e:
        logger.warning(f"⚠️ Rate warmup failed: {e}")

    yield

    # Cleanup Breez on shutdown
    try:
        from services.breez_service import close_breez
        await close_breez()
        logger.info("🔌 Breez SDK closed")
    except Exception as e:
        logger.warning(f"⚠️ Breez close failed: {e}")

    logger.info("🛑 ZamPOS v2.1 shutting down")


# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="ZamPOS API v2",
    description=(
        "Lightning POS for Zambian merchants. "
        "Invoices generated from each merchant's own Lightning Address. "
        "Customer pays merchant directly. "
        "SMS confirmation via Africa's Talking. "
        "Duplicate prevention: unique phone numbers and shop names enforced."
    ),
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ─────────────────────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────────────────────

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow ngrok + everything for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

app.include_router(router, prefix="", tags=["zampos"])


# ─────────────────────────────────────────────────────────────
# DUPLICATE CHECK ENDPOINT (New)
# ─────────────────────────────────────────────────────────────

@app.get("/merchant/check-duplicate")
async def api_check_duplicate_merchant(
    phone_number: Optional[str] = None,
    shop_name: Optional[str] = None
):
    """
    Check if a merchant already exists with the given phone number or shop name.
    Useful for real-time validation during registration.
    
    Returns:
        {
            "exists": true/false,
            "merchant_id": id if exists,
            "shop_name": name if exists,
            "phone_number": phone if exists,
            "message": description
        }
    """
    if not phone_number and not shop_name:
        return {
            "exists": False,
            "message": "No criteria provided. Provide phone_number or shop_name."
        }
    
    duplicate = await check_duplicate_merchant(phone_number, shop_name)
    
    if duplicate:
        return {
            "exists": True,
            "merchant_id": duplicate["id"],
            "shop_name": duplicate["shop_name"],
            "phone_number": duplicate["phone_number"],
            "message": f"Merchant already exists: {duplicate['shop_name']} ({duplicate['phone_number']})"
        }
    
    return {
        "exists": False,
        "message": "No existing merchant found with provided criteria."
    }


# ─────────────────────────────────────────────────────────────
# HEALTH (Updated with duplicate prevention status)
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    # Check Breez status
    breez_status = "not configured"
    breez_balance = None
    try:
        from services.breez_service import get_breez_balance
        balance = await get_breez_balance()
        if balance >= 0:
            breez_status = "online"
            breez_balance = balance
        else:
            breez_status = "offline"
    except:
        pass
    
    return {
        "status": "healthy",
        "version": "2.1.0",
        "model": "direct-lightning-address + custodial",
        "spread": f"{os.getenv('ZAMPOS_SPREAD_PCT', '0.5')}%",
        "sms": os.getenv("AFRICASTALKING_USERNAME", "not configured"),
        "breez": breez_status,
        "breez_balance_sats": breez_balance,
        "duplicate_prevention": "enabled (unique phone & shop name)",
    }


@app.get("/")
async def root():
    return {
        "message": "ZamPOS v2.1 API — visit /docs",
        "duplicate_check": "Use GET /merchant/check-duplicate?phone_number=xxx&shop_name=xxx"
    }


# ─────────────────────────────────────────────────────────────
# ERROR HANDLERS (Enhanced for duplicate errors)
# ─────────────────────────────────────────────────────────────

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Endpoint not found"})


@app.exception_handler(500)
async def server_error(request: Request, exc):
    logger.error(f"❌ 500: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Handle duplicate key errors gracefully
    if exc.status_code == 409:
        return JSONResponse(
            status_code=409,
            content={
                "detail": exc.detail,
                "error_type": "duplicate_merchant",
                "resolution": "Please use a different phone number or shop name"
            }
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# ─────────────────────────────────────────────────────────────
# ENTRYWPOINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENVIRONMENT") != "production",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )