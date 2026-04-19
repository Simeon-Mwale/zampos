# backend/webhooks.py — ZamPOS v2
# Voltage webhook handler REMOVED (Voltage node no longer used).
# Payment detection is now handled by:
#   1. Frontend polling /status/{payment_hash} every 3 seconds
#   2. POST /webhook/payment endpoint in router.py for wallets that support callbacks
#
# This file is kept as a placeholder to avoid import errors from any lingering references.
# Safe to delete once you've confirmed router.py is the only webhook entry point.

import logging
logger = logging.getLogger(__name__)

async def handle_voltage_webhook(*args, **kwargs):
    logger.warning("handle_voltage_webhook called but Voltage is no longer in use (ZamPOS v2)")
    return False