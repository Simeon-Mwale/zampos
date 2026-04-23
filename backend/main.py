# backend/main.py — ZamPOS v2
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os, logging, asyncio

from database import init_db
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
    logger.info("🚀 ZamPOS v2 starting...")
    logger.info(f"   Spread:  {os.getenv('ZAMPOS_SPREAD_PCT', '0.5')}%")
    logger.info(f"   SMS:     Africa's Talking ({os.getenv('AFRICASTALKING_USERNAME', 'sandbox')})")
    logger.info(f"   DB:      {os.getenv('DATABASE_PATH', './data/zampos.db')}")

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

    logger.info("🛑 ZamPOS v2 shutting down")


# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="ZamPOS API v2",
    description=(
        "Lightning POS for Zambian merchants. "
        "Invoices generated from each merchant's own Lightning Address. "
        "Customer pays merchant directly. "
        "SMS confirmation via Africa's Talking."
    ),
    version="2.0.0",
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
# HEALTH
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
        "version": "2.0.0",
        "model": "direct-lightning-address + custodial",
        "spread": f"{os.getenv('ZAMPOS_SPREAD_PCT', '0.5')}%",
        "sms": os.getenv("AFRICASTALKING_USERNAME", "not configured"),
        "breez": breez_status,
        "breez_balance_sats": breez_balance,
    }


@app.get("/")
async def root():
    return {"message": "ZamPOS v2 API — visit /docs"}


# ─────────────────────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────────────────────

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Endpoint not found"})


@app.exception_handler(500)
async def server_error(request: Request, exc):
    logger.error(f"❌ 500: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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