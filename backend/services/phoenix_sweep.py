# backend/services/phoenix_sweep.py
"""
ZamPOS Phoenix Sweep Service
────────────────────────────
Sends net merchant payout to owner's Phoenix wallet via Lightning Address.

Owner Lightning Address: fossilbean17@phoenixwallet.me
Flow:
  1. Parse Lightning Address → LNURL-pay endpoint
  2. GET endpoint → fetch callback URL + min/max sendable
  3. GET callback?amount=<msats> → get BOLT11 invoice
  4. Pay invoice via Voltage LND REST send_payment
"""

import httpx
import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)

# ── Owner Phoenix Lightning Address ────────────────────────────────────────────
OWNER_LIGHTNING_ADDRESS = os.getenv(
    "OWNER_LIGHTNING_ADDRESS",
    "fossilbean17@phoenixwallet.me"
)

# Voltage LND credentials (reuse from voltage.py)
NODE_REST_HOST = os.getenv("NODE_REST_HOST", "").strip()
NODE_MACAROON_HEX = os.getenv("NODE_MACAROON_HEX", "").strip()


class SweepResult(TypedDict):
    success: bool
    payment_hash: str
    fee_paid_sats: int
    error: str


def _lnurl_endpoint(lightning_address: str) -> str:
    """
    Convert Lightning Address to LNURL-pay well-known URL.
    e.g. fossilbean17@phoenixwallet.me
      →  https://phoenixwallet.me/.well-known/lnurlp/fossilbean17
    """
    user, domain = lightning_address.split("@")
    return f"https://{domain}/.well-known/lnurlp/{user}"


def _lnd_headers() -> dict:
    return {
        "Grpc-Metadata-macaroon": NODE_MACAROON_HEX,
        "Content-Type": "application/json",
    }


def _get_lnd_base() -> str:
    host = NODE_REST_HOST.rstrip("/")
    if ":" in host.split("/")[-1]:
        return f"https://{host}"
    return f"https://{host}:8080"


async def _resolve_invoice(amount_sats: int, lightning_address: str) -> str:
    """
    Full LNURL-pay flow: Lightning Address → BOLT11 invoice.
    Returns the payment_request string.
    """
    amount_msats = amount_sats * 1000  # LN uses millisatoshis

    endpoint = _lnurl_endpoint(lightning_address)
    logger.info(f"🔍 LNURL fetch: {endpoint}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: GET LNURL-pay metadata
        resp = await client.get(endpoint)
        resp.raise_for_status()
        lnurl_data = resp.json()

        tag = lnurl_data.get("tag")
        if tag != "payRequest":
            raise ValueError(f"Unexpected LNURL tag: {tag!r} (expected 'payRequest')")

        min_sendable = lnurl_data.get("minSendable", 0)   # millisats
        max_sendable = lnurl_data.get("maxSendable", 0)   # millisats
        callback = lnurl_data.get("callback")

        if not callback:
            raise ValueError("LNURL response missing callback URL")

        if not (min_sendable <= amount_msats <= max_sendable):
            raise ValueError(
                f"Amount {amount_sats} sats ({amount_msats} msats) outside "
                f"LNURL range [{min_sendable}–{max_sendable}] msats"
            )

        logger.info(f"✅ LNURL metadata OK | callback={callback}")

        # Step 2: GET invoice from callback
        invoice_resp = await client.get(callback, params={
            "amount": amount_msats,
            "comment": "ZamPOS gas sweep"
        })
        invoice_resp.raise_for_status()
        invoice_data = invoice_resp.json()

        if "status" in invoice_data and invoice_data["status"] == "ERROR":
            raise ValueError(f"LNURL callback error: {invoice_data.get('reason')}")

        payment_request = invoice_data.get("pr")
        if not payment_request:
            raise ValueError(f"No invoice in LNURL callback response: {invoice_data}")

        logger.info(f"⚡ Invoice resolved for {amount_sats} sats → {payment_request[:40]}...")
        return payment_request


async def _pay_invoice_via_lnd(payment_request: str, amount_sats: int) -> dict:
    """
    Pay a BOLT11 invoice via Voltage LND REST API.
    Uses /v2/router/send (streaming) — best for production reliability.
    Falls back to /v1/channels/transactions for simpler nodes.
    """
    base = _get_lnd_base()
    headers = _lnd_headers()

    payload = {
        "payment_request": payment_request,
        "timeout_seconds": 60,
        "fee_limit_sat": max(10, int(amount_sats * 0.01)),  # 1% fee limit, min 10 sats
        "no_inflight_updates": True,
    }

    async with httpx.AsyncClient(timeout=75.0, verify=True) as client:
        # Try v2 router first (preferred)
        try:
            url = f"{base}/v2/router/send"
            logger.info(f"💸 Paying via LND v2 router: {url}")
            resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code == 200:
                # v2/router/send returns newline-delimited JSON (streaming)
                # Each line is a payment update; last line has final status
                lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
                if not lines:
                    raise ValueError("Empty response from v2/router/send")

                import json
                last = json.loads(lines[-1])

                # Unwrap nested result if present
                result = last.get("result", last)
                status = result.get("status", "")

                if status == "SUCCEEDED":
                    return {
                        "success": True,
                        "payment_hash": result.get("payment_hash", ""),
                        "fee_paid_sats": int(result.get("fee_sat", 0)),
                    }
                else:
                    failure = result.get("failure_reason", "UNKNOWN")
                    raise ValueError(f"Payment failed with status={status} reason={failure}")

        except httpx.HTTPStatusError as e:
            if e.response.status_code in [404, 501]:
                logger.warning("⚠️ v2/router/send not available, falling back to v1")
            else:
                raise

        # Fallback: v1 send (synchronous, simpler)
        url = f"{base}/v1/channels/transactions"
        logger.info(f"💸 Paying via LND v1: {url}")

        v1_payload = {
            "payment_request": payment_request,
            "fee_limit": {"fixed": max(10, int(amount_sats * 0.01))},
        }
        resp = await client.post(url, headers=headers, json=v1_payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("payment_error"):
            raise ValueError(f"v1 payment error: {data['payment_error']}")

        return {
            "success": True,
            "payment_hash": data.get("payment_hash", ""),
            "fee_paid_sats": int(data.get("payment_route", {}).get("total_fees", 0)),
        }


async def sweep_to_phoenix(
    amount_sats: int,
    payment_hash: str,
    lightning_address: str | None = None,
) -> SweepResult:
    """
    Main entry point. Resolves invoice from Phoenix Lightning Address
    and pays it via Voltage LND.

    Args:
        amount_sats:        Net sats after gas fee (what merchant receives)
        payment_hash:       Original customer payment hash (for logging)
        lightning_address:  Override owner address (defaults to env/config)

    Returns:
        SweepResult with success, payment_hash, fee_paid_sats, error
    """
    address = lightning_address or OWNER_LIGHTNING_ADDRESS

    logger.info(
        f"🚀 Phoenix sweep | amount={amount_sats} sats "
        f"| to={address} | ref={payment_hash[:12]}..."
    )

    try:
        # Step 1: Resolve BOLT11 invoice from Lightning Address
        invoice = await _resolve_invoice(amount_sats, address)

        # Step 2: Pay via LND
        result = await _pay_invoice_via_lnd(invoice, amount_sats)

        logger.info(
            f"✅ Sweep success | {amount_sats} sats → {address} "
            f"| lnd_fee={result['fee_paid_sats']} sats"
        )
        return SweepResult(
            success=True,
            payment_hash=result["payment_hash"],
            fee_paid_sats=result["fee_paid_sats"],
            error=""
        )

    except Exception as e:
        logger.error(
            f"❌ Phoenix sweep failed | amount={amount_sats} ref={payment_hash[:12]}...: {e}",
            exc_info=True
        )
        return SweepResult(
            success=False,
            payment_hash="",
            fee_paid_sats=0,
            error=str(e)
        )