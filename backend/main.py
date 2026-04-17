# backend/main.py — Updated startup logging
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import logging
from database import init_db
from router import router

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup/shutdown"""
    logger.info("🚀 Starting ZamPOS backend...")
    await init_db()
    logger.info("✅ Database ready")
    
    try:
        # Warm up rate cache on startup (non-blocking)
        from services.rate_service import fetch_live_rates
        import asyncio
        asyncio.create_task(fetch_live_rates())
        logger.info("💱 Rate cache warming initiated (ZMW→USD→BTC flow)")
    except Exception as e:
        logger.warning(f"⚠️ Could not warm rate cache: {e}")
    
    yield
    
    logger.info("🛑 Shutting down ZamPOS backend...")

app = FastAPI(
    title="ZamPOS API",
    description="Lightning POS backend for Zambian merchants (ZMW→USD→BTC→sats)",
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ No prefix — routes match exactly what the frontend calls
app.include_router(router, prefix="", tags=["zampos"])

# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "network": os.getenv("VOLTAGE_NETWORK", "mutinynet"),
        "version": "1.1.0",
        "rate_flow": "ZMW→USD→BTC→sats"
    }

@app.get("/")
async def root():
    return {"message": "ZamPOS API running. Visit /docs for documentation."}

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Endpoint not found"})

@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    logger.error(f"❌ Internal server error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENVIRONMENT") != "production",
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )