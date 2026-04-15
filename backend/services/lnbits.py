# backend/services/lnbits.py
import httpx
import os
import uuid
import re
from dotenv import load_dotenv

load_dotenv()


# ------------------------
# CONFIG HELPERS
# ------------------------

def _get_url() -> str:
    return os.getenv("LNBITS_URL", "http://localhost:5000").rstrip("/")

def _get_invoice_key() -> str:
    key = os.getenv("LNBITS_INVOICE_KEY", "")
    if not key:
        raise RuntimeError("LNBITS_INVOICE_KEY not set in .env")
    return key

def _get_admin_key() -> str:
    key = os.getenv("LNBITS_ADMIN_KEY", "")
    if not key:
        raise RuntimeError("LNBITS_ADMIN_KEY not set in .env")
    return key


def _admin_headers() -> dict:
    return {
        "X-Api-Key": _get_admin_key(),
        "Content-Type": "application/json",
    }

def _invoice_headers(wallet_key: str | None = None) -> dict:
    return {
        "X-Api-Key": wallet_key if wallet_key else _get_invoice_key(),
        "Content-Type": "application/json",
    }


# ------------------------
# INVOICE CREATION
# ------------------------

async def create_invoice(
    amount_sats: int,
    memo: str,
    wallet_key: str | None = None,
    webhook_url: str | None = None
) -> dict:
    """Create Lightning invoice using merchant wallet or default"""
    base_url = _get_url()
    
    payload = {
        "out": False,
        "amount": amount_sats,
        "memo": memo,
        "unit": "sat",
    }
    if webhook_url:
        payload["webhook"] = webhook_url

    url = f"{base_url}/api/v1/payments"
    headers = _invoice_headers(wallet_key)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            print(f"[LNbits] Invoice error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()


# ------------------------
# CHECK PAYMENT STATUS
# ------------------------

async def check_payment(payment_hash: str) -> dict:
    """Check if a Lightning payment has been paid"""
    base_url = _get_url()
    url = f"{base_url}/api/v1/payments/{payment_hash}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=_invoice_headers())
        resp.raise_for_status()
        data = resp.json()
        return {
            "paid": data.get("paid", False),
            "details": data,
        }


# ------------------------
# CREATE MERCHANT WALLET (SINGLE-CALL USER+WALLET)
# ------------------------

async def create_wallet(name: str) -> dict:
    """
    Create a new LNBits wallet for a merchant using UserManager.
    
    Single-call flow (for LNBits versions that combine user+wallet creation):
    POST /usermanager/api/v1/wallets with BOTH user_name AND wallet_name
    """
    base_url = _get_url()
    admin_key = _get_admin_key()
    
    if not admin_key:
        raise RuntimeError("LNBITS_ADMIN_KEY not set in .env")
    
    # Sanitize name for username/email/wallet (alphanumeric + underscore only)
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', name.strip())[:30]
    if not safe_name:
        safe_name = f"merchant_{uuid.uuid4().hex[:8]}"
    
    temp_password = uuid.uuid4().hex[:16]
    temp_email = f"{safe_name.lower()}@zampos.local"
    wallet_name = f"{safe_name}_wallet"
    
    headers = _admin_headers()
    url = f"{base_url}/usermanager/api/v1/wallets"
    
    # 🔹 Payload formats to try (your version needs user_name + wallet_name together)
    payload_formats = [
        # Format 1: Full payload (most likely for your version)
        {
            "user_name": safe_name,
            "wallet_name": wallet_name,
            "admin": False,
            "email": temp_email,
            "password": temp_password
        },
        # Format 2: Without admin field
        {
            "user_name": safe_name,
            "wallet_name": wallet_name,
            "email": temp_email,
            "password": temp_password
        },
        # Format 3: Minimal (some versions auto-generate)
        {
            "user_name": safe_name,
            "wallet_name": wallet_name
        },
        # Format 4: With string "false" for admin
        {
            "user_name": safe_name,
            "wallet_name": wallet_name,
            "admin": "false",
            "email": temp_email,
            "password": temp_password
        }
    ]
    
    async with httpx.AsyncClient(timeout=30) as client:
        
        # 🔁 Try each payload format until one works
        for i, payload in enumerate(payload_formats, 1):
            print(f"[LNbits] Trying wallet format #{i}: user='{safe_name}', wallet='{wallet_name}'")
            
            try:
                resp = await client.post(url, headers=headers, json=payload)
                
                # Log response for debugging
                if resp.status_code >= 400:
                    print(f"[LNbits] Format #{i} failed ({resp.status_code}): {resp.text}")
                
                # Success!
                if resp.status_code in (200, 201):
                    data = resp.json()
                    print(f"[LNbits] ✓ Wallet created with format #{i}")
                    
                    # 🔁 Normalize response keys
                    wallet_id = (
                        data.get("id") or 
                        data.get("wallet_id") or 
                        (data.get("wallet") or {}).get("id")
                    )
                    adminkey = (
                        data.get("adminkey") or 
                        data.get("admin_key") or 
                        (data.get("wallet") or {}).get("adminkey")
                    )
                    inkey = (
                        data.get("inkey") or 
                        data.get("invoice_key") or 
                        (data.get("wallet") or {}).get("inkey")
                    )
                    
                    return {
                        "id": wallet_id or "unknown",
                        "adminkey": adminkey or "",
                        "inkey": inkey or "",
                        "name": name,
                        "user_id": data.get("user")  # Optional: store for audit
                    }
                
                # 409 = already exists (try different name)
                if resp.status_code == 409:
                    safe_name = f"{safe_name}_{uuid.uuid4().hex[:4]}"
                    wallet_name = f"{safe_name}_wallet"
                    continue
                    
            except Exception as e:
                print(f"[LNbits] Format #{i} exception: {e}")
                continue
        
        # If no format worked
        raise RuntimeError(
            "Failed to create UserManager wallet. Try these fixes:\n"
            "1. Check LNBits logs: docker logs lnbits --tail 50\n"
            "2. Verify UserManager extension is enabled at /extensions\n"
            "3. Try the curl command below manually to see exact error\n"
            "4. Ensure LNBITS_ADMIN_KEY has UserManager permissions"
        )