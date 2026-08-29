"""
Tests for the Phase 4 AI recovery agent.

No test depends on a real external LLM API. MockProvider is used for
deterministic-heuristic tests; small local stub providers simulate
timeouts, malformed output, and provider errors to exercise the
fail-safe fallback path.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.providers import LLMProvider, MockProvider, ProviderError, get_default_provider
from app.agent.schemas import AgentRecommendation, AgentRulesResult
from app.agent.service import get_agent_recommendation, get_recommendation_and_decision
from app.core.config import Settings
from app.rules.policies import Policy

TEST_POLICY = Policy(
    version="test-v1",
    max_automated_retries=2,
    min_recovery_probability=0.30,
    high_value_threshold_inr=50000.0,
    hard_stop_failure_reasons=frozenset({"risk_flagged"}),
)


def _payment(**overrides) -> dict:
    payment = {
        "transaction_id": "TXN2001",
        "amount": 4999.0,
        "payment_method": "upi",
        "failure_reason": "network_timeout",
        "retry_count": 0,
        "previous_transactions": 20,
        "previous_success_rate": 0.91,
        "subscription_status": "active",
        "customer_type": "returning",
        "days_since_failure": 0,
        "time_since_last_success": 24.0,
        "device_risk_score": 0.1,
        "historical_failure_count": 0,
        # Precomputed to keep tests independent of the trained ML artifact
        # unless a test explicitly wants to exercise that path.
        "recovery_probability": 0.85,
    }
    payment.update(overrides)
    return payment


# ---------- Test-only stub providers (simulate failures, no network) ----------

class _MalformedProvider(LLMProvider):
    name = "stub-malformed"
    is_mock = True

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        return {"requested_action": "RETRY"}  # missing confidence/explanation


class _UnsupportedActionProvider(LLMProvider):
    name = "stub-unsupported"
    is_mock = True

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        return {
            "requested_action": "TRANSFER_ALL_FUNDS",
            "confidence": 0.9,
            "explanation": "not a real action",
            "reason_codes": [],
        }


class _BadConfidenceProvider(LLMProvider):
    name = "stub-bad-confidence"
    is_mock = True

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        return {
            "requested_action": "RETRY",
            "confidence": 1.5,
            "explanation": "overconfident",
            "reason_codes": [],
        }


class _TimeoutProvider(LLMProvider):
    name = "stub-timeout"
    is_mock = False

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        raise ProviderError("simulated timeout after 10s")


class _ExceptionProvider(LLMProvider):
    name = "stub-exception"
    is_mock = False

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        raise RuntimeError("simulated unexpected provider crash")


class _AlwaysRetryProvider(LLMProvider):
    """Deterministically recommends RETRY regardless of context - used to
    prove the rules engine still gates an agent that (correctly or not)
    always asks for the same action, independent of what a well-behaved
    heuristic would do."""

    name = "stub-always-retry"
    is_mock = True

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        return {
            "requested_action": "RETRY",
            "confidence": 0.9,
            "explanation": "[STUB] Always recommends RETRY, for testing agent/rules separation.",
            "reason_codes": ["STUB_ALWAYS_RETRY"],
        }


# ---------- 1: Valid AI output ----------

def test_valid_ai_output_returns_well_formed_recommendation():
    result = get_agent_recommendation(_payment(), MockProvider())
    assert isinstance(result, AgentRecommendation)
    assert result.transaction_id == "TXN2001"
    assert 0.0 <= result.confidence <= 1.0
    assert result.explanation
    assert result.provider == "mock"
    assert result.is_mock is True


# ---------- 2-4: action-specific recommendations ----------

def test_high_probability_first_retry_recommends_retry():
    result = get_agent_recommendation(
        _payment(recovery_probability=0.85, retry_count=0, failure_reason="network_timeout"),
        MockProvider(),
    )
    assert result.requested_action == "RETRY"
    assert "FIRST_RETRY" in result.reason_codes


def test_terminal_failure_recommends_stop():
    result = get_agent_recommendation(
        _payment(failure_reason="invalid_card", recovery_probability=0.05), MockProvider()
    )
    assert result.requested_action == "STOP"


def test_low_probability_recommends_human_review():
    result = get_agent_recommendation(
        _payment(recovery_probability=0.15, retry_count=0, failure_reason="insufficient_funds"),
        MockProvider(),
    )
    assert result.requested_action == "HUMAN_REVIEW"


# ---------- 5: invalid action rejected -> fallback ----------

def test_unsupported_action_from_provider_falls_back():
    result = get_agent_recommendation(_payment(), _UnsupportedActionProvider())
    assert result.requested_action == "HUMAN_REVIEW"
    assert "AGENT_FALLBACK" in result.reason_codes
    assert result.is_mock is True
    assert result.confidence == 0.0


# ---------- 6: confidence outside 0-1 rejected -> fallback ----------

def test_out_of_range_confidence_falls_back():
    result = get_agent_recommendation(_payment(), _BadConfidenceProvider())
    assert result.requested_action == "HUMAN_REVIEW"
    assert "AGENT_FALLBACK" in result.reason_codes


# ---------- 7: malformed provider output -> fallback ----------

def test_malformed_output_missing_fields_falls_back():
    result = get_agent_recommendation(_payment(), _MalformedProvider())
    assert result.requested_action == "HUMAN_REVIEW"
    assert "AGENT_FALLBACK" in result.reason_codes


# ---------- 8: provider timeout/error -> fallback ----------

def test_provider_error_falls_back():
    result = get_agent_recommendation(_payment(), _TimeoutProvider())
    assert result.requested_action == "HUMAN_REVIEW"
    assert result.provider == "stub-timeout"
    assert "AGENT_FALLBACK" in result.reason_codes


def test_unexpected_exception_falls_back():
    result = get_agent_recommendation(_payment(), _ExceptionProvider())
    assert result.requested_action == "HUMAN_REVIEW"
    assert "AGENT_FALLBACK" in result.reason_codes


# ---------- 9: missing API key -> safe fallback to mock provider ----------

def test_missing_api_key_falls_back_to_mock_provider():
    settings = Settings(llm_provider="anthropic", llm_api_key="", database_url="sqlite:///./x.db")
    provider = get_default_provider(settings)
    assert provider.is_mock is True
    assert provider.name == "mock"


def test_unset_provider_defaults_to_mock():
    settings = Settings(llm_provider="none", llm_api_key="", database_url="sqlite:///./x.db")
    provider = get_default_provider(settings)
    assert provider.name == "mock"


# ---------- 10: mock provider works ----------

def test_mock_provider_produces_valid_recommendation_directly():
    raw = MockProvider().generate_recommendation(
        {"transaction_id": "TXN1", "recovery_probability": 0.7, "retry_count": 0, "failure_reason": "network_timeout"}
    )
    assert raw["requested_action"] in {"RETRY", "SEND_REMINDER", "WAIT", "STOP", "HUMAN_REVIEW", "SUGGEST_ALTERNATIVE_PAYMENT"}
    assert "[MOCK]" in raw["explanation"]


# ---------- 11-13: agent + rules integration ----------

def test_ai_retry_and_rules_allow():
    result = get_recommendation_and_decision(_payment(), MockProvider(), TEST_POLICY)
    assert isinstance(result, AgentRulesResult)
    assert result.agent.requested_action == "RETRY"
    assert result.safety.decision == "ALLOW"
    assert result.final_decision == "ALLOW"


def test_ai_retry_and_rules_block_on_max_retries():
    result = get_recommendation_and_decision(
        _payment(retry_count=2), _AlwaysRetryProvider(), TEST_POLICY
    )
    assert result.agent.requested_action == "RETRY"
    assert result.safety.decision == "BLOCK"
    assert "MAX_RETRIES_REACHED" in result.safety.reason_codes
    assert result.final_decision == "BLOCK"


def test_ai_retry_and_rules_human_approval_on_high_value():
    result = get_recommendation_and_decision(
        _payment(amount=68000.0, retry_count=0), _AlwaysRetryProvider(), TEST_POLICY
    )
    assert result.agent.requested_action == "RETRY"
    assert result.safety.decision == "HUMAN_APPROVAL"
    assert result.final_decision == "HUMAN_APPROVAL"
    assert result.safety.requires_human_approval is True


# ---------- 14: AI STOP remains safe ----------

def test_ai_stop_recommendation_is_always_allowed():
    result = get_recommendation_and_decision(
        _payment(recovery_probability=0.05, retry_count=2, failure_reason="invalid_card"),
        MockProvider(),
        TEST_POLICY,
    )
    assert result.agent.requested_action == "STOP"
    assert result.safety.decision == "ALLOW"
    assert result.final_decision == "ALLOW"


# ---------- 15-17: AI/rules separation demonstrations ----------

def test_high_value_demonstrates_agent_rules_separation():
    result = get_recommendation_and_decision(
        _payment(amount=99000.0), _AlwaysRetryProvider(), TEST_POLICY
    )
    # The agent's request and the system's final outcome are different
    # concepts with different values here - proving neither is derived
    # from the other by simple pass-through.
    assert result.agent.requested_action == "RETRY"
    assert result.final_decision == "HUMAN_APPROVAL"
    assert result.final_decision != result.agent.requested_action


def test_max_retries_demonstrates_agent_rules_separation():
    result = get_recommendation_and_decision(
        _payment(retry_count=5), _AlwaysRetryProvider(), TEST_POLICY
    )
    assert result.agent.requested_action == "RETRY"
    assert result.final_decision == "BLOCK"
    assert result.final_decision != result.agent.requested_action


def test_hard_stop_failure_demonstrates_agent_rules_separation():
    result = get_recommendation_and_decision(
        _payment(failure_reason="risk_flagged", recovery_probability=0.95),
        _AlwaysRetryProvider(),
        TEST_POLICY,
    )
    assert result.agent.requested_action == "RETRY"  # agent's request, preserved for audit
    assert result.final_decision == "BLOCK"
    assert "HARD_STOP_FAILURE_REASON" in result.safety.reason_codes


# ---------- 18: deterministic mock behavior ----------

def test_mock_provider_is_deterministic():
    ctx = {"transaction_id": "TXN1", "recovery_probability": 0.72, "retry_count": 1, "failure_reason": "otp_failed"}
    r1 = MockProvider().generate_recommendation(ctx)
    r2 = MockProvider().generate_recommendation(ctx)
    assert r1 == r2


# ---------- 19: no direct execution from agent ----------

def test_agent_recommendation_has_no_execution_capability():
    """The agent module exposes no execute/charge/call-razorpay function -
    its only outputs are data objects. This test asserts the schema
    contains no execution-flavored field, and that final_decision is
    sourced from the rules engine, never copied from the agent."""
    result = get_recommendation_and_decision(
        _payment(retry_count=2), _AlwaysRetryProvider(), TEST_POLICY
    )
    assert not hasattr(result.agent, "executed")
    assert not hasattr(result.agent, "execute")
    # Disagreement case proves final_decision isn't just mirroring the agent.
    assert result.final_decision != result.agent.requested_action


# ---------- Output schema / audit-readiness ----------

def test_agent_recommendation_rejects_invalid_action_at_construction():
    with pytest.raises(Exception):
        AgentRecommendation(
            transaction_id="TXN1",
            requested_action="NOT_A_REAL_ACTION",
            confidence=0.5,
            explanation="test",
            reason_codes=[],
            provider="mock",
            is_mock=True,
            generated_at="2026-01-01T00:00:00+00:00",
        )


def test_to_audit_dict_contains_all_expected_fields():
    result = get_recommendation_and_decision(_payment(), MockProvider(), TEST_POLICY)
    audit = result.to_audit_dict()
    for field in [
        "transaction_id",
        "agent_requested_action",
        "agent_confidence",
        "agent_explanation",
        "agent_reason_codes",
        "agent_provider",
        "agent_is_mock",
        "agent_model",
        "agent_generated_at",
        "safety_decision",
        "safety_reason_codes",
        "safety_requires_human_approval",
        "safety_explanation",
        "safety_policy_version",
        "final_decision",
    ]:
        assert field in audit


# ---------- Reuses Phase 2 prediction service (no duplicated ML logic) ----------

def test_recommendation_uses_phase2_prediction_service_when_probability_omitted():
    """When recovery_probability isn't pre-supplied, the agent must call
    the real Phase 2 predict_recovery() function rather than reimplementing
    any scoring logic - this exercises that integration end-to-end."""
    payment = _payment()
    del payment["recovery_probability"]
    result = get_agent_recommendation(payment, MockProvider())
    assert isinstance(result, AgentRecommendation)
    assert result.requested_action in {"RETRY", "SEND_REMINDER", "WAIT", "STOP", "HUMAN_REVIEW"}


def test_missing_ml_artifact_still_fails_safe(monkeypatch):
    """If probability resolution itself fails (e.g. model artifact
    missing), the agent must still return a safe fallback, not raise."""
    import app.agent.service as service_module

    def _broken_resolver(payment):
        raise FileNotFoundError("simulated missing model artifact")

    monkeypatch.setattr(service_module, "_resolve_recovery_probability", _broken_resolver)

    payment = _payment()
    del payment["recovery_probability"]
    result = get_agent_recommendation(payment, MockProvider())
    assert result.requested_action == "HUMAN_REVIEW"
    assert "AGENT_FALLBACK" in result.reason_codes
