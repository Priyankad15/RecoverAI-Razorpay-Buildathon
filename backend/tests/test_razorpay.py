"""
Tests for the Phase 7 Razorpay Test Mode integration.

No test makes a real network call to Razorpay - RazorpayClient is always
either mocked/faked, or its construction is tested in isolation (auth
config only, no request sent). This matches Phase 7's explicit testing
requirement: "Do NOT require real Razorpay API calls for the normal test
suite."
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.providers import MockProvider
from app.db import repository
from app.db.models import Base, RecoveryAttempt
from app.db.session import get_db
from app.execution.enums import ExecutionStatus
from app.execution.executor import RecoveryExecutor, SimulationExecutor, UnsupportedExecutionAction
from app.execution.factory import get_executor
from app.execution.service import recover_transaction
from app.integrations.razorpay.client import PaymentLinkResult, RazorpayClient, RazorpayClientError
from app.integrations.razorpay.executor import (
    RazorpayConfigurationError,
    RazorpayTestExecutor,
    build_razorpay_test_executor,
)
from app.integrations.razorpay.webhook_security import verify_webhook_signature
from app.main import app
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
        "transaction_id": "TXN-RZP-1",
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


# ---------- Fakes (no network) ----------


class FakePaymentLinkClient:
    """Stands in for RazorpayClient. Records calls; never touches the network."""

    def __init__(self, link_id="plink_fake123", short_url="https://rzp.io/i/fake123", fail=None, malformed=False):
        self.calls: list[dict] = []
        self._link_id = link_id
        self._short_url = short_url
        self._fail = fail  # a RazorpayClientError to raise, if set
        self._malformed = malformed

    def create_payment_link(self, amount_inr, reference_id, description, currency="INR", customer=None, notes=None):
        self.calls.append({"amount_inr": amount_inr, "reference_id": reference_id, "notes": notes})
        if self._fail:
            raise self._fail
        if self._malformed:
            raise RazorpayClientError("Malformed Razorpay payment_link response: missing/invalid field ('id')")
        return PaymentLinkResult(
            id=self._link_id,
            short_url=self._short_url,
            reference_id=reference_id,
            status="created",
            amount=amount_inr,
            raw_status_field="created",
        )

    def fetch_payment_link(self, payment_link_id):
        raise NotImplementedError


class SpyExecutor(RecoveryExecutor):
    """Records whether it was ever called - used to prove BLOCK/HUMAN_APPROVAL
    never reach the executor, exactly like Phase 5's equivalent test."""

    called = False

    def execute(self, *args, **kwargs):
        SpyExecutor.called = True
        return super().execute(*args, **kwargs)


# ---------- 1: Razorpay client authentication configuration ----------


def test_client_requires_both_credentials():
    with pytest.raises(RazorpayClientError):
        RazorpayClient(key_id="", key_secret="secret", base_url="https://api.razorpay.com/v1")
    with pytest.raises(RazorpayClientError):
        RazorpayClient(key_id="key", key_secret="", base_url="https://api.razorpay.com/v1")


def test_client_constructs_with_both_credentials():
    client = RazorpayClient(key_id="rzp_test_key", key_secret="secret", base_url="https://api.razorpay.com/v1")
    assert client is not None


# ---------- 2: Payment Link creation ----------


def test_payment_link_creation_success():
    fake = FakePaymentLinkClient()
    executor = RazorpayTestExecutor(fake)
    result = executor.execute("RETRY", _payment(amount=4999.0))

    assert result.status == ExecutionStatus.COMPLETED.value
    assert result.execution_mode == "RAZORPAY_TEST_MODE"
    assert result.simulation_mode is False
    assert result.razorpay_payment_link_id == "plink_fake123"
    assert result.razorpay_payment_link_url == "https://rzp.io/i/fake123"
    assert "[RAZORPAY TEST MODE]" in result.detail
    assert len(fake.calls) == 1
    assert fake.calls[0]["reference_id"] == "recoverai-TXN-RZP-1"


# ---------- Payment Link creation is NOT recovered revenue ----------


def test_payment_link_creation_records_zero_recovered_amount():
    fake = FakePaymentLinkClient()
    executor = RazorpayTestExecutor(fake)
    result = executor.execute("RETRY", _payment(amount=4999.0))
    assert result.recovered_amount == 0.0
    assert result.status != ExecutionStatus.SUCCESS.value


# ---------- 3: Payment Link creation failure ----------


def test_payment_link_creation_failure_propagates():
    fake = FakePaymentLinkClient(fail=RazorpayClientError("Razorpay API returned 400"))
    executor = RazorpayTestExecutor(fake)
    with pytest.raises(RazorpayClientError):
        executor.execute("RETRY", _payment())


# ---------- 4: Timeout ----------


def test_timeout_propagates_as_client_error():
    fake = FakePaymentLinkClient(fail=RazorpayClientError("Razorpay API request timed out (POST /payment_links)"))
    executor = RazorpayTestExecutor(fake)
    with pytest.raises(RazorpayClientError, match="timed out"):
        executor.execute("RETRY", _payment())


# ---------- 5: Malformed Razorpay response ----------


def test_malformed_response_raises_client_error():
    fake = FakePaymentLinkClient(malformed=True)
    executor = RazorpayTestExecutor(fake)
    with pytest.raises(RazorpayClientError, match="Malformed"):
        executor.execute("RETRY", _payment())


def test_client_parse_raises_on_missing_fields():
    client = RazorpayClient(key_id="k", key_secret="s", base_url="https://api.razorpay.com/v1")
    with pytest.raises(RazorpayClientError):
        client._parse_payment_link({"id": "plink_1"})  # missing status/amount


# ---------- 6: Duplicate/idempotent request ----------


def test_duplicate_recovery_request_does_not_create_second_payment_link():
    fake = FakePaymentLinkClient()
    executor = RazorpayTestExecutor(fake)
    store: dict = {}

    r1 = recover_transaction(_payment(transaction_id="TXN-RZP-DUP"), MockProvider(), TEST_POLICY, executor=executor, idempotency_store=store)
    r2 = recover_transaction(_payment(transaction_id="TXN-RZP-DUP"), MockProvider(), TEST_POLICY, executor=executor, idempotency_store=store)

    assert r1.idempotent_replay is False
    assert r2.idempotent_replay is True
    assert len(fake.calls) == 1  # only one Payment Link ever created


# ---------- 7-8: BLOCK / HUMAN_APPROVAL prevent the Razorpay call ----------


def test_block_prevents_razorpay_call():
    from tests.test_agent import _AlwaysRetryProvider

    SpyExecutor.called = False
    fake = FakePaymentLinkClient()

    class SpyRazorpayExecutor(RazorpayTestExecutor):
        def execute(self, *args, **kwargs):
            SpyExecutor.called = True
            return super().execute(*args, **kwargs)

    result = recover_transaction(
        _payment(retry_count=2), _AlwaysRetryProvider(), TEST_POLICY,
        executor=SpyRazorpayExecutor(fake), idempotency_store={},
    )
    assert result.safety.decision == "BLOCK"
    assert SpyExecutor.called is False
    assert len(fake.calls) == 0


def test_human_approval_prevents_razorpay_call():
    from tests.test_agent import _AlwaysRetryProvider

    SpyExecutor.called = False
    fake = FakePaymentLinkClient()

    class SpyRazorpayExecutor(RazorpayTestExecutor):
        def execute(self, *args, **kwargs):
            SpyExecutor.called = True
            return super().execute(*args, **kwargs)

    result = recover_transaction(
        _payment(amount=68000.0), _AlwaysRetryProvider(), TEST_POLICY,
        executor=SpyRazorpayExecutor(fake), idempotency_store={},
    )
    assert result.safety.decision == "HUMAN_APPROVAL"
    assert SpyExecutor.called is False
    assert len(fake.calls) == 0


# ---------- 9: ALLOW calls the Razorpay adapter ----------


def test_allow_calls_razorpay_adapter():
    fake = FakePaymentLinkClient()
    result = recover_transaction(
        _payment(), MockProvider(), TEST_POLICY, executor=RazorpayTestExecutor(fake), idempotency_store={},
    )
    assert result.safety.decision == "ALLOW"
    assert len(fake.calls) == 1
    assert result.recovery_attempt.execution_mode == "RAZORPAY_TEST_MODE"


# ---------- 10-12: revenue accounting truthfulness ----------


def test_payment_link_creation_does_not_count_as_recovered_revenue():
    fake = FakePaymentLinkClient()
    result = recover_transaction(
        _payment(amount=7000.0), MockProvider(), TEST_POLICY, executor=RazorpayTestExecutor(fake), idempotency_store={},
    )
    assert result.recovery_attempt.recovered_amount == 0.0
    assert result.recovery_attempt.execution_status == ExecutionStatus.COMPLETED.value


def test_confirmed_payment_counts_as_recovered_revenue_via_webhook(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    txn_id, reference_id, secret = _seed_razorpay_attempt(session_local, amount=5000.0)

    body = _webhook_body("payment_link.paid", reference_id, amount_paid_paise=500000)
    response = client.post(
        "/api/integrations/razorpay/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    session = session_local()
    attempt = session.query(RecoveryAttempt).filter_by(razorpay_reference_id=reference_id).one()
    assert attempt.execution_status == ExecutionStatus.SUCCESS.value
    assert attempt.recovered_amount == 5000.0
    session.close()


def test_failed_payment_does_not_count_as_recovered(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    txn_id, reference_id, secret = _seed_razorpay_attempt(session_local, amount=5000.0)

    body = _webhook_body("payment_link.expired", reference_id)
    response = client.post(
        "/api/integrations/razorpay/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"

    session = session_local()
    attempt = session.query(RecoveryAttempt).filter_by(razorpay_reference_id=reference_id).one()
    assert attempt.execution_status == ExecutionStatus.FAILED.value
    assert attempt.recovered_amount == 0.0
    session.close()


# ---------- 13: Missing credentials fails safely ----------


def test_missing_credentials_raises_configuration_error_by_default():
    with pytest.raises(RazorpayConfigurationError):
        build_razorpay_test_executor(
            key_id="", key_secret="", base_url="https://api.razorpay.com/v1",
            timeout_seconds=10.0, fallback_to_simulation=False,
        )


def test_missing_credentials_falls_back_when_explicitly_configured():
    executor = build_razorpay_test_executor(
        key_id="", key_secret="", base_url="https://api.razorpay.com/v1",
        timeout_seconds=10.0, fallback_to_simulation=True,
    )
    assert isinstance(executor, SimulationExecutor)


def test_get_executor_factory_defaults_to_simulation():
    from app.core.config import Settings

    settings = Settings(database_url="sqlite:///./x.db", recovery_executor="simulation")
    executor = get_executor(settings)
    assert isinstance(executor, SimulationExecutor)


def test_get_executor_factory_selects_razorpay_with_fallback():
    from app.core.config import Settings

    settings = Settings(
        database_url="sqlite:///./x.db",
        recovery_executor="razorpay_test",
        razorpay_key_id="",
        razorpay_key_secret="",
        razorpay_fallback_to_simulation=True,
    )
    executor = get_executor(settings)
    assert isinstance(executor, SimulationExecutor)


# ---------- 14: SimulationExecutor remains unchanged ----------


def test_simulation_executor_unchanged_default_success():
    result = SimulationExecutor().execute("RETRY", {"amount": 5000.0})
    assert result.status == ExecutionStatus.SUCCESS.value
    assert result.recovered_amount == 5000.0
    assert result.execution_mode == "SIMULATION"
    assert result.simulation_mode is True


def test_simulation_executor_is_recovery_executor_alias():
    assert SimulationExecutor is RecoveryExecutor


def test_razorpay_executor_delegates_passive_actions_to_simulation():
    fake = FakePaymentLinkClient()
    executor = RazorpayTestExecutor(fake)
    result = executor.execute("STOP", _payment())
    assert result.status == ExecutionStatus.COMPLETED.value
    assert result.execution_mode == "SIMULATION"  # delegated - not a Razorpay call
    assert len(fake.calls) == 0


def test_razorpay_executor_rejects_unsupported_action():
    fake = FakePaymentLinkClient()
    executor = RazorpayTestExecutor(fake)
    with pytest.raises(UnsupportedExecutionAction):
        executor.execute("TRANSFER_ALL_FUNDS", _payment())


# ---------- Config: RAZORPAY_MODE must be test ----------


def test_razorpay_mode_live_rejected_at_startup():
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(database_url="sqlite:///./x.db", razorpay_mode="live")


def test_razorpay_mode_test_accepted():
    from app.core.config import Settings

    settings = Settings(database_url="sqlite:///./x.db", razorpay_mode="test")
    assert settings.razorpay_mode == "test"


# ---------- Webhook: signature verification ----------


def test_verify_webhook_signature_valid():
    body = b'{"event": "payment_link.paid"}'
    secret = "whsec_test"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret) is True


def test_verify_webhook_signature_invalid():
    body = b'{"event": "payment_link.paid"}'
    assert verify_webhook_signature(body, "not-a-real-signature", "whsec_test") is False


def test_verify_webhook_signature_missing_header():
    body = b'{"event": "payment_link.paid"}'
    assert verify_webhook_signature(body, None, "whsec_test") is False


def test_verify_webhook_signature_missing_secret():
    body = b'{"event": "payment_link.paid"}'
    sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, "") is False


# ---------- 16-21: Webhook endpoint tests ----------


@pytest.fixture()
def razorpay_webhook_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    from app.core.config import get_settings

    test_settings = get_settings().model_copy(update={"razorpay_webhook_secret": "whsec_test"})
    monkeypatch.setattr("app.api.razorpay_webhook.get_settings", lambda: test_settings)

    with TestClient(app) as client:
        yield client, TestSessionLocal
    app.dependency_overrides.clear()


def _seed_razorpay_attempt(session_local, amount: float) -> tuple[str, str, str]:
    """Seeds a Payment + RecoveryAttempt as if RazorpayTestExecutor had
    already created a Payment Link for it, so the webhook has something
    to match against. Returns (transaction_id, reference_id, webhook_secret)."""
    txn_id = "TXN-WEBHOOK-1"
    reference_id = f"recoverai-{txn_id}"
    session = session_local()
    try:
        record = {
            "transaction_id": txn_id, "customer_id": "cust-wh-1", "amount": amount,
            "payment_method": "upi", "failure_reason": "network_timeout",
            "previous_transactions": 5, "previous_success_rate": 0.8,
            "subscription_status": "active", "customer_type": "returning",
            "historical_failure_count": 0, "simulation_outcome": None,
        }
        payment = repository.upsert_payment_with_customer(session, record)
        attempt = RecoveryAttempt(
            payment_id=payment.id, retry_count=0, ml_probability=0.8,
            agent_action="RETRY", agent_reason="test", agent_confidence=0.8,
            rules_decision="ALLOW", execution_status=ExecutionStatus.COMPLETED.value,
            recovered_amount=0.0, simulation_mode=False, execution_mode="RAZORPAY_TEST_MODE",
            razorpay_payment_link_id="plink_test1", razorpay_reference_id=reference_id,
        )
        session.add(attempt)
        session.commit()
    finally:
        session.close()
    return txn_id, reference_id, "whsec_test"


def _webhook_body(event: str, reference_id: str, amount_paid_paise: int | None = None) -> bytes:
    payload = {
        "event": event,
        "payload": {
            "payment_link": {
                "entity": {
                    "reference_id": reference_id,
                    **({"amount_paid": amount_paid_paise} if amount_paid_paise is not None else {}),
                }
            }
        },
    }
    return json.dumps(payload).encode()


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_valid_signature_accepted(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    _, reference_id, secret = _seed_razorpay_attempt(session_local, amount=1000.0)
    body = _webhook_body("payment_link.paid", reference_id, amount_paid_paise=100000)
    response = client.post(
        "/api/integrations/razorpay/webhook", content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_webhook_invalid_signature_rejected(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    _, reference_id, _secret = _seed_razorpay_attempt(session_local, amount=1000.0)
    body = _webhook_body("payment_link.paid", reference_id, amount_paid_paise=100000)
    response = client.post(
        "/api/integrations/razorpay/webhook", content=body,
        headers={"X-Razorpay-Signature": "totally-wrong-signature", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_webhook_duplicate_delivery_does_not_double_count(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    _, reference_id, secret = _seed_razorpay_attempt(session_local, amount=2500.0)
    body = _webhook_body("payment_link.paid", reference_id, amount_paid_paise=250000)
    headers = {"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"}

    r1 = client.post("/api/integrations/razorpay/webhook", content=body, headers=headers)
    r2 = client.post("/api/integrations/razorpay/webhook", content=body, headers=headers)

    assert r1.json()["status"] == "confirmed"
    assert r2.json()["status"] == "ignored"  # already confirmed - not double-processed

    session = session_local()
    attempt = session.query(RecoveryAttempt).filter_by(razorpay_reference_id=reference_id).one()
    assert attempt.recovered_amount == 2500.0  # not doubled to 5000
    session.close()


def test_webhook_unknown_transaction_ignored(razorpay_webhook_client):
    client, _session_local = razorpay_webhook_client
    secret = "whsec_test"
    body = _webhook_body("payment_link.paid", "recoverai-DOES-NOT-EXIST", amount_paid_paise=100000)
    response = client.post(
        "/api/integrations/razorpay/webhook", content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_success_event_sets_recovered_amount(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    _, reference_id, secret = _seed_razorpay_attempt(session_local, amount=6000.0)
    body = _webhook_body("payment_link.paid", reference_id, amount_paid_paise=600000)
    response = client.post(
        "/api/integrations/razorpay/webhook", content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )
    assert response.json()["recovered_amount"] == 6000.0


def test_webhook_failed_event_keeps_recovered_amount_zero(razorpay_webhook_client):
    client, session_local = razorpay_webhook_client
    _, reference_id, secret = _seed_razorpay_attempt(session_local, amount=6000.0)
    body = _webhook_body("payment_link.cancelled", reference_id)
    response = client.post(
        "/api/integrations/razorpay/webhook", content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )
    assert response.json()["recovered_amount"] == 0.0


# ---------- Audit event type: RAZORPAY_PAYMENT_LINK_CREATED ----------


def test_payment_link_creation_emits_distinct_audit_event_type():
    """Payment Link creation must be distinguishable in the audit trail
    from a generic passive-action COMPLETED event (Phase 5) - per Phase 7's
    audit requirements."""
    fake = FakePaymentLinkClient()
    result = recover_transaction(
        _payment(transaction_id="TXN-RZP-AUDIT"), MockProvider(), TEST_POLICY,
        executor=RazorpayTestExecutor(fake), idempotency_store={},
    )
    event_types = [e.event_type for e in result.audit_events]
    assert "RAZORPAY_PAYMENT_LINK_CREATED" in event_types
    assert "RECOVERY_COMPLETED" not in event_types


def test_simulation_completed_action_still_uses_generic_event_type():
    """Regression guard: a plain SimulationExecutor COMPLETED action
    (e.g. SEND_REMINDER) must NOT be mislabeled as a Razorpay event."""
    result = recover_transaction(
        _payment(transaction_id="TXN-SIM-AUDIT", recovery_probability=0.4), MockProvider(), TEST_POLICY,
        idempotency_store={},
    )
    event_types = [e.event_type for e in result.audit_events]
    assert "RAZORPAY_PAYMENT_LINK_CREATED" not in event_types


# ---------- 15: existing 134 tests continue passing - verified by running full suite separately ----------
