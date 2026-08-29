"""
Typed contracts for the AI recovery agent.

AgentRecommendation is strictly validated - it reuses app.rules.enums.RecoveryAction
rather than defining a second action vocabulary, so there is exactly one
place in the codebase that defines what actions exist.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rules.enums import RecoveryAction


class AgentRecommendation(BaseModel):
    """
    The AI agent's output. This is a REQUEST, not a decision - nothing in
    this model authorizes anything. See app.rules.engine for the only
    component permitted to authorize a money-related action.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    requested_action: str
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    reason_codes: list[str] = Field(default_factory=list)

    # Provenance - always populated so a decision record never looks like
    # it came from nowhere, and so a mock recommendation can never be
    # mistaken for a real one.
    provider: str
    is_mock: bool
    model: str | None = None
    generated_at: str

    @field_validator("requested_action")
    @classmethod
    def _action_must_be_approved(cls, value: str) -> str:
        try:
            RecoveryAction(value)
        except ValueError as exc:
            raise ValueError(
                f"'{value}' is not an approved recovery action "
                f"(allowed: {', '.join(a.value for a in RecoveryAction)})"
            ) from exc
        return value

    @field_validator("explanation")
    @classmethod
    def _explanation_must_be_nonempty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("explanation must not be empty")
        return value

    @field_validator("transaction_id")
    @classmethod
    def _transaction_id_must_be_nonempty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("transaction_id must not be empty")
        return value


class SafetyDecisionSummary(BaseModel):
    """A thin, audit-ready mirror of the Phase 3 RuleEngineDecision fields
    relevant to the combined agent+rules response."""

    decision: str  # ALLOW | BLOCK | HUMAN_APPROVAL
    reason_codes: list[str]
    requires_human_approval: bool
    explanation: str
    policy_version: str


class AgentRulesResult(BaseModel):
    """
    Combined output of the Phase 4 workflow: the agent's (advisory)
    recommendation alongside the Phase 3 rules engine's (authoritative)
    decision. `final_decision` always mirrors `safety.decision` - it is
    never derived from `agent.requested_action`. The two are kept as
    separate objects, deliberately, so a caller cannot conflate
    "the AI recommended X" with "X is allowed."
    """

    agent: AgentRecommendation
    safety: SafetyDecisionSummary
    final_decision: str

    def to_audit_dict(self) -> dict:
        """Flattened, audit_log-ready representation. Not persisted yet
        (Phase 5+) - shape only."""
        return {
            "transaction_id": self.agent.transaction_id,
            "agent_requested_action": self.agent.requested_action,
            "agent_confidence": self.agent.confidence,
            "agent_explanation": self.agent.explanation,
            "agent_reason_codes": self.agent.reason_codes,
            "agent_provider": self.agent.provider,
            "agent_is_mock": self.agent.is_mock,
            "agent_model": self.agent.model,
            "agent_generated_at": self.agent.generated_at,
            "safety_decision": self.safety.decision,
            "safety_reason_codes": self.safety.reason_codes,
            "safety_requires_human_approval": self.safety.requires_human_approval,
            "safety_explanation": self.safety.explanation,
            "safety_policy_version": self.safety.policy_version,
            "final_decision": self.final_decision,
        }
