"""
GET /api/payments and GET /api/payments/{transaction_id}.

Read-only. No business logic - everything here is a display projection
of what's already persisted (Phase 2-5 computed it; this just reads it).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    AuditEventOut,
    PaymentDetail,
    PaymentListItem,
    PaymentListResponse,
    RecoveryAttemptOut,
)
from app.db import repository
from app.db.session import get_db

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("", response_model=PaymentListResponse)
def list_payments(
    search: str | None = Query(default=None, description="Search by transaction ID or customer ID"),
    status: str | None = Query(default=None, description="Filter by execution status, or UNPROCESSED"),
    sort_by: str = Query(default="created_at", pattern="^(created_at|amount|transaction_id)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaymentListResponse:
    payments, total = repository.list_payments(
        db, search=search, status_filter=status, sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset
    )

    items = []
    for payment in payments:
        latest = repository.get_latest_attempt(db, payment)
        items.append(
            PaymentListItem(
                transaction_id=payment.transaction_id,
                customer_id=payment.customer_id,
                amount=payment.amount,
                payment_method=payment.payment_method,
                failure_reason=payment.failure_reason,
                retry_count=latest.retry_count if latest else None,
                recovery_probability=latest.ml_probability if latest else None,
                status=latest.execution_status if latest else "UNPROCESSED",
                requested_action=latest.agent_action if latest else None,
                rules_decision=latest.rules_decision if latest else None,
                created_at=_iso(payment.created_at),
            )
        )

    return PaymentListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{transaction_id}", response_model=PaymentDetail)
def get_payment_detail(transaction_id: str, db: Session = Depends(get_db)) -> PaymentDetail:
    payment = repository.get_payment_by_transaction_id(db, transaction_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    latest = repository.get_latest_attempt(db, payment)
    latest_out = None
    if latest is not None:
        latest_out = RecoveryAttemptOut(
            id=latest.id,
            retry_count=latest.retry_count,
            recovery_probability=latest.ml_probability,
            requested_action=latest.agent_action,
            agent_explanation=latest.agent_reason,
            agent_confidence=latest.agent_confidence,
            rules_decision=latest.rules_decision,
            execution_status=latest.execution_status,
            recovered_amount=latest.recovered_amount,
            failure_reason=latest.failure_reason,
            simulation_mode=latest.simulation_mode,
            created_at=_iso(latest.created_at),
            completed_at=_iso(latest.completed_at),
            execution_mode=latest.execution_mode,
            razorpay_payment_link_id=latest.razorpay_payment_link_id,
            razorpay_payment_link_url=latest.razorpay_payment_link_url,
            razorpay_reference_id=latest.razorpay_reference_id,
        )

    audit_rows = repository.list_audit_events(db, transaction_id=transaction_id)
    audit_trail = [
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
        for row, txn_id in audit_rows
    ]

    customer = payment.customer

    return PaymentDetail(
        transaction_id=payment.transaction_id,
        customer_id=payment.customer_id,
        amount=payment.amount,
        payment_method=payment.payment_method,
        failure_reason=payment.failure_reason,
        status=latest.execution_status if latest else "UNPROCESSED",
        created_at=_iso(payment.created_at),
        previous_transactions=customer.previous_transactions if customer else 0,
        previous_success_rate=customer.previous_success_rate if customer else 0.0,
        subscription_status=customer.subscription_status if customer else None,
        customer_type=customer.customer_type if customer else None,
        historical_failure_count=customer.historical_failure_count if customer else 0,
        latest_attempt=latest_out,
        audit_trail=audit_trail,
    )
