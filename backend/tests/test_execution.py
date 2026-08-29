"""
Tests for the Phase 5 bounded recovery execution layer.

No test depends on a real external LLM API or a live Razorpay
connection. Everything runs through MockProvider, the AlwaysRetry test
stub from Phase 4, and RecoveryExecutor's deterministic
forced_outcome/simulation_outcome mechanism.
"""

from __future__ import annotations

import pytest

from app.agent.providers import LLMProvider, MockProvider
from app.execution.enums import ExecutionStatus, ForcedOutcome
from app.execution.executor import RecoveryExecutor, UnsupportedExecutionAction
from app.execution.revenue import compute_batch_revenue_metrics
from app.execution.service import recover_transaction
from app.rules.policies import Policy
from tests.test_agent import _AlwaysRetryProvider, _ExceptionProvider

TEST_POLICY = Policy(
    version="test-v1",
    max_automated_retries=2,
    min_recovery_probability=0.30,
    high_value_threshold_inr=50000.0,
    hard_stop_failure_reasons=frozenset({"risk_flagged"}),
)


def _payment(**overrides) -> dict:
    payment = {
        "transaction_id": "TXN3001",
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
        "recovery_probability": 0.85,
    }
    payment.update(overrides)
    return payment


# ---------- RecoveryExecutor unit tests ----------

def test_executor_rejects_unsupported_action():
    with pytest.raises(UnsupportedExecutionAction):
        RecoveryExecutor().execute("TRANSFER_ALL_FUNDS", {"amount": 100.0})


def test_executor_retry_default_success():
    result = RecoveryExecutor().execute("RETRY", {"amount": 5000.0})
    assert result.status == ExecutionStatus.SUCCESS.value
    assert result.recovered_amount == 5000.0
    assert result.simulation_mode is True
    assert "[SIMULATION / TEST MODE]" in result.detail


def test_executor_retry_forced_failure():
    result = RecoveryExecutor().execute("RETRY", {"amount": 5000.0}, forced_outcome=ForcedOutcome.FAILURE.value)
    assert result.status == ExecutionStatus.FAILED.value
    assert result.recovered_amount == 0.0
    assert result.failure_reason


def test_executor_retry_outcome_from_transaction_field():
    result = RecoveryExecutor().execute("RETRY", {"amount": 5000.0, "simulation_outcome": "FAILURE"})
    assert result.status == ExecutionStatus.FAILED.value


def test_executor_forced_outcome_overrides_transaction_field():
    result = RecoveryExecutor().execute(
        "RETRY", {"amount": 5000.0, "simulation_outcome": "FAILURE"}, forced_outcome=ForcedOutcome.SUCCESS.value
    )
    assert result.status == ExecutionStatus.SUCCESS.value


def test_executor_passive_actions_never_move_money():
    for action in ["STOP", "WAIT", "HUMAN_REVIEW"]:
        result = RecoveryExecutor().execute(action, {"amount": 99999.0})
        assert result.status == ExecutionStatus.COMPLETED.value
        assert result.recovered_amount == 0.0


def test_executor_outreach_actions_never_move_money():
    for action in ["SEND_REMINDER", "SUGGEST_ALTERNATIVE_PAYMENT"]:
        result = RecoveryExecutor().execute(action, {"amount": 99999.0})
        assert result.status == ExecutionStatus.COMPLETED.value
        assert result.recovered_amount == 0.0


# ---------- 1-2: ALLOW + execution outcomes ----------

def test_allow_and_successful_retry():
    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, forced_outcome=ForcedOutcome.SUCCESS.value,
        idempotency_store={},
    )
    assert result.safety.decision == "ALLOW"
    assert result.recovery_attempt.execution_status == ExecutionStatus.SUCCESS.value
    assert result.recovery_attempt.recovered_amount == 4999.0


def test_allow_and_failed_retry():
    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, forced_outcome=ForcedOutcome.FAILURE.value,
        idempotency_store={},
    )
    assert result.safety.decision == "ALLOW"
    assert result.recovery_attempt.execution_status == ExecutionStatus.FAILED.value
    assert result.recovery_attempt.recovered_amount == 0.0
    assert result.recovery_attempt.failure_reason


# ---------- 3-4: BLOCK / HUMAN_APPROVAL never execute ----------

def test_block_prevents_execution():
    class SpyExecutor(RecoveryExecutor):
        called = False

        def execute(self, *args, **kwargs):
            SpyExecutor.called = True
            return super().execute(*args, **kwargs)

    result = recover_transaction(
        _payment(retry_count=2), _AlwaysRetryProvider(), TEST_POLICY,
        executor=SpyExecutor(), idempotency_store={},
    )
    assert result.safety.decision == "BLOCK"
    assert result.recovery_attempt.execution_status == ExecutionStatus.BLOCKED.value
    assert SpyExecutor.called is False, "executor must never be called when rules BLOCK"
    assert result.recovery_attempt.recovered_amount == 0.0


def test_human_approval_prevents_automatic_execution():
    class SpyExecutor(RecoveryExecutor):
        called = False

        def execute(self, *args, **kwargs):
            SpyExecutor.called = True
            return super().execute(*args, **kwargs)

    result = recover_transaction(
        _payment(amount=68000.0), _AlwaysRetryProvider(), TEST_POLICY,
        executor=SpyExecutor(), idempotency_store={},
    )
    assert result.safety.decision == "HUMAN_APPROVAL"
    assert result.recovery_attempt.execution_status == ExecutionStatus.PENDING_HUMAN_APPROVAL.value
    assert SpyExecutor.called is False, "executor must never be called when rules require HUMAN_APPROVAL"
    assert result.recovery_attempt.recovered_amount == 0.0


# ---------- 5: unsupported action rejected ----------

def test_unsupported_action_never_reaches_execution_success():
    """If somehow an unapproved action string reached the executor, it
    must raise, not silently succeed. Exercises the executor's own closed
    action set directly, independent of the rules engine."""
    with pytest.raises(UnsupportedExecutionAction):
        RecoveryExecutor().execute("SOMETHING_UNSUPPORTED", {"amount": 100.0})


# ---------- 6-8: revenue truthfulness ----------

def test_simulation_success_records_recovered_amount():
    result = recover_transaction(
        _payment(amount=1234.0), MockProvider(), TEST_POLICY,
        forced_outcome=ForcedOutcome.SUCCESS.value, idempotency_store={},
    )
    assert result.recovery_attempt.recovered_amount == 1234.0


def test_simulation_failure_records_zero_recovered():
    result = recover_transaction(
        _payment(amount=1234.0), MockProvider(), TEST_POLICY,
        forced_outcome=ForcedOutcome.FAILURE.value, idempotency_store={},
    )
    assert result.recovery_attempt.recovered_amount == 0.0


def test_failed_execution_does_not_claim_recovery():
    result = recover_transaction(
        _payment(amount=1234.0), MockProvider(), TEST_POLICY,
        forced_outcome=ForcedOutcome.FAILURE.value, idempotency_store={},
    )
    assert result.recovery_attempt.execution_status != ExecutionStatus.SUCCESS.value
    assert result.recovery_attempt.recovered_amount == 0.0


# ---------- 9: retry count respected (via rules engine, not re-implemented here) ----------

def test_retry_count_respected_blocks_execution():
    result = recover_transaction(
        _payment(retry_count=2), _AlwaysRetryProvider(), TEST_POLICY, idempotency_store={},
    )
    assert result.safety.decision == "BLOCK"
    assert "MAX_RETRIES_REACHED" in result.safety.reason_codes
    assert result.recovery_attempt.execution_status == ExecutionStatus.BLOCKED.value


# ---------- 10: duplicate execution prevented ----------

def test_duplicate_execution_prevented_by_idempotency():
    store: dict = {}
    r1 = recover_transaction(
        _payment(transaction_id="TXN-DUP"), MockProvider(), TEST_POLICY,
        forced_outcome=ForcedOutcome.SUCCESS.value, idempotency_store=store,
    )
    r2 = recover_transaction(
        _payment(transaction_id="TXN-DUP"), MockProvider(), TEST_POLICY,
        forced_outcome=ForcedOutcome.FAILURE.value,  # even with a different outcome requested
        idempotency_store=store,
    )
    assert r1.idempotent_replay is False
    assert r2.idempotent_replay is True
    # Second call must return the FIRST result, not re-execute with the new outcome.
    assert r2.recovery_attempt.id == r1.recovery_attempt.id
    assert r2.recovery_attempt.execution_status == ExecutionStatus.SUCCESS.value


def test_custom_idempotency_key_respected():
    store: dict = {}
    payment = _payment(transaction_id="TXN-KEYED", idempotency_key="custom-key-1")
    r1 = recover_transaction(payment, MockProvider(), TEST_POLICY, idempotency_store=store)
    r2 = recover_transaction(payment, MockProvider(), TEST_POLICY, idempotency_store=store)
    assert r2.idempotent_replay is True
    assert "custom-key-1" in store


# ---------- 11: missing transaction handled safely ----------

def test_missing_transaction_id_handled_safely():
    result = recover_transaction({"amount": 100.0}, MockProvider(), TEST_POLICY, idempotency_store={})
    assert result.safety.decision == "BLOCK"
    assert result.recovery_attempt.execution_status == ExecutionStatus.NOT_EXECUTED.value
    assert result.recovery_attempt.recovered_amount == 0.0


def test_none_payment_handled_safely():
    result = recover_transaction(None, MockProvider(), TEST_POLICY, idempotency_store={})  # type: ignore[arg-type]
    assert result.safety.decision == "BLOCK"
    assert result.recovery_attempt.execution_status == ExecutionStatus.NOT_EXECUTED.value


# ---------- 12: executor exception handled safely ----------

def test_executor_exception_fails_closed_not_success():
    class BrokenExecutor(RecoveryExecutor):
        def execute(self, *args, **kwargs):
            raise RuntimeError("simulated adapter crash")

    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, executor=BrokenExecutor(), idempotency_store={},
    )
    assert result.safety.decision == "ALLOW"  # rules said fine, but execution itself broke
    assert result.recovery_attempt.execution_status == ExecutionStatus.NOT_EXECUTED.value
    assert result.recovery_attempt.execution_status != ExecutionStatus.SUCCESS.value
    assert result.recovery_attempt.recovered_amount == 0.0


def test_agent_provider_exception_fails_closed():
    """Even if the LLM provider itself explodes, recover_transaction must
    never raise or authorize execution."""
    result = recover_transaction(_payment(), _ExceptionProvider(), TEST_POLICY, idempotency_store={})
    # ExceptionProvider triggers the agent's own HUMAN_REVIEW fallback,
    # which is a passive action the rules engine always ALLOWs.
    assert result.recovery_attempt.execution_status in {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.NOT_EXECUTED.value,
    }
    assert result.recovery_attempt.recovered_amount == 0.0


# ---------- 13-16: audit events created for every path ----------

def test_audit_event_created_for_success():
    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, forced_outcome=ForcedOutcome.SUCCESS.value,
        idempotency_store={},
    )
    event_types = [e.event_type for e in result.audit_events]
    assert "RECOVERY_RECOMMENDED" in event_types
    assert "RECOVERY_EXECUTED" in event_types


def test_audit_event_created_for_failure():
    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, forced_outcome=ForcedOutcome.FAILURE.value,
        idempotency_store={},
    )
    event_types = [e.event_type for e in result.audit_events]
    assert "RECOVERY_FAILED" in event_types


def test_audit_event_created_for_blocked():
    result = recover_transaction(
        _payment(retry_count=2), _AlwaysRetryProvider(), TEST_POLICY, idempotency_store={},
    )
    event_types = [e.event_type for e in result.audit_events]
    assert "RECOVERY_BLOCKED" in event_types
    blocked_event = next(e for e in result.audit_events if e.event_type == "RECOVERY_BLOCKED")
    assert blocked_event.execution_status == ExecutionStatus.BLOCKED.value
    assert "MAX_RETRIES_REACHED" in blocked_event.reason_codes


def test_audit_event_created_for_human_approval():
    result = recover_transaction(
        _payment(amount=68000.0), _AlwaysRetryProvider(), TEST_POLICY, idempotency_store={},
    )
    event_types = [e.event_type for e in result.audit_events]
    assert "RECOVERY_APPROVAL_REQUIRED" in event_types


# ---------- 17-19: revenue accounting correctness ----------

def test_recovered_revenue_calculated_correctly_across_batch():
    store: dict = {}
    results = [
        recover_transaction(
            _payment(transaction_id="TXN-B1", amount=1000.0), MockProvider(), TEST_POLICY,
            forced_outcome=ForcedOutcome.SUCCESS.value, idempotency_store=store,
        ),
        recover_transaction(
            _payment(transaction_id="TXN-B2", amount=2000.0), MockProvider(), TEST_POLICY,
            forced_outcome=ForcedOutcome.FAILURE.value, idempotency_store=store,
        ),
        recover_transaction(
            _payment(transaction_id="TXN-B3", amount=3000.0, retry_count=2), _AlwaysRetryProvider(),
            TEST_POLICY, idempotency_store=store,
        ),
        recover_transaction(
            _payment(transaction_id="TXN-B4", amount=4000.0), MockProvider(), TEST_POLICY,
            forced_outcome=ForcedOutcome.SUCCESS.value, idempotency_store=store,
        ),
    ]
    metrics = compute_batch_revenue_metrics(results)
    assert metrics["amount_at_risk_inr"] == 10000.0
    assert metrics["recovered_amount_inr"] == 5000.0  # only TXN-B1 (1000) + TXN-B4 (4000)
    assert metrics["counts"]["success"] == 2
    assert metrics["counts"]["failed"] == 1
    assert metrics["counts"]["blocked"] == 1


def test_failed_amount_not_counted_as_recovered():
    result = recover_transaction(
        _payment(amount=5000.0), MockProvider(), TEST_POLICY, forced_outcome=ForcedOutcome.FAILURE.value,
        idempotency_store={},
    )
    metrics = compute_batch_revenue_metrics([result])
    assert metrics["recovered_amount_inr"] == 0.0
    assert metrics["amount_at_risk_inr"] == 5000.0


def test_human_approved_amount_not_counted_as_recovered():
    result = recover_transaction(
        _payment(amount=68000.0), _AlwaysRetryProvider(), TEST_POLICY, idempotency_store={},
    )
    metrics = compute_batch_revenue_metrics([result])
    assert metrics["recovered_amount_inr"] == 0.0
    assert metrics["potentially_recoverable_amount_inr"] == 68000.0  # HUMAN_APPROVAL still "in play"


# ---------- 20: simulation clearly marked ----------

def test_execution_result_and_attempt_marked_as_simulation():
    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, forced_outcome=ForcedOutcome.SUCCESS.value,
        idempotency_store={},
    )
    assert result.recovery_attempt.simulation_mode is True
    executed_event = next(e for e in result.audit_events if e.event_type == "RECOVERY_EXECUTED")
    assert executed_event.simulation_mode is True
    assert "[SIMULATION / TEST MODE]" in executed_event.explanation


# ---------- Demo fixtures A-D ----------

def test_demo_a_successful_recovery():
    from scripts.demo_fixtures import run_demo_a

    result = run_demo_a()
    assert result.safety.decision == "ALLOW"
    assert result.recovery_attempt.execution_status == ExecutionStatus.SUCCESS.value
    assert result.recovery_attempt.recovered_amount == 4999.0


def test_demo_b_failed_recovery():
    from scripts.demo_fixtures import run_demo_b

    result = run_demo_b()
    assert result.safety.decision == "ALLOW"
    assert result.recovery_attempt.execution_status == ExecutionStatus.FAILED.value
    assert result.recovery_attempt.recovered_amount == 0.0


def test_demo_c_blocked_max_retries():
    from scripts.demo_fixtures import run_demo_c

    result = run_demo_c()
    assert result.agent.requested_action == "RETRY"
    assert result.safety.decision == "BLOCK"
    assert "MAX_RETRIES_REACHED" in result.safety.reason_codes
    assert result.recovery_attempt.execution_status == ExecutionStatus.BLOCKED.value


def test_demo_d_human_approval_high_value():
    from scripts.demo_fixtures import run_demo_d

    result = run_demo_d()
    assert result.agent.requested_action == "RETRY"
    assert result.safety.decision == "HUMAN_APPROVAL"
    assert result.recovery_attempt.execution_status == ExecutionStatus.PENDING_HUMAN_APPROVAL.value
    assert result.recovery_attempt.recovered_amount == 0.0


# ---------- Phase 3/4 non-duplication sanity checks ----------

def test_executor_never_reevaluates_safety_rules_itself():
    """The executor has no imports from app.rules - it cannot possibly
    re-implement or diverge from Phase 3's policy."""
    import app.execution.executor as executor_module

    source = open(executor_module.__file__).read()
    assert "evaluate_recovery_action" not in source
    assert "min_recovery_probability" not in source
    assert "max_automated_retries" not in source
