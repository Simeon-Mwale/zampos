# backend/services/lnurl_static.py
# Generates and serves static LNURL-pay endpoints per merchant.
#
# Flow:
#   1. Vendor's static QR encodes:  lightning:LNURL1... (bech32 of the step-1 URL)
#   2. Customer wallet GETs:        GET /merchant/<id>/lnurl
#      → returns LNURL-pay metadata (min/max sats, description)
#   3. Wallet GETs callback:        GET /merchant/<id>/lnurl/callback?amount=<msats>
#      → fetches bolt11 from merchant's Lightning Address (direct mode)
#      → OR creates custodial invoice via operator wallet (custodial mode)
#      → returns { pr: <bolt11>, routes: [] }
#
# Direct-mode: ZamPOS is only a routing layer. Zero custody.

import hashlib
import os
import json
import logging
from bech32 import bech32_encode, convertbits

logger = logging.getLogger(__name__)

BASE_URL        = os.getenv("ZAMPOS_BASE_URL", "https://zampos.onrender.com").rstrip("/")
GLOBAL_MIN_SATS = int(os.getenv("LNURL_MIN_SATS", "1"))
GLOBAL_MAX_SATS = int(os.getenv("LNURL_MAX_SATS", "100000"))


def encode_lnurl(url: str) -> str:
    """
    Encode a plain HTTPS URL to the bech32 LNURL1... format.
    Wallets scan this, decode it, then GET the URL.
    Returns uppercase e.g. LNURL1DP68GURN8GHJ...
    """
    data_bytes = url.encode("utf-8")
    converted  = convertbits(data_bytes, 8, 5)
    if converted is None:
        raise ValueError(f"bech32 convertbits failed for: {url}")
    encoded = bech32_encode("lnurl", converted)
    if encoded is None:
        raise ValueError(f"bech32_encode returned None for: {url}")
    return encoded.upper()


def get_lnurlp_url(merchant_id: int) -> str:
    """Plain HTTPS URL wallets GET for LNURL-pay metadata (Step 1)."""
    return f"{BASE_URL}/merchant/{merchant_id}/lnurl"


def get_lnurl_encoded(merchant_id: int) -> str:
    """bech32-encoded LNURL1... string. This is what gets put in the QR."""
    return encode_lnurl(get_lnurlp_url(merchant_id))


def get_qr_value(merchant_id: int) -> str:
    """
    Full string to embed in the QR code.
    Prefixed with 'lightning:' so wallets open automatically on scan.
    """
    return f"lightning:{get_lnurl_encoded(merchant_id)}"


def build_lnurlp_metadata(shop_name: str, location: str | None = None) -> str:
    """
    LNURL-pay metadata JSON array.
    Spec requires at minimum a [['text/plain', '...']] entry.
    """
    description = f"Pay {shop_name}"
    if location:
        description += f" · {location}"
    description += " via ZamPOS ⚡"
    return json.dumps([["text/plain", description]])


def build_lnurlp_response(merchant_id: int, shop_name: str, location: str | None = None) -> dict:
    """
    Step 1 response body.
    Wallet GETs /merchant/<id>/lnurl and receives this.
    Tells the wallet: min/max amounts, description, and where to call back.
    """
    metadata = build_lnurlp_metadata(shop_name, location)

    return {
        "tag":            "payRequest",
        "callback":       f"{BASE_URL}/merchant/{merchant_id}/lnurl/callback",
        "minSendable":    GLOBAL_MIN_SATS * 1000,   # in msats
        "maxSendable":    GLOBAL_MAX_SATS * 1000,   # in msats
        "metadata":       metadata,
        "commentAllowed": 64,
    }