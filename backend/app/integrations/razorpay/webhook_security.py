"""
Razorpay webhook signature verification.

Razorpay signs webhook payloads with HMAC-SHA256 over the raw request
body, using the webhook secret configured in the Razorpay dashboard, and
sends the resulting hex digest in the `X-Razorpay-Signature` header. This
is Razorpay's documented verification method - never invented here.

A webhook is trusted ONLY if this check passes. An unsigned or
incorrectly-signed request is always rejected, regardless of what its
body claims.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_webhook_signature(raw_body: bytes, signature_header: str | None, webhook_secret: str) -> bool:
    """Returns True only if `signature_header` is a valid HMAC-SHA256 of
    `raw_body` using `webhook_secret`. Constant-time comparison to avoid
    timing attacks, per standard HMAC verification practice."""
    if not signature_header or not webhook_secret:
        return False

    expected = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
