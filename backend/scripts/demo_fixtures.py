"""
Deterministic demo fixtures (DEMO-A through DEMO-D from the Phase 5 spec).

All amounts, probabilities, and outcomes are fixed and reproducible -
nothing here is random. Every fixture uses the MockProvider (or, for
DEMO-C, the existing AlwaysRetryProvider test stub, imported directly
so it is not duplicated) so the same input always produces the same
demo output.

DEMO/TEST/SIMULATION ONLY - no real money, no real Razorpay calls.
"""

from __future__ import annotations

from app.agent.providers import MockProvider
from app.execution.enums import ForcedOutcome
from app.execution.service import recover_transaction


def _demo_payment(**overrides) -> dict:
    payment = {
        "transaction_id": "TXN-DEMO",
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
        "recovery_probability": 0.84,
    }
    payment.update(overrides)
    return payment


def run_demo_a(idempotency_store: dict | None = None):
    """DEMO-A: normal successful recovery. AI RETRY, rules ALLOW,
    execution SUCCESS, recovered = amount."""
    payment = _demo_payment(transaction_id="TXN-DEMO-A", retry_count=0)
    return recover_transaction(
        payment,
        provider=MockProvider(),
        idempotency_store=idempotency_store if idempotency_store is not None else {},
        forced_outcome=ForcedOutcome.SUCCESS.value,
    )


def run_demo_b(idempotency_store: dict | None = None):
    """DEMO-B: graceful failure. AI RETRY, rules ALLOW, execution
    FAILURE, recovered = 0."""
    payment = _demo_payment(transaction_id="TXN-DEMO-B", retry_count=0)
    return recover_transaction(
        payment,
        provider=MockProvider(),
        idempotency_store=idempotency_store if idempotency_store is not None else {},
        forced_outcome=ForcedOutcome.FAILURE.value,
    )


def run_demo_c(idempotency_store: dict | None = None):
    """DEMO-C: retries exhausted. AI RETRY (via the AlwaysRetry test
    stub - the default MockProvider would itself avoid requesting RETRY
    at retry_count=2, so this uses the same stub already established in
    Phase 4's tests to force a genuine AI/rules disagreement), rules
    BLOCK (MAX_RETRIES_REACHED), execution never runs."""
    from tests.test_agent import _AlwaysRetryProvider  # existing Phase 4 test stub, reused not duplicated

    payment = _demo_payment(transaction_id="TXN-DEMO-C", retry_count=2)
    return recover_transaction(
        payment,
        provider=_AlwaysRetryProvider(),
        idempotency_store=idempotency_store if idempotency_store is not None else {},
    )


def run_demo_d(idempotency_store: dict | None = None):
    """DEMO-D: high-value transaction. AI RETRY, rules HUMAN_APPROVAL,
    execution never runs automatically."""
    payment = _demo_payment(transaction_id="TXN-DEMO-D", amount=68000.0, retry_count=0)
    return recover_transaction(
        payment,
        provider=MockProvider(),
        idempotency_store=idempotency_store if idempotency_store is not None else {},
    )
