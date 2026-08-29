"""
POST /api/recovery/{transaction_id} and GET /api/recovery/{transaction_id}.

POST is the only endpoint in this project that can trigger money-adjacent
(simulated) behavior. It accepts NOTHING from the client that could
influence the outcome - no recovered_amount, no rules_decision, no
execution_status, not even a requested action. The client can only ask
"run the recovery workflow for this transaction"; every value in the
response is computed by the backend (Phases 2-5) and persisted before
being returned.

Flow (exactly the Phase 5 pipeline, now with persistence):
1. Load payment + customer history from the database
2. Build the feature dict Phases 2-5 expect
3. Call recover_transaction() (ML -> agent -> rules -> execution)
4. Persist the recovery attempt and every audit event
5. Return the complete structured result

Idempotency is enforced at this layer using the database: if a payment
already has a recovery attempt, POST returns that existing result rather
than executing again.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.providers import get_default_provider
from app.api.schemas import AuditEventOut, RecoveryWorkflowResponse
from app.db import repository
from app.db.models import Payment
from app.db.repository import DuplicateRecoveryAttemptError
from app.db.session import get_db
from app.execution.factory import get_executor
from app.execution.service import recover_transaction
from app.integrations.razorpay.executor import RazorpayConfigurationError
from app.ml.predict import predict_recovery
from app.rules.policies import get_active_policy

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _build_feature_payload(payment: Payment) -> dict:
    customer = payment.customer
    return {
        "transaction_id": payment.transaction_id,
        "amount": payment.amount,
        "payment_method": payment.payment_method,
        "failure_reason": payment.failure_reason,
        "retry_count": 0,  # first automated attempt for this payment in this MVP
        "previous_transactions": customer.previous_transactions if customer else 0,
        "previous_success_rate": customer.previous_success_rate if customer else 0.5,
        "subscription_status": customer.subscription_status if customer else "none",
        "customer_type": customer.customer_type if customer else "new",
        # Real per-payment values when the seed/caller provided them;
        # fall back to neutral defaults for older rows that predate these
        # columns, so nothing existing breaks.
        "days_since_failure": payment.days_since_failure if payment.days_since_failure is not None else 0,
        "time_since_last_success": (
            payment.time_since_last_success if payment.time_since_last_success is not None else 720.0
        ),
        "device_risk_score": payment.device_risk_score if payment.device_risk_score is not None else 0.3,
        "historical_failure_count": customer.historical_failure_count if customer else 0,
        "simulation_outcome": payment.simulation_outcome,
    }


def _to_response(
    transaction_id: str,
    recovery_probability: float | None,
    result,
    idempotent_replay: bool,
) -> RecoveryWorkflowResponse:
    return RecoveryWorkflowResponse(
        transaction_id=transaction_id,
        idempotent_replay=idempotent_replay,
        recovery_probability=recovery_probability,
        agent_requested_action=result.agent.requested_action,
        agent_confidence=result.agent.confidence,
        agent_explanation=result.agent.explanation,
        agent_reason_codes=result.agent.reason_codes,
        agent_provider=result.agent.provider,
        agent_is_mock=result.agent.is_mock,
        rules_decision=result.safety.decision,
        rules_reason_codes=result.safety.reason_codes,
        rules_explanation=result.safety.explanation,
        requires_human_approval=result.safety.requires_human_approval,
        execution_status=result.recovery_attempt.execution_status,
        recovered_amount=result.recovery_attempt.recovered_amount,
        failure_reason=result.recovery_attempt.failure_reason,
        simulation_mode=result.recovery_attempt.simulation_mode,
        execution_mode=result.recovery_attempt.execution_mode,
        razorpay_payment_link_id=result.recovery_attempt.razorpay_payment_link_id,
        razorpay_payment_link_url=result.recovery_attempt.razorpay_payment_link_url,
        razorpay_reference_id=result.recovery_attempt.razorpay_reference_id,
        audit_events=[
            AuditEventOut(
                timestamp=e.timestamp,
                event_type=e.event_type,
                transaction_id=e.transaction_id,
                requested_action=e.requested_action,
                rules_decision=e.rules_decision,
                execution_status=e.execution_status,
                reason_codes=e.reason_codes,
                explanation=e.explanation,
            )
            for e in result.audit_events
        ],
    )


def _replay_response_from_attempt(
    db: Session, transaction_id: str, attempt
) -> RecoveryWorkflowResponse:
    """Builds a RecoveryWorkflowResponse from an already-persisted
    RecoveryAttempt row plus its audit trail. Used for every path that
    returns an existing result rather than a freshly-computed one: the
    pre-check idempotent-replay branch, the post-conflict race-recovery
    branch (see trigger_recovery), and GET. Pulled out to one place so
    those three call sites can't silently drift from each other."""
    audit_rows = repository.list_audit_events(db, transaction_id=transaction_id)
    events = [
        AuditEventOut(
            timestamp=_iso(row.timestamp),
            event_type=row.event_type,
            transaction_id=txn_id,
            requested_action=row.requested_action,
            rules_decision=row.rules_decision,
            execution_status=row.execution_status,
            reason_codes=json.loads(row.reason_codes) if row.reason_codes else [],
            explanation=row.explanation or row.event_detail,
        )
        for row, txn_id in reversed(audit_rows)
    ]

    return RecoveryWorkflowResponse(
        transaction_id=transaction_id,
        idempotent_replay=True,
        recovery_probability=attempt.ml_probability,
        agent_requested_action=attempt.agent_action or "",
        agent_confidence=attempt.agent_confidence or 0.0,
        agent_explanation=attempt.agent_reason or "",
        agent_reason_codes=[],
        agent_provider="",
        agent_is_mock=True,
        rules_decision=attempt.rules_decision or "",
        rules_reason_codes=[],
        rules_explanation="",
        requires_human_approval=attempt.rules_decision == "HUMAN_APPROVAL",
        execution_status=attempt.execution_status or "",
        recovered_amount=attempt.recovered_amount or 0.0,
        failure_reason=attempt.failure_reason,
        simulation_mode=bool(attempt.simulation_mode),
        execution_mode=attempt.execution_mode or "SIMULATION",
        razorpay_payment_link_id=attempt.razorpay_payment_link_id,
        razorpay_payment_link_url=attempt.razorpay_payment_link_url,
        razorpay_reference_id=attempt.razorpay_reference_id,
        audit_events=events,
    )


@router.post("/{transaction_id}", response_model=RecoveryWorkflowResponse)
def trigger_recovery(transaction_id: str, db: Session = Depends(get_db)) -> RecoveryWorkflowResponse:
    payment = repository.get_payment_by_transaction_id(db, transaction_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    existing_attempt = repository.get_latest_attempt(db, payment)
    if existing_attempt is not None:
        # Idempotent: return the persisted result rather than re-executing.
        return _replay_response_from_attempt(db, transaction_id, existing_attempt)

    feature_payload = _build_feature_payload(payment)

    try:
        recovery_probability = predict_recovery(feature_payload)["recovery_probability"]
    except Exception:
        recovery_probability = None

    payload_with_probability = dict(feature_payload)
    payload_with_probability["recovery_probability"] = recovery_probability

    try:
        active_executor = get_executor()
    except RazorpayConfigurationError as exc:
        # Fail closed with a clear, secret-free configuration error rather
        # than a raw 500 - never silently fall back to a different
        # executor than what was actually configured.
        raise HTTPException(status_code=503, detail=str(exc)) from None

    result = recover_transaction(
        payload_with_probability,
        provider=get_default_provider(),
        policy=get_active_policy(),
        executor=active_executor,  # simulation by default; razorpay_test if configured (Phase 7)
        idempotency_store={},  # DB-level idempotency (above and below) is authoritative for this API
    )

    try:
        repository.persist_recovery_result(
            db, payment, result, retry_count=feature_payload["retry_count"], ml_probability=recovery_probability
        )
        db.commit()
    except DuplicateRecoveryAttemptError:
        # Lost the race: a concurrent request for this same transaction
        # already inserted its attempt between our pre-check above and
        # our own insert just now. persist_recovery_result() already
        # rolled back our half-written attempt (and its audit events) -
        # fetch and return the winning request's result instead of
        # exposing the conflict or silently creating a duplicate.
        winning_attempt = repository.get_latest_attempt(db, payment)
        return _replay_response_from_attempt(db, transaction_id, winning_attempt)

    return _to_response(transaction_id, recovery_probability, result, idempotent_replay=False)


@router.get("/{transaction_id}", response_model=RecoveryWorkflowResponse)
def get_recovery_result(transaction_id: str, db: Session = Depends(get_db)) -> RecoveryWorkflowResponse:
    payment = repository.get_payment_by_transaction_id(db, transaction_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    attempt = repository.get_latest_attempt(db, payment)
    if attempt is None:
        raise HTTPException(status_code=404, detail="No recovery attempt has been run for this transaction yet")

    return _replay_response_from_attempt(db, transaction_id, attempt)
