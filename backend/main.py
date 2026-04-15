from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

load_dotenv()

from routers import invoice, price, webhook, transactions, sweep, merchant
from database import init_db


# ------------------------
# APP LIFECYCLE
# ------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 ZamPOS backend starting...")
    init_db()
    yield
    print("🛑 ZamPOS backend shutting down...")


# ------------------------
# FASTAPI INIT
# ------------------------

app = FastAPI(
    title="ZamPOS API",
    description="Bitcoin Lightning POS backend for Zambian informal markets",
    version="0.1.0",
    lifespan=lifespan,
)


# ------------------------
# CORS
# ------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------
# ROUTES
# ------------------------

app.include_router(price.router,        prefix="/price",        tags=["Price"])
app.include_router(invoice.router,      prefix="/invoice",      tags=["Invoice"])
app.include_router(webhook.router,      prefix="/webhook",      tags=["Webhook"])
app.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
app.include_router(sweep.router,        prefix="/sweep",        tags=["Sweep"])
app.include_router(merchant.router,     prefix="/merchant",     tags=["Merchant"])


# ------------------------
# HEALTH
# ------------------------

@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": "ZamPOS",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}