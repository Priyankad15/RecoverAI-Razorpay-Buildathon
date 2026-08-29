"""
Typed input/output contracts for the rules engine.

RecoveryActionRequest performs strict field-level validation (type,
range, non-empty). requested_action is intentionally kept as a raw string
here rather than the RecoveryAction enum, so that an unsupported action
string produces the engine's own UNSUPPORTED_ACTION reason code (step 2
of the evaluation order) instead of a generic pydantic validation error -
callers get a consistent, explainable response either way.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecoveryActionRequest(BaseModel):
    """Input to the rules engine. Strict: extra fields are rejected,
    types are enforced, and ranges are validated at construction time."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    recovery_probability: float = Field(ge=0.0, le=1.0)
    retry_count: int = Field(ge=0)
    requested_action: str = Field(min_length=1)
    failure_reason: str = Field(min_length=1)

    @field_validator("transaction_id", "requested_action", "failure_reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class RuleEngineDecision(BaseModel):
    """Output of the rules engine. Shaped to be written directly into the
    audit_log table (Phase 5+) without transformation."""

    transaction_id: str
    requested_action: str
    decision: str  # ALLOW | BLOCK | HUMAN_APPROVAL
    reason_codes: list[str]
    explanation: str
    requires_human_approval: bool
    policy_version: str
    evaluated_at: str  # ISO 8601 UTC timestamp
