"""
Phase 5 orchestrator.

recover_transaction() is the one function that ties every phase together:

1. Load payment (caller-supplied dict - no DB wiring yet, matching the
   "shape now, persist later" pattern used throughout this project)
2. Get ML recovery probability          (Phase 2, via app.agent.service)
3. Get AI recommendation                (Phase 4)
4. Evaluate rules                       (Phase 3, via Phase 4's combined call)
5. BLOCK        -> stop, do not execute
   HUMAN_APPROVAL -> create a pending state, do not execute
   ALLOW        -> run RecoveryExecutor
6. Record the recovery attempt
7. Record audit events
8. Return the complete structured result

NON-NEGOTIABLE SAFETY RULE: RecoveryExecutor.execute() is called in
exactly one place in this file, inside the `final_decision == "ALLOW"`
branch, and nowhere else. There is no path from BLOCK or HUMAN_APPROVAL
to execution, and no path where an exception silently becomes SUCCESS.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.agent.providers import LLMProvider
from app.agent.schemas import AgentRecommendation, SafetyDecisionSummary
from app.agent.service import get_recommendation_and_decision
from app.execution.enums import ExecutionStatus
from app.execution.executor import RecoveryExecutor
from app.execution.models import AuditEvent, RecoveryAttemptRecord, RecoveryTransactionResult
from app.rules.policies import Policy

# Process-local idempotency store. This is intentionally NOT persistent
# across restarts - it exists to prevent accidental duplicate execution
# within a single running process/request lifecycle. A later phase
# backing this with a DB unique constraint (transaction_id + attempt
# generation) would make it durable across restarts and instances;
# documented in docs/recovery-execution.md.
_DEFAULT_IDEMPOTENCY_STORE: dict[str, RecoveryTransactionResult] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recommended_event(transaction_id: str, agent: AgentRecommendation) -> AuditEvent:
    return AuditEvent(
        transaction_id=transaction_id,
        event_type="RECOVERY_RECOMMENDED",
        requested_action=agent.requested_action,
        reason_codes=agent.reason_codes,
        explanation=agent.explanation,
        simulation_mode=True,
        timestamp=agent.generated_at,
    )


def _blocked_event(transaction_id: str, agent: AgentRecommendation, safety: SafetyDecisionSummary) -> AuditEvent:
    return AuditEvent(
        transaction_id=transaction_id,
        event_type="RECOVERY_BLOCKED",
        requested_action=agent.requested_action,
        rules_decision=safety.decision,
        execution_status=ExecutionStatus.BLOCKED.value,
        reason_codes=safety.reason_codes,
        explanation=safety.explanation,
        simulation_mode=True,
        timestamp=_now_iso(),
    )


def _approval_required_event(
    transaction_id: str, agent: AgentRecommendation, safety: SafetyDecisionSummary
) -> AuditEvent:
    return AuditEvent(
        transaction_id=transaction_id,
        event_type="RECOVERY_APPROVAL_REQUIRED",
        requested_action=agent.requested_action,
        rules_decision=safety.decision,
        execution_status=ExecutionStatus.PENDING_HUMAN_APPROVAL.value,
        reason_codes=safety.reason_codes,
        explanation=safety.explanation,
        simulation_mode=True,
        timestamp=_now_iso(),
    )


def _execution_event(
    transaction_id: str,
    agent: AgentRecommendation,
    safety: SafetyDecisionSummary,
    execution_status: str,
    detail: str,
    execution_mode: str = "SIMULATION",
) -> AuditEvent:
    if execution_status == ExecutionStatus.COMPLETED.value and execution_mode == "RAZORPAY_TEST_MODE":
        # A Razorpay Test Mode Payment Link being created is distinct
        # enough from a generic passive/outreach COMPLETED action (Phase 5)
        # to warrant its own event type - per Phase 7's audit requirements.
        event_type = "RAZORPAY_PAYMENT_LINK_CREATED"
    else:
        event_type = {
            ExecutionStatus.SUCCESS.value: "RECOVERY_EXECUTED",
            ExecutionStatus.FAILED.value: "RECOVERY_FAILED",
            ExecutionStatus.COMPLETED.value: "RECOVERY_COMPLETED",
            ExecutionStatus.NOT_EXECUTED.value: "RECOVERY_FAILED",
        }.get(execution_status, "RECOVERY_FAILED")

    return AuditEvent(
        transaction_id=transaction_id,
        event_type=event_type,
        requested_action=agent.requested_action,
        rules_decision=safety.decision,
        execution_status=execution_status,
        reason_codes=safety.reason_codes,
        explanation=detail,
        simulation_mode=True,
        timestamp=_now_iso(),
    )


def _invalid_transaction_result(transaction_id: str, reason: str) -> RecoveryTransactionResult:
    """Fail-closed path for a payload we can't even evaluate. Mirrors the
    fallback conventions used by app.agent.service and app.rules.engine -
    never raises, never authorizes anything."""
    now = _now_iso()
    agent = AgentRecommendation(
        transaction_id=transaction_id,
        requested_action="HUMAN_REVIEW",
        confidence=0.0,
        explanation=f"[SYSTEM FALLBACK] Cannot evaluate this transaction ({reason}). Routed to human review.",
        reason_codes=["INVALID_TRANSACTION_PAYLOAD"],
        provider="system",
        is_mock=True,
        model=None,
        generated_at=now,
    )
    safety = SafetyDecisionSummary(
        decision="BLOCK",
        reason_codes=["INVALID_INPUT"],
        requires_human_approval=False,
        explanation=f"Transaction payload is invalid or missing ({reason}); failing closed.",
        policy_version="n/a",
    )
    attempt = RecoveryAttemptRecord(
        id=str(uuid.uuid4()),
        transaction_id=transaction_id,
        requested_action=agent.requested_action,
        rules_decision=safety.decision,
        execution_status=ExecutionStatus.NOT_EXECUTED.value,
        amount=0.0,
        recovered_amount=0.0,
        failure_reason=reason,
        simulation_mode=True,
        created_at=now,
        completed_at=now,
    )
    events = [
        AuditEvent(
            transaction_id=transaction_id,
            event_type="RECOVERY_FAILED",
            requested_action=agent.requested_action,
            rules_decision=safety.decision,
            execution_status=ExecutionStatus.NOT_EXECUTED.value,
            reason_codes=["INVALID_TRANSACTION_PAYLOAD"],
            explanation=reason,
            simulation_mode=True,
            timestamp=now,
        )
    ]
    return RecoveryTransactionResult(agent=agent, safety=safety, recovery_attempt=attempt, audit_events=events)


def recover_transaction(
    payment: dict,
    provider: LLMProvider | None = None,
    policy: Policy | None = None,
    executor: RecoveryExecutor | None = None,
    idempotency_store: dict[str, RecoveryTransactionResult] | None = None,
    forced_outcome: str | None = None,
) -> RecoveryTransactionResult:
    """
    The complete Phase 1-5 pipeline for one failed payment.

    Never raises. Never returns SUCCESS on an execution error. Execution
    only ever runs when the Phase 3 rules engine's final_decision is
    exactly "ALLOW".
    """
    executor = executor or RecoveryExecutor()
    store = idempotency_store if idempotency_store is not None else _DEFAULT_IDEMPOTENCY_STORE

    if not isinstance(payment, dict) or not payment.get("transaction_id"):
        transaction_id = str(payment.get("transaction_id")) if isinstance(payment, dict) else "UNKNOWN"
        return _invalid_transaction_result(transaction_id or "UNKNOWN", "missing or invalid transaction_id")

    transaction_id = str(payment["transaction_id"])
    idempotency_key = str(payment.get("idempotency_key") or transaction_id)

    if idempotency_key in store:
        cached = store[idempotency_key]
        return cached.model_copy(update={"idempotent_replay": True})

    try:
        combined = get_recommendation_and_decision(payment, provider, policy)
    except Exception as exc:  # noqa: BLE001 - fail closed, never raise
        result = _invalid_transaction_result(transaction_id, f"agent/rules pipeline failed: {exc}")
        store[idempotency_key] = result
        return result

    agent = combined.agent
    safety = combined.safety
    amount = float(payment.get("amount") or 0.0)
    attempt_id = str(uuid.uuid4())

    audit_events: list[AuditEvent] = [_recommended_event(transaction_id, agent)]

    # Defaults for paths where nothing actually executed (BLOCK, HUMAN_APPROVAL,
    # error) - overwritten below only in the ALLOW branch, from whatever the
    # active executor (SimulationExecutor or RazorpayTestExecutor) actually reports.
    simulation_mode = True
    execution_mode = "SIMULATION"
    razorpay_payment_link_id = None
    razorpay_payment_link_url = None
    razorpay_reference_id = None

    if combined.final_decision == "BLOCK":
        execution_status = ExecutionStatus.BLOCKED.value
        recovered_amount = 0.0
        failure_reason = None
        audit_events.append(_blocked_event(transaction_id, agent, safety))

    elif combined.final_decision == "HUMAN_APPROVAL":
        execution_status = ExecutionStatus.PENDING_HUMAN_APPROVAL.value
        recovered_amount = 0.0
        failure_reason = None
        audit_events.append(_approval_required_event(transaction_id, agent, safety))

    elif combined.final_decision == "ALLOW":
        try:
            exec_result = executor.execute(agent.requested_action, payment, forced_outcome=forced_outcome)
            execution_status = exec_result.status
            recovered_amount = exec_result.recovered_amount
            failure_reason = exec_result.failure_reason
            simulation_mode = exec_result.simulation_mode
            execution_mode = exec_result.execution_mode
            razorpay_payment_link_id = exec_result.razorpay_payment_link_id
            razorpay_payment_link_url = exec_result.razorpay_payment_link_url
            razorpay_reference_id = exec_result.razorpay_reference_id
            audit_events.append(
                _execution_event(
                    transaction_id, agent, safety, execution_status, exec_result.detail, exec_result.execution_mode
                )
            )
        except Exception as exc:  # noqa: BLE001 - execution errors NEVER become SUCCESS
            execution_status = ExecutionStatus.NOT_EXECUTED.value
            recovered_amount = 0.0
            failure_reason = f"execution_error: {exc}"
            audit_events.append(
                _execution_event(
                    transaction_id, agent, safety, execution_status, f"Execution adapter raised: {exc}"
                )
            )

    else:  # pragma: no cover - rules engine's Decision enum is closed; guard anyway
        execution_status = ExecutionStatus.NOT_EXECUTED.value
        recovered_amount = 0.0
        failure_reason = f"unrecognized_rules_decision: {combined.final_decision}"
        audit_events.append(_execution_event(transaction_id, agent, safety, execution_status, failure_reason))

    attempt = RecoveryAttemptRecord(
        id=attempt_id,
        transaction_id=transaction_id,
        requested_action=agent.requested_action,
        rules_decision=combined.final_decision,
        execution_status=execution_status,
        amount=amount,
        recovered_amount=recovered_amount,
        failure_reason=failure_reason,
        simulation_mode=simulation_mode,
        created_at=agent.generated_at,
        completed_at=_now_iso(),
        execution_mode=execution_mode,
        razorpay_payment_link_id=razorpay_payment_link_id,
        razorpay_payment_link_url=razorpay_payment_link_url,
        razorpay_reference_id=razorpay_reference_id,
    )

    result = RecoveryTransactionResult(
        agent=agent,
        safety=safety,
        recovery_attempt=attempt,
        audit_events=audit_events,
        idempotent_replay=False,
    )
    store[idempotency_key] = result
    return result
