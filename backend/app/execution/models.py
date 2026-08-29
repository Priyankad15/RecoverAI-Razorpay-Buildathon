"""
Typed contracts for the Phase 5 execution layer. All shapes here are
audit_log / recovery_attempts - ready, per the Phase 5 requirements -
persistence itself is not wired up yet (same "shape now, persist later"
pattern used in Phase 3/4's decision objects).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.agent.schemas import AgentRecommendation, SafetyDecisionSummary


class ExecutionResult(BaseModel):
    """What the RecoveryExecutor actually did for one action."""

    model_config = ConfigDict(extra="forbid")

    action: str
    status: str  # ExecutionStatus value
    simulation_mode: bool = True
    recovered_amount: float = 0.0
    failure_reason: str | None = None
    executed_at: str
    detail: str  # always includes "[SIMULATION / TEST MODE]" or "[RAZORPAY TEST MODE]"

    # --- Added in Phase 7 (Razorpay Test Mode integration) - purely
    # additive, all default so every existing SimulationExecutor call site
    # is unaffected. ---
    execution_mode: str = "SIMULATION"  # "SIMULATION" | "RAZORPAY_TEST_MODE"
    razorpay_payment_link_id: str | None = None
    razorpay_payment_link_url: str | None = None
    razorpay_reference_id: str | None = None


class AuditEvent(BaseModel):
    """One entry in the recovery audit trail. Ready for direct
    audit_log persistence in a later phase."""

    transaction_id: str
    event_type: str
    requested_action: str | None = None
    rules_decision: str | None = None
    execution_status: str | None = None
    reason_codes: list[str] = []
    explanation: str
    simulation_mode: bool = True
    timestamp: str


class RecoveryAttemptRecord(BaseModel):
    """Ready for direct recovery_attempts persistence in a later phase."""

    id: str
    transaction_id: str
    requested_action: str
    rules_decision: str
    execution_status: str
    amount: float
    recovered_amount: float
    failure_reason: str | None = None
    simulation_mode: bool = True
    created_at: str
    completed_at: str | None = None

    # --- Added in Phase 7 - purely additive, defaulted. ---
    execution_mode: str = "SIMULATION"
    razorpay_payment_link_id: str | None = None
    razorpay_payment_link_url: str | None = None
    razorpay_reference_id: str | None = None


class RecoveryTransactionResult(BaseModel):
    """
    The complete, structured result of recover_transaction(): the AI's
    advisory recommendation, the rules engine's authoritative decision,
    what (if anything) the execution adapter actually did, and the full
    audit trail for this transaction.
    """

    agent: AgentRecommendation
    safety: SafetyDecisionSummary
    recovery_attempt: RecoveryAttemptRecord
    audit_events: list[AuditEvent]
    idempotent_replay: bool = False

    def to_audit_dicts(self) -> list[dict]:
        return [event.model_dump() for event in self.audit_events]
