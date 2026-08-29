"""
Response models for the Phase 6 dashboard API. These describe DISPLAY
shapes only - none of them are inputs a client can use to influence a
decision. Endpoints that accept a body (POST /api/recovery/{id}) take no
decision-relevant fields from the client at all; see app.api.recovery.
"""

from __future__ import annotations

from pydantic import BaseModel


class PaymentListItem(BaseModel):
    transaction_id: str
    customer_id: str
    amount: float
    payment_method: str
    failure_reason: str | None
    retry_count: int | None
    recovery_probability: float | None
    status: str  # execution_status of the latest attempt, or "UNPROCESSED"
    requested_action: str | None
    rules_decision: str | None
    created_at: str


class PaymentListResponse(BaseModel):
    items: list[PaymentListItem]
    total: int
    limit: int
    offset: int


class AuditEventOut(BaseModel):
    timestamp: str
    event_type: str
    transaction_id: str | None
    requested_action: str | None
    rules_decision: str | None
    execution_status: str | None
    reason_codes: list[str]
    explanation: str | None


class RecoveryAttemptOut(BaseModel):
    id: str
    retry_count: int | None
    recovery_probability: float | None
    requested_action: str | None
    agent_explanation: str | None
    agent_confidence: float | None
    rules_decision: str | None
    execution_status: str | None
    recovered_amount: float | None
    failure_reason: str | None
    simulation_mode: bool | None
    created_at: str | None
    completed_at: str | None

    # --- Added in Phase 7 (Razorpay Test Mode) - additive, all optional. ---
    execution_mode: str | None = None  # "SIMULATION" | "RAZORPAY_TEST_MODE"
    razorpay_payment_link_id: str | None = None
    razorpay_payment_link_url: str | None = None
    razorpay_reference_id: str | None = None


class PaymentDetail(BaseModel):
    transaction_id: str
    customer_id: str
    amount: float
    payment_method: str
    failure_reason: str | None
    status: str
    created_at: str

    previous_transactions: int
    previous_success_rate: float
    subscription_status: str | None
    customer_type: str | None
    historical_failure_count: int

    latest_attempt: RecoveryAttemptOut | None
    audit_trail: list[AuditEventOut]


class RecoveryWorkflowResponse(BaseModel):
    """The complete structured result of running (or replaying) the
    recovery workflow for one transaction - agent recommendation, rules
    decision, execution outcome, and the audit events it produced."""

    transaction_id: str
    idempotent_replay: bool

    recovery_probability: float | None

    agent_requested_action: str
    agent_confidence: float
    agent_explanation: str
    agent_reason_codes: list[str]
    agent_provider: str
    agent_is_mock: bool

    rules_decision: str
    rules_reason_codes: list[str]
    rules_explanation: str
    requires_human_approval: bool

    execution_status: str
    recovered_amount: float
    failure_reason: str | None
    simulation_mode: bool

    # --- Added in Phase 7 - additive, all optional. ---
    execution_mode: str = "SIMULATION"
    razorpay_payment_link_id: str | None = None
    razorpay_payment_link_url: str | None = None
    razorpay_reference_id: str | None = None

    audit_events: list[AuditEventOut]


class DashboardSummary(BaseModel):
    total_payments: int
    failed_payments: int
    revenue_at_risk_inr: float
    potentially_recoverable_revenue_inr: float
    recovered_revenue_inr: float
    recovery_rate: float
    automated_recoveries: int
    failed_recoveries: int
    blocked_recoveries: int
    pending_human_approval: int
    unprocessed_payments: int


class AnalyticsResponse(BaseModel):
    summary: DashboardSummary
    status_breakdown: dict[str, int]
    failure_reason_breakdown: dict[str, int]
    top_reason_codes: dict[str, int]
