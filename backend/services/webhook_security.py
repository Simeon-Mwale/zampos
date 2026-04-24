import hmac
import hashlib
import os

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me")

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)