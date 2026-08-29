"""
ORM models for RecoverAI.

Phase 1 scope: schema definition only. No ML, agent, or execution logic
reads/writes these tables yet - that comes in later phases. Tables mirror
the schema agreed in the architecture document (Section H).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    transaction_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String, ForeignKey("customer_history.customer_id"))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[str] = mapped_column(String, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Added in Phase 6 (dashboard + API wiring) - purely additive. ---
    # Deterministic, caller-controlled simulation outcome for this payment's
    # next RETRY execution (see app.execution.executor). Used by the demo
    # seed script for reproducible variety; ordinary payments leave this
    # null, which the executor treats as "default to SUCCESS".
    simulation_outcome: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Added post-Phase-7 (buildathon polish) - purely additive.
    # These three ML features (see app.ml.features.NUMERIC_FEATURES) were
    # previously hardcoded to fixed constants in
    # app.api.recovery._build_feature_payload() regardless of the actual
    # transaction, silently flattening 3 of the model's 8 features for
    # every live-triggered recovery. Stored per-payment now so the live
    # API path uses real, differentiated values - the same way retry_count/
    # previous_success_rate/etc. always have. Nullable with sensible
    # defaults applied at read time (see _build_feature_payload) so
    # existing rows created before this change remain valid. ---
    days_since_failure: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_since_last_success: Mapped[float | None] = mapped_column(Float, nullable=True)
    device_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    customer: Mapped["CustomerHistory"] = relationship(back_populates="payments")
    recovery_attempts: Mapped[list["RecoveryAttempt"]] = relationship(back_populates="payment")
    audit_events: Mapped[list["AuditLog"]] = relationship(back_populates="payment")


class CustomerHistory(Base):
    __tablename__ = "customer_history"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    previous_transactions: Mapped[int] = mapped_column(Integer, default=0)
    previous_success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    subscription_status: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_type: Mapped[str | None] = mapped_column(String, nullable=True)
    historical_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    payments: Mapped[list["Payment"]] = relationship(back_populates="customer")


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # unique=True: at most one RecoveryAttempt per payment. This is the
    # database-level idempotency guarantee added to close a race condition
    # identified in code review - see app.db.repository.persist_recovery_result
    # and app.api.recovery for how a conflict here is handled gracefully.
    payment_id: Mapped[str] = mapped_column(String, ForeignKey("payments.id"), unique=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    ml_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_action: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_status: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Added in Phase 5 (bounded recovery execution) - purely additive,
    # nothing above this line was changed or removed. ---
    execution_status: Mapped[str | None] = mapped_column(String, nullable=True)
    recovered_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulation_mode: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Added in Phase 6 (dashboard + API wiring) - purely additive.
    # `rules_decision` is the authoritative ALLOW/BLOCK/HUMAN_APPROVAL value
    # for this attempt. The legacy `safety_status` / `execution_decision` /
    # `result` columns above are retained from Phase 1's initial draft
    # schema for backwards compatibility but are not written to by Phase 6+
    # - `rules_decision` and `execution_status` are the columns of record. ---
    rules_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Added in Phase 7 (Razorpay Test Mode integration) - purely
    # additive. `execution_mode` distinguishes an in-process
    # SimulationExecutor result ("SIMULATION") from a real Razorpay Test
    # Mode API call ("RAZORPAY_TEST_MODE") - both are safe, neither is
    # real money, but they're materially different for audit purposes. ---
    execution_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    razorpay_payment_link_id: Mapped[str | None] = mapped_column(String, nullable=True)
    razorpay_payment_link_url: Mapped[str | None] = mapped_column(String, nullable=True)
    razorpay_reference_id: Mapped[str | None] = mapped_column(String, nullable=True)

    payment: Mapped["Payment"] = relationship(back_populates="recovery_attempts")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    payment_id: Mapped[str | None] = mapped_column(String, ForeignKey("payments.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, default="system")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Added in Phase 6 (dashboard + API wiring) - purely additive.
    # `reason_codes` is stored as a JSON-encoded string (Text) since plain
    # SQLite/Postgres String columns don't support arrays uniformly across
    # both backends without a migration-managed ARRAY type; decoded on read
    # in app.db.repository. ---
    requested_action: Mapped[str | None] = mapped_column(String, nullable=True)
    rules_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_status: Mapped[str | None] = mapped_column(String, nullable=True)
    reason_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    simulation_mode: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    payment: Mapped["Payment | None"] = relationship(back_populates="audit_events")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
