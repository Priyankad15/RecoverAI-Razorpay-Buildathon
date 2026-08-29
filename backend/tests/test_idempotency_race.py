"""
Focused regression tests for the idempotency race-condition fix
identified in code review: two requests that both pass the
application-level `get_latest_attempt() is None` check before either has
inserted could previously create two RecoveryAttempt rows for the same
payment (and, under RECOVERY_EXECUTOR=razorpay_test, potentially two
Razorpay Payment Links).

The fix adds a database-level unique constraint on
RecoveryAttempt.payment_id (see app.db.models) plus graceful handling of
the resulting IntegrityError (see app.db.repository.persist_recovery_result
and app.api.recovery.trigger_recovery).

What these tests actually prove, precisely:
- test_persist_recovery_result_rejects_second_attempt_for_same_payment:
  the DB constraint itself fires, deterministically, no threading involved.
- test_post_recovery_gracefully_returns_winning_result_after_lost_race:
  the API route's exception-handling branch, deterministically forced
  (not timing-dependent), returns the winning result instead of a raw
  error.
- test_concurrent_post_requests_never_create_duplicate_attempts:
  a real two-thread race against a shared in-memory SQLite database,
  synchronized with a Barrier to maximize (not guarantee) actual
  interleaving. This is strong evidence under SQLite's specific locking
  behavior in this test environment - it is not a formal proof that no
  database backend could ever interleave differently. The claim this
  test supports is narrow and stated in its own docstring.

None of these tests touch the AI agent, rules engine, execution
architecture, Razorpay safety boundaries, or revenue accounting - they
exercise only the persistence-layer idempotency guarantee.
"""

from __future__ import annotations

import os
import tempfile
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.providers import MockProvider
from app.db import repository
from app.db.models import Base, Payment, RecoveryAttempt
from app.db.repository import DuplicateRecoveryAttemptError
from app.db.session import get_db
from app.execution.service import recover_transaction
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client, TestSessionLocal
    app.dependency_overrides.clear()


def _seed_payment(session_local, **overrides) -> dict:
    record = {
        "transaction_id": "TXN-RACE-1",
        "customer_id": "cust-race-1",
        "amount": 4999.0,
        "payment_method": "upi",
        "failure_reason": "network_timeout",
        "previous_transactions": 15,
        "previous_success_rate": 0.9,
        "subscription_status": "active",
        "customer_type": "returning",
        "historical_failure_count": 0,
        "simulation_outcome": None,
    }
    record.update(overrides)
    session = session_local()
    try:
        repository.upsert_payment_with_customer(session, record)
        session.commit()
    finally:
        session.close()
    return record


@pytest.fixture()
def threaded_client():
    """
    A separate fixture from `client` above, deliberately NOT using
    StaticPool over an in-memory database. StaticPool hands out the same
    single underlying connection to every Session, which - when two real
    threads then use it concurrently - tests the connection object's
    thread-safety rather than the database's actual cross-connection
    transaction isolation. A real concurrency test needs each thread to
    get its own connection, the way separate concurrent requests would
    in production; a temp-file-backed SQLite database with the default
    connection pool provides that.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client, TestSessionLocal
    app.dependency_overrides.clear()
    engine.dispose()
    os.unlink(path)


def _run_recovery(payment_dict: dict):
    """Produces a real RecoveryTransactionResult via the actual Phase 5
    pipeline (MockProvider, default policy) - not a hand-built fake -
    so the persistence test below exercises the real object shape."""
    return recover_transaction(
        {
            **payment_dict,
            "retry_count": 0,
            "days_since_failure": 0,
            "time_since_last_success": 24.0,
            "device_risk_score": 0.1,
            "recovery_probability": 0.85,
        },
        provider=MockProvider(),
        idempotency_store={},
    )


# ---------- 1: the DB constraint itself fires (deterministic, no threading) ----------


def test_persist_recovery_result_rejects_second_attempt_for_same_payment(client):
    test_client, session_local = client
    record = _seed_payment(session_local, transaction_id="TXN-RACE-DIRECT")

    session = session_local()
    try:
        payment = repository.get_payment_by_transaction_id(session, "TXN-RACE-DIRECT")

        first_result = _run_recovery(record)
        repository.persist_recovery_result(session, payment, first_result, retry_count=0, ml_probability=0.85)
        session.commit()

        second_result = _run_recovery(record)
        with pytest.raises(DuplicateRecoveryAttemptError):
            repository.persist_recovery_result(
                session, payment, second_result, retry_count=0, ml_probability=0.85
            )

        # The session must still be usable after the rollback inside
        # persist_recovery_result - prove it by successfully querying.
        count = session.execute(
            select(func.count()).select_from(RecoveryAttempt).where(RecoveryAttempt.payment_id == payment.id)
        ).scalar_one()
        assert count == 1, "exactly one attempt must survive - the rejected second insert must not persist"
    finally:
        session.close()


def test_rejected_duplicate_leaves_no_orphaned_audit_rows(client):
    """The failed second insert's AuditLog rows (queued in the same
    flush) must also be rolled back - not left as orphans referencing an
    attempt that was never actually recorded."""
    test_client, session_local = client
    record = _seed_payment(session_local, transaction_id="TXN-RACE-AUDIT")

    session = session_local()
    try:
        payment = repository.get_payment_by_transaction_id(session, "TXN-RACE-AUDIT")

        first_result = _run_recovery(record)
        repository.persist_recovery_result(session, payment, first_result, retry_count=0, ml_probability=0.85)
        session.commit()
        audit_count_after_first = len(repository.list_audit_events(session, transaction_id="TXN-RACE-AUDIT"))

        second_result = _run_recovery(record)
        with pytest.raises(DuplicateRecoveryAttemptError):
            repository.persist_recovery_result(
                session, payment, second_result, retry_count=0, ml_probability=0.85
            )

        audit_count_after_rejected_second = len(
            repository.list_audit_events(session, transaction_id="TXN-RACE-AUDIT")
        )
        assert audit_count_after_rejected_second == audit_count_after_first
    finally:
        session.close()


# ---------- 2: API route's graceful-handling branch (deterministically forced) ----------


def test_post_recovery_gracefully_returns_winning_result_after_lost_race(client, monkeypatch):
    """Forces the exact race outcome deterministically (no thread timing
    involved): a 'winning' attempt is already persisted by the time this
    request's own persist call runs, and persist_recovery_result is
    monkeypatched to raise DuplicateRecoveryAttemptError - exactly what
    the real DB constraint raises when a genuine race is lost. Proves
    the route returns the winning result gracefully (200, correct data)
    instead of a raw 500."""
    test_client, session_local = client
    record = _seed_payment(session_local, transaction_id="TXN-RACE-API")

    # Simulate a concurrent request that already won: persist a real
    # result directly, bypassing the route.
    session = session_local()
    payment = repository.get_payment_by_transaction_id(session, "TXN-RACE-API")
    winning_result = _run_recovery(record)
    repository.persist_recovery_result(session, payment, winning_result, retry_count=0, ml_probability=0.85)
    session.commit()
    session.close()

    def _raise_duplicate(*args, **kwargs):
        raise DuplicateRecoveryAttemptError("simulated lost race")

    monkeypatch.setattr(repository, "persist_recovery_result", _raise_duplicate)

    response = test_client.post("/api/recovery/TXN-RACE-API")

    assert response.status_code == 200, f"must not surface a raw error: {response.text}"
    data = response.json()
    assert data["idempotent_replay"] is True
    assert data["execution_status"] == winning_result.recovery_attempt.execution_status
    assert data["recovered_amount"] == winning_result.recovery_attempt.recovered_amount
    assert data["rules_decision"] == winning_result.recovery_attempt.rules_decision


# ---------- 3: real two-thread race against a shared DB ----------


def test_concurrent_post_requests_never_create_duplicate_attempts(threaded_client):
    """
    Two real threads, synchronized with a Barrier to start their
    requests as close together as possible, both POST to the same
    transaction concurrently, against a temp-file-backed SQLite database
    where each thread's session gets its own real connection (see the
    `threaded_client` fixture docstring for why this matters).

    What this test proves: after both requests complete, at most one
    RecoveryAttempt row exists for the payment, both HTTP responses
    succeeded (no unhandled exception surfaced as a 500), and both
    responses report identical execution_status/recovered_amount/
    rules_decision - i.e. neither caller ever saw corrupted, conflicting,
    or partially-written data, regardless of which one's request
    happened to "win" the underlying database write.

    What this test does NOT prove: that this exact interleaving is
    reproduced identically on every database backend or under every
    possible thread-scheduling order. SQLite's own file-level locking
    may serialize the two write attempts differently than Postgres would
    under real contention. This is strong evidence for this codebase's
    behavior under an actual race, not a formal cross-database guarantee.
    """
    test_client, session_local = threaded_client
    _seed_payment(session_local, transaction_id="TXN-RACE-THREADED")

    barrier = threading.Barrier(2)
    responses: list = [None, None]
    errors: list = [None, None]

    def _post(index: int):
        try:
            barrier.wait(timeout=5)
            responses[index] = test_client.post("/api/recovery/TXN-RACE-THREADED")
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below, not swallowed
            errors[index] = exc

    threads = [threading.Thread(target=_post, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [None, None], f"neither request should raise an unhandled exception: {errors}"
    assert responses[0] is not None and responses[1] is not None, "both requests must complete"
    assert responses[0].status_code == 200
    assert responses[1].status_code == 200

    data0, data1 = responses[0].json(), responses[1].json()
    assert data0["execution_status"] == data1["execution_status"]
    assert data0["recovered_amount"] == data1["recovered_amount"]
    assert data0["rules_decision"] == data1["rules_decision"]
    # Exactly one of the two should be the "fresh" result and the other
    # the idempotent replay - never both fresh (that would mean two
    # independent executions/Razorpay calls happened).
    assert sorted([data0["idempotent_replay"], data1["idempotent_replay"]]) == [False, True]

    session = session_local()
    try:
        payment = session.execute(
            select(Payment).where(Payment.transaction_id == "TXN-RACE-THREADED")
        ).scalar_one()
        count = session.execute(
            select(func.count()).select_from(RecoveryAttempt).where(RecoveryAttempt.payment_id == payment.id)
        ).scalar_one()
        assert count == 1, "concurrent requests must never persist more than one attempt for the same payment"
    finally:
        session.close()
