"""
GET /api/dashboard/summary and GET /api/analytics.

Every figure here is computed from persisted Payment / RecoveryAttempt
rows at request time - nothing is hard-coded, and nothing here reads
Phase 2's test-set metrics (those describe model quality on a held-out
sample; this describes actual/demo workflow outcomes).

REVENUE DEFINITIONS (see docs/dashboard.md for the full writeup):
- revenue_at_risk: sum of every persisted payment's amount. Every row in
  the payments table is, by this project's dataset design, a failed
  payment - so failed_payments == total_payments here.
- potentially_recoverable_revenue: sum of amounts for payments whose
  latest recovery attempt has rules_decision in {ALLOW, HUMAN_APPROVAL}
  - i.e. the rules engine did not BLOCK it outright. Payments with no
  attempt yet are not counted here (their rules decision is unknown
  until the workflow actually runs).
- recovered_revenue: sum of recovered_amount ONLY where execution_status
  == SUCCESS. BLOCKED, FAILED, and PENDING_HUMAN_APPROVAL never
  contribute, by construction.
- recovery_rate: recovered_revenue / potentially_recoverable_revenue
  (0 if the denominator is 0).
"""

from __future__ import annotations

from collections import Counter
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import AnalyticsResponse, DashboardSummary
from app.db import repository
from app.db.session import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


def _compute_summary(db: Session) -> DashboardSummary:
    pairs = repository.all_payments_with_latest_attempt(db)

    total_payments = len(pairs)
    revenue_at_risk = 0.0
    potentially_recoverable = 0.0
    recovered = 0.0

    n_success = n_failed = n_blocked = n_pending = n_unprocessed = 0

    for payment, attempt in pairs:
        revenue_at_risk += payment.amount

        if attempt is None:
            n_unprocessed += 1
            continue

        if attempt.rules_decision in {"ALLOW", "HUMAN_APPROVAL"}:
            potentially_recoverable += payment.amount

        status = attempt.execution_status
        if status == "SUCCESS":
            recovered += attempt.recovered_amount or 0.0
            n_success += 1
        elif status == "FAILED":
            n_failed += 1
        elif status == "BLOCKED":
            n_blocked += 1
        elif status == "PENDING_HUMAN_APPROVAL":
            n_pending += 1

    recovery_rate = round(recovered / potentially_recoverable, 4) if potentially_recoverable > 0 else 0.0

    return DashboardSummary(
        total_payments=total_payments,
        failed_payments=total_payments,  # every persisted payment is a failed payment by dataset design
        revenue_at_risk_inr=round(revenue_at_risk, 2),
        potentially_recoverable_revenue_inr=round(potentially_recoverable, 2),
        recovered_revenue_inr=round(recovered, 2),
        recovery_rate=recovery_rate,
        automated_recoveries=n_success,
        failed_recoveries=n_failed,
        blocked_recoveries=n_blocked,
        pending_human_approval=n_pending,
        unprocessed_payments=n_unprocessed,
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    return _compute_summary(db)


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(db: Session = Depends(get_db)) -> AnalyticsResponse:
    summary = _compute_summary(db)
    pairs = repository.all_payments_with_latest_attempt(db)

    status_breakdown: Counter = Counter()
    failure_reason_breakdown: Counter = Counter()
    reason_code_counter: Counter = Counter()

    for payment, attempt in pairs:
        status_breakdown[attempt.execution_status if attempt else "UNPROCESSED"] += 1
        if payment.failure_reason:
            failure_reason_breakdown[payment.failure_reason] += 1

    audit_rows = repository.list_audit_events(db, transaction_id=None, limit=1000)
    for row, _txn_id in audit_rows:
        if row.reason_codes:
            for code in json.loads(row.reason_codes):
                reason_code_counter[code] += 1

    return AnalyticsResponse(
        summary=summary,
        status_breakdown=dict(status_breakdown),
        failure_reason_breakdown=dict(failure_reason_breakdown),
        top_reason_codes=dict(reason_code_counter.most_common(10)),
    )
