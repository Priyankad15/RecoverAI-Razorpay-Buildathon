"""
Tests for the Phase 3 deterministic safety/rules engine.

All tests pass an explicit Policy instead of relying on environment
configuration, so results are fixed and don't depend on .env contents.
"""

from __future__ import annotations

import pytest

from app.rules.enums import Decision, ReasonCode
from app.rules.engine import evaluate_recovery_action
from app.rules.policies import Policy

TEST_POLICY = Policy(
    version="test-v1",
    max_automated_retries=2,
    min_recovery_probability=0.30,
    high_value_threshold_inr=50000.0,
    hard_stop_failure_reasons=frozenset({"risk_flagged"}),
)


def _base_request(**overrides) -> dict:
    request = {
        "transaction_id": "TXN1001",
        "amount": 1000.0,
        "recovery_probability": 0.85,
        "retry_count": 0,
        "requested_action": "RETRY",
        "failure_reason": "network_timeout",
    }
    request.update(overrides)
    return request


# ---------- 1-2: straightforward ALLOW ----------

def test_valid_retry_high_probability_zero_retries_allows():
    result = evaluate_recovery_action(_base_request(), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value
    assert result.reason_codes == []
    assert result.requires_human_approval is False


def test_valid_retry_with_retry_count_one_allows():
    result = evaluate_recovery_action(_base_request(retry_count=1), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value


# ---------- 3: retry limit ----------

def test_retry_blocked_when_retry_count_equals_max():
    result = evaluate_recovery_action(_base_request(retry_count=2), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.MAX_RETRIES_REACHED.value in result.reason_codes


def test_retry_blocked_when_retry_count_exceeds_max():
    result = evaluate_recovery_action(_base_request(retry_count=5), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.MAX_RETRIES_REACHED.value in result.reason_codes


# ---------- 4: probability floor ----------

def test_retry_blocked_when_probability_below_minimum():
    result = evaluate_recovery_action(_base_request(recovery_probability=0.29), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.LOW_RECOVERY_PROBABILITY.value in result.reason_codes


# ---------- 5: high value ----------

def test_high_value_transaction_requires_human_approval():
    result = evaluate_recovery_action(_base_request(amount=75000.0), TEST_POLICY)
    assert result.decision == Decision.HUMAN_APPROVAL.value
    assert ReasonCode.HIGH_VALUE_TRANSACTION.value in result.reason_codes
    assert result.requires_human_approval is True


# ---------- 6-9: invalid input fails closed ----------

def test_negative_amount_blocks():
    result = evaluate_recovery_action(_base_request(amount=-100.0), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_zero_amount_blocks():
    result = evaluate_recovery_action(_base_request(amount=0.0), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_probability_below_zero_blocks():
    result = evaluate_recovery_action(_base_request(recovery_probability=-0.1), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_probability_above_one_blocks():
    result = evaluate_recovery_action(_base_request(recovery_probability=1.1), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_negative_retry_count_blocks():
    result = evaluate_recovery_action(_base_request(retry_count=-1), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_empty_transaction_id_blocks():
    result = evaluate_recovery_action(_base_request(transaction_id=""), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_whitespace_only_transaction_id_blocks():
    result = evaluate_recovery_action(_base_request(transaction_id="   "), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_wrong_type_amount_blocks():
    result = evaluate_recovery_action(_base_request(amount="not_a_number"), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


# ---------- 10: unsupported action ----------

def test_unsupported_action_blocks():
    result = evaluate_recovery_action(_base_request(requested_action="TRANSFER_ALL_FUNDS"), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.UNSUPPORTED_ACTION.value in result.reason_codes


def test_lowercase_action_string_is_unsupported():
    """Action matching must be exact - engine must not silently normalize
    case, since that would mean accepting strings outside the strict enum."""
    result = evaluate_recovery_action(_base_request(requested_action="retry"), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.UNSUPPORTED_ACTION.value in result.reason_codes


# ---------- 11-12: passive actions always allowed ----------

def test_stop_action_allows():
    result = evaluate_recovery_action(_base_request(requested_action="STOP"), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value
    assert result.requires_human_approval is False


def test_human_review_action_allows():
    result = evaluate_recovery_action(_base_request(requested_action="HUMAN_REVIEW"), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value


def test_wait_action_allows():
    result = evaluate_recovery_action(_base_request(requested_action="WAIT"), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value


def test_passive_actions_bypass_monetary_gates():
    """A STOP request with retry_count way over the limit and probability
    at zero must still ALLOW - it's passive and never touches money."""
    result = evaluate_recovery_action(
        _base_request(requested_action="STOP", retry_count=99, recovery_probability=0.0, amount=999999.0),
        TEST_POLICY,
    )
    assert result.decision == Decision.ALLOW.value


# ---------- 13: boundary - probability exactly at minimum ----------

def test_probability_exactly_at_minimum_allows():
    """MIN_RECOVERY_PROBABILITY is an inclusive floor: probability >= min passes."""
    result = evaluate_recovery_action(_base_request(recovery_probability=0.30), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value
    assert ReasonCode.LOW_RECOVERY_PROBABILITY.value not in result.reason_codes


def test_probability_just_below_minimum_blocks():
    result = evaluate_recovery_action(_base_request(recovery_probability=0.2999), TEST_POLICY)
    assert result.decision == Decision.BLOCK.value


# ---------- 14: boundary - amount exactly at high-value threshold ----------

def test_amount_exactly_at_high_value_threshold_requires_approval():
    """HIGH_VALUE_THRESHOLD is inclusive: amount >= threshold triggers approval."""
    result = evaluate_recovery_action(_base_request(amount=50000.0), TEST_POLICY)
    assert result.decision == Decision.HUMAN_APPROVAL.value
    assert ReasonCode.HIGH_VALUE_TRANSACTION.value in result.reason_codes


def test_amount_just_below_high_value_threshold_allows():
    result = evaluate_recovery_action(_base_request(amount=49999.99), TEST_POLICY)
    assert result.decision == Decision.ALLOW.value


# ---------- 15: simultaneous triggers - deterministic precedence ----------

def test_retry_limit_and_high_value_together_block_takes_precedence():
    """Decision must resolve to BLOCK (precedence), while reason_codes
    retains every condition that actually triggered, for full audit
    transparency - not just the winning one."""
    result = evaluate_recovery_action(
        _base_request(retry_count=2, amount=75000.0), TEST_POLICY
    )
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.MAX_RETRIES_REACHED.value in result.reason_codes
    assert ReasonCode.HIGH_VALUE_TRANSACTION.value in result.reason_codes
    assert result.requires_human_approval is False


def test_low_probability_and_high_value_together_block_takes_precedence():
    result = evaluate_recovery_action(
        _base_request(recovery_probability=0.1, amount=75000.0), TEST_POLICY
    )
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.LOW_RECOVERY_PROBABILITY.value in result.reason_codes
    assert result.requires_human_approval is False


def test_hard_stop_failure_reason_blocks_even_with_high_probability():
    result = evaluate_recovery_action(
        _base_request(failure_reason="risk_flagged", recovery_probability=0.95, retry_count=0),
        TEST_POLICY,
    )
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.HARD_STOP_FAILURE_REASON.value in result.reason_codes


# ---------- 16: malformed / unknown input fails closed ----------

def test_empty_dict_input_blocks():
    result = evaluate_recovery_action({}, TEST_POLICY)
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


def test_none_values_block():
    result = evaluate_recovery_action(
        {
            "transaction_id": None,
            "amount": None,
            "recovery_probability": None,
            "retry_count": None,
            "requested_action": None,
            "failure_reason": None,
        },
        TEST_POLICY,
    )
    assert result.decision == Decision.BLOCK.value


def test_completely_wrong_shape_input_blocks():
    result = evaluate_recovery_action({"unexpected": "shape"}, TEST_POLICY)
    assert result.decision == Decision.BLOCK.value


def test_extra_unexpected_fields_are_rejected():
    """Strict input model rejects unknown fields rather than silently
    ignoring them - important so a caller can't sneak in an unvalidated
    field that later code might accidentally trust."""
    result = evaluate_recovery_action(
        _base_request(injected_discount_percent=100), TEST_POLICY
    )
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.INVALID_INPUT.value in result.reason_codes


# ---------- SUGGEST_ALTERNATIVE_PAYMENT is also monetary-gated ----------

def test_suggest_alternative_payment_not_retry_gated_but_high_value_gated():
    """SUGGEST_ALTERNATIVE_PAYMENT doesn't re-attempt the same charge, so
    only RETRY is subject to the retry-count limit - but it's still an
    active/monetary action, so it remains gated by the high-value
    threshold."""
    high_retry = evaluate_recovery_action(
        _base_request(requested_action="SUGGEST_ALTERNATIVE_PAYMENT", retry_count=10), TEST_POLICY
    )
    assert high_retry.decision == Decision.ALLOW.value


def test_suggest_alternative_payment_gated_by_high_value():
    result = evaluate_recovery_action(
        _base_request(requested_action="SUGGEST_ALTERNATIVE_PAYMENT", amount=60000.0), TEST_POLICY
    )
    assert result.decision == Decision.HUMAN_APPROVAL.value


def test_send_reminder_allowed_normally_but_gated_by_high_value():
    normal = evaluate_recovery_action(_base_request(requested_action="SEND_REMINDER"), TEST_POLICY)
    assert normal.decision == Decision.ALLOW.value

    high_value = evaluate_recovery_action(
        _base_request(requested_action="SEND_REMINDER", amount=60000.0), TEST_POLICY
    )
    assert high_value.decision == Decision.HUMAN_APPROVAL.value


def test_send_reminder_not_gated_by_retry_limit():
    """SEND_REMINDER doesn't re-attempt a charge, so the retry-count limit
    (which exists specifically to cap repeated charge attempts) doesn't
    apply to it - only RETRY is retry-gated."""
    result = evaluate_recovery_action(
        _base_request(requested_action="SEND_REMINDER", retry_count=10), TEST_POLICY
    )
    assert result.decision == Decision.ALLOW.value


# ---------- Output schema / audit compatibility ----------

def test_decision_output_has_all_required_fields():
    result = evaluate_recovery_action(_base_request(), TEST_POLICY)
    data = result.model_dump()
    for field in [
        "transaction_id",
        "requested_action",
        "decision",
        "reason_codes",
        "explanation",
        "requires_human_approval",
        "policy_version",
        "evaluated_at",
    ]:
        assert field in data

    assert isinstance(data["explanation"], str) and len(data["explanation"]) > 0
    assert data["policy_version"] == TEST_POLICY.version


def test_decision_is_json_serializable():
    import json

    result = evaluate_recovery_action(_base_request(), TEST_POLICY)
    serialized = json.dumps(result.model_dump())
    assert "ALLOW" in serialized


# ---------- Fail-closed on unexpected internal error ----------

def test_engine_never_raises_and_fails_closed_on_broken_policy():
    class BrokenPolicy:
        version = "broken"
        # Deliberately missing every attribute the engine reads, to
        # simulate an unexpected internal failure during evaluation.

    result = evaluate_recovery_action(_base_request(), BrokenPolicy())  # type: ignore[arg-type]
    assert result.decision == Decision.BLOCK.value
    assert ReasonCode.EVALUATION_ERROR.value in result.reason_codes


# ---------- Determinism / reproducibility ----------

def test_same_input_always_produces_same_decision():
    r1 = evaluate_recovery_action(_base_request(), TEST_POLICY)
    r2 = evaluate_recovery_action(_base_request(), TEST_POLICY)
    assert r1.decision == r2.decision
    assert r1.reason_codes == r2.reason_codes
    assert r1.explanation == r2.explanation


def test_default_policy_matches_documented_defaults():
    from app.rules.policies import get_active_policy

    policy = get_active_policy()
    assert policy.max_automated_retries == 2
    assert policy.min_recovery_probability == pytest.approx(0.30)
    assert policy.high_value_threshold_inr == pytest.approx(50000.0)
