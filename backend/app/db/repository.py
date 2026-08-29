"""
Persistence layer connecting Phase 5's execution results to the Phase 1
database. This is the ONLY module that writes RecoveryTransactionResult
data to the database - API routes call these functions rather than
touching SQLAlchemy models directly, keeping business logic (Phases 2-5)
fully separate from persistence (this file) and presentation (API/frontend).

No business logic lives here: this module never computes a probability,
a recommendation, or a decision - it only reads/writes what those layers
already produced.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import AuditLog, CustomerHistory, Payment, RecoveryAttempt
from app.execution.models import RecoveryTransactionResult


class DuplicateRecoveryAttemptError(Exception):
    """
    Raised when persist_recovery_result() loses a race to a concurrent
    request for the same payment: two requests both passed the
    application-level `get_latest_attempt() is None` check before either
    had inserted, and this one lost the database-level unique-constraint
    race on RecoveryAttempt.payment_id.

    This is the expected, handled outcome of that race - not a corrupted
    state. The caller (see app.api.recovery.trigger_recovery) catches
    this, rolls back, re-fetches the winning attempt, and returns it as
    an idempotent replay - exactly as if this request had arrived after
    the winner instead of concurrently with it.
    """


# ---------- Writes ----------


def upsert_payment_with_customer(session: Session, record: dict) -> Payment:
    """Creates (or updates, if it already exists) a Payment row and its
    associated CustomerHistory row from a flat feature dict - the same
    shape used throughout Phases 2-5. `record` is trusted input from the
    seed script or an internal caller, never taken as-is from the
    frontend for anything that affects a decision."""

    customer_id = str(record["customer_id"])
    customer = session.get(CustomerHistory, customer_id)
    if customer is None:
        customer = CustomerHistory(customer_id=customer_id)
        session.add(customer)

    customer.previous_transactions = int(record.get("previous_transactions") or 0)
    customer.previous_success_rate = float(record.get("previous_success_rate") or 0.0)
    customer.subscription_status = record.get("subscription_status")
    customer.customer_type = record.get("customer_type")
    customer.historical_failure_count = int(record.get("historical_failure_count") or 0)

    existing = session.execute(
        select(Payment).where(Payment.transaction_id == record["transaction_id"])
    ).scalar_one_or_none()

    if existing is not None:
        payment = existing
    else:
        payment = Payment(transaction_id=record["transaction_id"], customer_id=customer_id)
        session.add(payment)

    payment.customer_id = customer_id
    payment.amount = float(record["amount"])
    payment.payment_method = record.get("payment_method", "card")
    payment.failure_reason = record.get("failure_reason")
    payment.status = record.get("status", "failed")
    payment.simulation_outcome = record.get("simulation_outcome")
    payment.days_since_failure = record.get("days_since_failure")
    payment.time_since_last_success = record.get("time_since_last_success")
    payment.device_risk_score = record.get("device_risk_score")

    session.flush()
    return payment


def persist_recovery_result(
    session: Session,
    payment: Payment,
    result: RecoveryTransactionResult,
    retry_count: int,
    ml_probability: float | None,
) -> RecoveryAttempt:
    """Persists the recovery attempt and every audit event from one
    recover_transaction() call. Never invents or recomputes any decision
    value - everything decision-related written here comes directly from
    `result`, which was produced entirely by Phases 2-5. `retry_count` and
    `ml_probability` are passed in from the same payment context the
    caller used to invoke recover_transaction(), for display purposes
    only (they don't affect what gets persisted for the decision itself)."""

    attempt = RecoveryAttempt(
        id=result.recovery_attempt.id,
        payment_id=payment.id,
        retry_count=retry_count,
        ml_probability=ml_probability,
        agent_action=result.agent.requested_action,
        agent_reason=result.agent.explanation,
        agent_confidence=result.agent.confidence,
        rules_decision=result.recovery_attempt.rules_decision,
        execution_status=result.recovery_attempt.execution_status,
        recovered_amount=result.recovery_attempt.recovered_amount,
        failure_reason=result.recovery_attempt.failure_reason,
        simulation_mode=result.recovery_attempt.simulation_mode,
        completed_at=_parse_iso(result.recovery_attempt.completed_at),
        execution_mode=result.recovery_attempt.execution_mode,
        razorpay_payment_link_id=result.recovery_attempt.razorpay_payment_link_id,
        razorpay_payment_link_url=result.recovery_attempt.razorpay_payment_link_url,
        razorpay_reference_id=result.recovery_attempt.razorpay_reference_id,
    )
    session.add(attempt)

    for event in result.audit_events:
        session.add(
            AuditLog(
                payment_id=payment.id,
                event_type=event.event_type,
                event_detail=event.explanation,
                actor="system",
                timestamp=_parse_iso(event.timestamp),  # reuse the event's own precise timestamp,
                # not a fresh server_default=now() - two events in the same
                # workflow can land in the same DB second, and only the
                # original per-event timestamp preserves correct ordering.
                requested_action=event.requested_action,
                rules_decision=event.rules_decision,
                execution_status=event.execution_status,
                reason_codes=json.dumps(event.reason_codes),
                explanation=event.explanation,
                simulation_mode=event.simulation_mode,
            )
        )

    _flush_recovery_attempt(session, payment.id)
    return attempt


def _flush_recovery_attempt(session: Session, payment_id: str) -> None:
    """Flushes the pending RecoveryAttempt + AuditLog inserts as one unit
    and translates a payment_id unique-constraint violation into a clean,
    typed exception. On conflict, session.rollback() discards the whole
    pending batch (attempt and its audit events together) - a losing
    request never leaves orphaned audit rows behind for an attempt that
    was never actually recorded."""
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateRecoveryAttemptError(
            f"A recovery attempt for payment_id={payment_id} already exists "
            "(a concurrent request won the race to insert first)."
        ) from exc


def _parse_iso(value: str | None):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value)


# ---------- Reads ----------


def get_payment_by_transaction_id(session: Session, transaction_id: str) -> Payment | None:
    return session.execute(
        select(Payment)
        .options(selectinload(Payment.recovery_attempts), selectinload(Payment.customer))
        .where(Payment.transaction_id == transaction_id)
    ).scalar_one_or_none()


def get_latest_attempt(session: Session, payment: Payment) -> RecoveryAttempt | None:
    """This MVP allows at most one attempt per payment (idempotency is
    enforced at the API layer, see app.api.recovery), so 'latest' and
    'only' currently coincide - written this way so a future phase
    allowing re-attempts (e.g. after a policy change) doesn't require
    changing every caller."""
    if not payment.recovery_attempts:
        return None
    return max(payment.recovery_attempts, key=lambda a: a.created_at)


def list_payments(
    session: Session,
    search: str | None = None,
    status_filter: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Payment], int]:
    query = select(Payment).options(selectinload(Payment.recovery_attempts))

    if search:
        like = f"%{search}%"
        query = query.where(
            (Payment.transaction_id.ilike(like)) | (Payment.customer_id.ilike(like))
        )

    if status_filter:
        # status_filter matches the latest attempt's execution_status, or
        # "UNPROCESSED" for payments with no attempt yet.
        payments_all = session.execute(query).scalars().all()
        filtered = []
        for p in payments_all:
            latest = get_latest_attempt(session, p)
            current_status = latest.execution_status if latest else "UNPROCESSED"
            if current_status == status_filter:
                filtered.append(p)
        total = len(filtered)
        sortable = filtered
    else:
        all_rows = session.execute(query).scalars().all()
        total = len(all_rows)
        sortable = all_rows

    sort_key_map = {
        "amount": lambda p: p.amount,
        "created_at": lambda p: p.created_at,
        "transaction_id": lambda p: p.transaction_id,
    }
    key_fn = sort_key_map.get(sort_by, sort_key_map["created_at"])
    sortable = sorted(sortable, key=key_fn, reverse=(sort_dir == "desc"))

    page = sortable[offset : offset + limit]
    return page, total


def list_audit_events(
    session: Session, transaction_id: str | None = None, limit: int = 200
) -> list[tuple[AuditLog, str | None]]:
    """Returns (AuditLog, transaction_id) pairs, newest first."""
    query = select(AuditLog, Payment.transaction_id).join(
        Payment, AuditLog.payment_id == Payment.id, isouter=True
    )
    if transaction_id:
        query = query.where(Payment.transaction_id == transaction_id)
    query = query.order_by(AuditLog.timestamp.desc()).limit(limit)
    return list(session.execute(query).all())


def all_payments_with_latest_attempt(session: Session) -> list[tuple[Payment, RecoveryAttempt | None]]:
    payments = (
        session.execute(select(Payment).options(selectinload(Payment.recovery_attempts))).scalars().all()
    )
    return [(p, get_latest_attempt(session, p)) for p in payments]
