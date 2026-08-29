"""
Batch-level revenue accounting, computed from actual RecoveryTransactionResult
objects - never hard-coded, never guessed.

Three figures, deliberately kept distinct (per Phase 2 and Phase 5's
shared requirement to never conflate predicted/pending amounts with
actually-recovered ones):

- amount_at_risk:              sum of every processed transaction's amount
- potentially_recoverable_amount: sum where the rules engine did not BLOCK
                                   the transaction outright (ALLOW or
                                   HUMAN_APPROVAL) - i.e. still in play
- recovered_amount:            sum of ExecutionStatus.SUCCESS amounts ONLY

BLOCKED, FAILED, and PENDING_HUMAN_APPROVAL transactions never contribute
to recovered_amount.
"""

from __future__ import annotations

from app.execution.enums import ExecutionStatus
from app.execution.models import RecoveryTransactionResult


def compute_batch_revenue_metrics(results: list[RecoveryTransactionResult]) -> dict:
    amount_at_risk = 0.0
    potentially_recoverable_amount = 0.0
    recovered_amount = 0.0

    n_success = 0
    n_failed = 0
    n_blocked = 0
    n_pending_approval = 0
    n_completed = 0
    n_not_executed = 0

    for result in results:
        attempt = result.recovery_attempt
        amount_at_risk += attempt.amount

        if attempt.rules_decision in {"ALLOW", "HUMAN_APPROVAL"}:
            potentially_recoverable_amount += attempt.amount

        if attempt.execution_status == ExecutionStatus.SUCCESS.value:
            recovered_amount += attempt.recovered_amount
            n_success += 1
        elif attempt.execution_status == ExecutionStatus.FAILED.value:
            n_failed += 1
        elif attempt.execution_status == ExecutionStatus.BLOCKED.value:
            n_blocked += 1
        elif attempt.execution_status == ExecutionStatus.PENDING_HUMAN_APPROVAL.value:
            n_pending_approval += 1
        elif attempt.execution_status == ExecutionStatus.COMPLETED.value:
            n_completed += 1
        elif attempt.execution_status == ExecutionStatus.NOT_EXECUTED.value:
            n_not_executed += 1

    n_total = len(results)
    recovery_rate = round(recovered_amount / amount_at_risk, 4) if amount_at_risk > 0 else 0.0

    return {
        "note": (
            "amount_at_risk is every processed transaction's amount. "
            "potentially_recoverable_amount includes ALLOW and HUMAN_APPROVAL "
            "transactions - it is NOT recovered revenue. recovered_amount counts "
            "ONLY transactions whose execution_status is SUCCESS."
        ),
        "n_transactions": n_total,
        "amount_at_risk_inr": round(amount_at_risk, 2),
        "potentially_recoverable_amount_inr": round(potentially_recoverable_amount, 2),
        "recovered_amount_inr": round(recovered_amount, 2),
        "recovery_rate": recovery_rate,
        "counts": {
            "success": n_success,
            "failed": n_failed,
            "blocked": n_blocked,
            "pending_human_approval": n_pending_approval,
            "completed_passive_or_outreach": n_completed,
            "not_executed": n_not_executed,
        },
    }
