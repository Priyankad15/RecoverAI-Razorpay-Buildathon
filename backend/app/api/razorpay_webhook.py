"""
POST /api/integrations/razorpay/webhook

Confirms a Razorpay Test Mode Payment Link payment result. This is the
ONLY path in the codebase that can set execution_status to SUCCESS for a
Razorpay-executed recovery and populate recovered_amount - Payment Link
*creation* never does (see app.integrations.razorpay.executor).

SECURITY: every request is verified against the documented Razorpay
webhook signature scheme (HMAC-SHA256 of the raw body using the
configured webhook secret - see app.integrations.razorpay.webhook_security)
before its payload is trusted for anything. An unsigned or
incorrectly-signed request is rejected outright; the payload's own claims
(e.g. "status": "paid") are never taken at face value without a valid
signature. A frontend-provided `payment_success=true` is never accepted
anywhere in this codebase - only this verified webhook path (or the
payment-link status-fetch API, not yet wired to an endpoint) can confirm
a payment.

EVENT NAMES: this handler dispatches on Razorpay's documented Payment
Links webhook events. `payment_link.paid` is treated as a confirmed
success; `payment_link.cancelled` / `payment_link.expired` are treated as
a failed recovery attempt. Any other event is acknowledged (200) but not
acted on. Verify exact event names against Razorpay's current webhook
documentation before relying on this in production - this environment
had no network access to Razorpay's live docs during implementation; see
docs/razorpay-test-mode.md for this caveat in full.

IDEMPOTENT: if the matched attempt has already been marked SUCCESS, the
webhook is a no-op - it never double-counts recovered revenue on a
duplicate delivery (Razorpay, like most webhook senders, may redeliver
the same event).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditLog, RecoveryAttempt
from app.db.session import get_db
from app.execution.enums import ExecutionStatus
from app.integrations.razorpay.webhook_security import verify_webhook_signature

router = APIRouter(prefix="/api/integrations/razorpay", tags=["razorpay"])

SUCCESS_EVENTS = {"payment_link.paid"}
FAILURE_EVENTS = {"payment_link.cancelled", "payment_link.expired"}


@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    raw_body = await request.body()

    if not verify_webhook_signature(raw_body, x_razorpay_signature, settings.razorpay_webhook_secret):
        # Never process an unsigned/incorrectly-signed payload, regardless
        # of what it claims. No details about *why* it failed are
        # returned, to avoid helping an attacker iterate toward a valid
        # signature.
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed webhook payload") from None

    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
    reference_id = entity.get("reference_id")
    paid_amount_paise = entity.get("amount_paid")

    if not reference_id:
        # Nothing we can match to a transaction - acknowledge (so
        # Razorpay doesn't retry forever) but do nothing.
        return {"status": "ignored", "reason": "no reference_id in payload"}

    attempt = db.execute(
        select(RecoveryAttempt).where(RecoveryAttempt.razorpay_reference_id == reference_id)
    ).scalar_one_or_none()

    if attempt is None:
        return {"status": "ignored", "reason": "no matching transaction for reference_id"}

    if attempt.execution_status == ExecutionStatus.SUCCESS.value:
        # Already confirmed - idempotent no-op, never double-count.
        return {"status": "ignored", "reason": "already confirmed"}

    if event in SUCCESS_EVENTS:
        payment = attempt.payment
        if paid_amount_paise is not None:
            recovered_amount = float(paid_amount_paise) / 100.0
        else:
            # Documented payloads include amount_paid; this is a
            # defensive fallback only, using the transaction's own
            # recorded amount rather than inventing a number.
            recovered_amount = payment.amount if payment else 0.0

        attempt.execution_status = ExecutionStatus.SUCCESS.value
        attempt.recovered_amount = recovered_amount
        attempt.completed_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                payment_id=attempt.payment_id,
                event_type="RAZORPAY_PAYMENT_CONFIRMED",
                event_detail=f"Razorpay Test Mode payment confirmed via webhook ({event}).",
                actor="razorpay_webhook",
                requested_action=attempt.agent_action,
                rules_decision=attempt.rules_decision,
                execution_status=ExecutionStatus.SUCCESS.value,
                reason_codes=json.dumps([]),
                explanation=(
                    f"[RAZORPAY TEST MODE] Payment confirmed via verified webhook. "
                    f"Recovered amount: {recovered_amount}."
                ),
                simulation_mode=False,
                timestamp=datetime.now(timezone.utc),
            )
        )
        db.commit()
        return {"status": "confirmed", "recovered_amount": recovered_amount}

    if event in FAILURE_EVENTS:
        attempt.execution_status = ExecutionStatus.FAILED.value
        attempt.recovered_amount = 0.0
        attempt.failure_reason = f"razorpay_{event.split('.')[-1]}"
        attempt.completed_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                payment_id=attempt.payment_id,
                event_type="RAZORPAY_PAYMENT_FAILED",
                event_detail=f"Razorpay Test Mode payment link {event.split('.')[-1]} (webhook: {event}).",
                actor="razorpay_webhook",
                requested_action=attempt.agent_action,
                rules_decision=attempt.rules_decision,
                execution_status=ExecutionStatus.FAILED.value,
                reason_codes=json.dumps([]),
                explanation=f"[RAZORPAY TEST MODE] Payment not completed ({event}). No revenue recovered.",
                simulation_mode=False,
                timestamp=datetime.now(timezone.utc),
            )
        )
        db.commit()
        return {"status": "failed", "recovered_amount": 0.0}

    return {"status": "ignored", "reason": f"unhandled event type: {event}"}
