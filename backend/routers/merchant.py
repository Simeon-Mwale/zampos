from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from database import save_merchant, get_merchant_by_id, get_available_wallet_from_pool, mark_wallet_assigned
import re

router = APIRouter()


# ------------------------
# REQUEST/RESPONSE MODELS
# ------------------------

class MerchantRegisterRequest(BaseModel):
    shop_name: str = Field(..., min_length=2, max_length=100, description="Shop or business name")
    location: str | None = Field(None, max_length=200, description="Optional: Market/location")
    
    class Config:
        json_schema_extra = {
            "example": {
                "shop_name": "Mama Ntemba's Groundnuts",
                "location": "Lusaka, Soweto Market"
            }
        }


class MerchantRegisterResponse(BaseModel):
    merchant_id: int
    shop_name: str
    location: str | None
    invoice_key: str
    wallet_id: str
    created_at: str


# ------------------------
# REGISTER MERCHANT (WALLET POOL — NO EXTERNAL API CALLS)
# ------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=MerchantRegisterResponse)
async def register_merchant(req: MerchantRegisterRequest):
    """
    Register a new merchant using pre-created wallet pool.
    
    ✅ No LNBits API calls during registration → faster, more reliable for offline markets.
    """
    
    # Sanitize shop name
    clean_name = re.sub(r"[^a-zA-Z0-9\s'\-]", "", req.shop_name).strip()
    if len(clean_name) < 2:
        raise HTTPException(status_code=400, detail="Shop name must be at least 2 characters")
    
    try:
        # 🔥 Get available wallet from pool (NO external API call)
        wallet = get_available_wallet_from_pool()
        
        # 💾 Save merchant to local DB
        merchant_id = save_merchant(
            name=clean_name,
            wallet_id=wallet["id"],
            admin_key=wallet["adminkey"],  # Stored securely, never returned
            invoice_key=wallet["inkey"],    # Returned to frontend for invoice creation
            location=req.location
        )
        
        # 🔒 Mark wallet as assigned in pool
        mark_wallet_assigned(wallet["inkey"], merchant_id)
        
        # 📦 Return safe response
        merchant = get_merchant_by_id(merchant_id)
        
        return MerchantRegisterResponse(
            merchant_id=merchant["id"],
            shop_name=merchant["name"],
            location=merchant.get("location"),
            invoice_key=merchant["invoice_key"],
            wallet_id=merchant["wallet_id"],
            created_at=merchant["created_at"]
        )
        
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"❌ Merchant registration failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to register merchant. Please try again.")


# ------------------------
# GET MERCHANT (Helper)
# ------------------------

@router.get("/{merchant_id}")
async def get_merchant(merchant_id: int):
    """Get merchant details by ID"""
    merchant = get_merchant_by_id(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    return {
        "merchant_id": merchant["id"],
        "shop_name": merchant["name"],
        "location": merchant.get("location"),
        "created_at": merchant["created_at"]
    }