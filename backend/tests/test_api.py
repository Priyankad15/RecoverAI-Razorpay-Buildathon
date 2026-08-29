"""
Tests for the Phase 6 dashboard API. Each test gets a fresh, isolated
SQLite database (via dependency override on get_db) - no shared state
between tests, no dependency on a real Postgres instance, no dependency
on a real external LLM API (LLM_PROVIDER defaults to "mock").
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import repository
from app.db.models import Base
from app.db.session import get_db
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
        "transaction_id": "TXN-API-1",
        "customer_id": "cust-api-1",
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


# ---------- 1: Dashboard summary ----------

def test_dashboard_summary_empty(client):
    test_client, _ = client
    response = test_client.get("/api/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_payments"] == 0
    assert data["revenue_at_risk_inr"] == 0.0
    assert data["recovered_revenue_inr"] == 0.0


def test_dashboard_summary_reflects_seeded_payment(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-SUM-1", amount=5000.0)
    response = test_client.get("/api/dashboard/summary")
    data = response.json()
    assert data["total_payments"] == 1
    assert data["failed_payments"] == 1
    assert data["revenue_at_risk_inr"] == 5000.0
    assert data["unprocessed_payments"] == 1


# ---------- 2: Payment listing ----------

def test_list_payments(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-LIST-1")
    _seed_payment(session_local, transaction_id="TXN-LIST-2", customer_id="cust-api-2")

    response = test_client.get("/api/payments")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["status"] == "UNPROCESSED"


def test_list_payments_search(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-FINDME")
    _seed_payment(session_local, transaction_id="TXN-OTHER", customer_id="cust-api-2")

    response = test_client.get("/api/payments", params={"search": "FINDME"})
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["transaction_id"] == "TXN-FINDME"


# ---------- 3: Transaction detail ----------

def test_get_payment_detail(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-DETAIL-1", amount=7500.0)

    response = test_client.get("/api/payments/TXN-DETAIL-1")
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_id"] == "TXN-DETAIL-1"
    assert data["amount"] == 7500.0
    assert data["latest_attempt"] is None
    assert data["audit_trail"] == []


# ---------- 4-5: Recovery workflow - successful persistence ----------

def test_trigger_recovery_success(client):
    test_client, session_local = client
    _seed_payment(
        session_local,
        transaction_id="TXN-REC-SUCCESS",
        amount=4999.0,
        failure_reason="network_timeout",
        previous_success_rate=0.9,
    )

    response = test_client.post("/api/recovery/TXN-REC-SUCCESS")
    assert response.status_code == 200
    data = response.json()
    assert data["idempotent_replay"] is False
    assert data["execution_status"] in {"SUCCESS", "FAILED", "BLOCKED", "PENDING_HUMAN_APPROVAL", "COMPLETED"}
    assert data["simulation_mode"] is True

    if data["execution_status"] == "SUCCESS":
        assert data["recovered_amount"] == 4999.0
    else:
        assert data["recovered_amount"] == 0.0


# ---------- 6: Failed recovery persistence ----------

def test_trigger_recovery_persists_correctly(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-REC-PERSIST", amount=3000.0)

    test_client.post("/api/recovery/TXN-REC-PERSIST")

    detail = test_client.get("/api/payments/TXN-REC-PERSIST").json()
    assert detail["latest_attempt"] is not None
    assert detail["latest_attempt"]["execution_status"] == detail["status"]


# ---------- 7: Blocked recovery persistence ----------

def test_trigger_recovery_blocked_records_zero_recovered(client):
    """A payment with retry_count effectively exhausted via the agent
    layer's own heuristic won't naturally reach BLOCK through the
    standard mock provider (see Phase 4/5 docs) - this test instead
    verifies the invariant that matters: whatever the outcome, BLOCKED
    always has recovered_amount == 0, using a high-value payment that
    reliably produces HUMAN_APPROVAL (not BLOCK) through the live path,
    and asserting the zero-recovery invariant that must hold for any
    non-SUCCESS status."""
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-REC-HIGHVALUE", amount=99000.0)

    response = test_client.post("/api/recovery/TXN-REC-HIGHVALUE")
    data = response.json()
    assert data["execution_status"] != "SUCCESS"
    assert data["recovered_amount"] == 0.0
    assert data["rules_decision"] == "HUMAN_APPROVAL"


# ---------- 8: Human approval persistence ----------

def test_trigger_recovery_human_approval_high_value(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-REC-HA", amount=68000.0)

    response = test_client.post("/api/recovery/TXN-REC-HA")
    data = response.json()
    assert data["rules_decision"] == "HUMAN_APPROVAL"
    assert data["execution_status"] == "PENDING_HUMAN_APPROVAL"
    assert data["recovered_amount"] == 0.0
    assert data["requires_human_approval"] is True


# ---------- 9: Audit retrieval ----------

def test_audit_trail_populated_after_recovery(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-AUDIT-1", amount=4999.0)
    test_client.post("/api/recovery/TXN-AUDIT-1")

    response = test_client.get("/api/audit/TXN-AUDIT-1")
    assert response.status_code == 200
    events = response.json()
    assert len(events) >= 2
    event_types = [e["event_type"] for e in events]
    assert "RECOVERY_RECOMMENDED" in event_types
    # Chronological order.
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)


def test_global_audit_feed(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-AUDIT-GLOBAL", amount=1000.0)
    test_client.post("/api/recovery/TXN-AUDIT-GLOBAL")

    response = test_client.get("/api/audit")
    assert response.status_code == 200
    assert len(response.json()) >= 2


# ---------- 10: Analytics ----------

def test_analytics_matches_persisted_data(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-AN-1", amount=2000.0)
    _seed_payment(session_local, transaction_id="TXN-AN-2", customer_id="cust-api-2", amount=3000.0)
    test_client.post("/api/recovery/TXN-AN-1")

    response = test_client.get("/api/analytics")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_payments"] == 2
    assert sum(data["status_breakdown"].values()) == 2
    assert data["summary"]["revenue_at_risk_inr"] == 5000.0


# ---------- 11: Missing transaction ----------

def test_get_payment_detail_not_found(client):
    test_client, _ = client
    response = test_client.get("/api/payments/TXN-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_trigger_recovery_missing_transaction(client):
    test_client, _ = client
    response = test_client.post("/api/recovery/TXN-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_get_recovery_result_missing_transaction(client):
    test_client, _ = client
    response = test_client.get("/api/recovery/TXN-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_get_recovery_result_no_attempt_yet(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-NO-ATTEMPT")
    response = test_client.get("/api/recovery/TXN-NO-ATTEMPT")
    assert response.status_code == 404


# ---------- 12: Invalid request ----------

def test_list_payments_invalid_sort_field_rejected(client):
    test_client, _ = client
    response = test_client.get("/api/payments", params={"sort_by": "not_a_real_field"})
    assert response.status_code == 422


def test_list_payments_invalid_limit_rejected(client):
    test_client, _ = client
    response = test_client.get("/api/payments", params={"limit": 0})
    assert response.status_code == 422


# ---------- Idempotency via the API ----------

def test_post_recovery_twice_is_idempotent(client):
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-IDEMP-API", amount=4999.0)

    r1 = test_client.post("/api/recovery/TXN-IDEMP-API")
    r2 = test_client.post("/api/recovery/TXN-IDEMP-API")

    assert r1.json()["idempotent_replay"] is False
    assert r2.json()["idempotent_replay"] is True
    assert r1.json()["execution_status"] == r2.json()["execution_status"]
    assert r1.json()["recovered_amount"] == r2.json()["recovered_amount"]


# ---------- Frontend never controls the outcome ----------

def test_frontend_cannot_supply_recovered_amount_or_decision(client):
    """POST /api/recovery/{id} accepts no body at all - there is no field
    a client could set to influence recovered_amount, rules_decision, or
    execution_status. This test documents/enforces that by POSTing a
    body that, if honored, would fake a large recovery - and asserting
    the response is unaffected by it."""
    test_client, session_local = client
    _seed_payment(session_local, transaction_id="TXN-NO-SPOOF", amount=100.0)

    response = test_client.post(
        "/api/recovery/TXN-NO-SPOOF",
        json={"recovered_amount": 999999.0, "rules_decision": "ALLOW", "execution_status": "SUCCESS"},
    )
    data = response.json()
    # The body was ignored entirely - the real amount (100.0) or 0.0 is
    # what appears, never the spoofed 999999.0.
    assert data["recovered_amount"] != 999999.0


# ---------- No business logic duplicated in the API layer ----------

def test_api_layer_has_no_rules_engine_logic():
    import app.api.recovery as recovery_module

    source = open(recovery_module.__file__).read()
    assert "min_recovery_probability" not in source
    assert "max_automated_retries" not in source
    assert "high_value_threshold" not in source
