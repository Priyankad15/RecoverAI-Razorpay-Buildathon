"""
Seeds the database with demo data for the dashboard.

Three kinds of rows are created:

1. Four canonical demo transactions (TXN-DEMO-A..D), pre-executed using
   the exact same Phase 5 demo fixtures already established
   (scripts/demo_fixtures.py - reused, not duplicated) so the dashboard
   reliably shows one of each outcome: SUCCESS, FAILED, BLOCKED,
   PENDING_HUMAN_APPROVAL. These are persisted immediately.

2. Two curated "hero" probability transactions (pay_demo_low_probability,
   pay_demo_high_probability) with feature profiles empirically verified
   against the real trained Phase 2 model by actually calling
   predict_recovery() (see docs/DEMO_SCENARIOS.md for the exact observed
   recovery_probability of each - re-verify after any model retrain,
   since these numbers are read off a specific trained artifact, not
   derived analytically). Left UNPROCESSED so a merchant can trigger
   recovery live and see the real model's output.

3. A realistic batch of ~20 additional failed-payment transactions
   (pay_demo_XXX / cust_demo_XXX) spanning varied INR amounts, payment
   methods, failure reasons, and customer histories (new, returning,
   loyal, repeated-failure). Left UNPROCESSED for live interactive
   triggering through the dashboard.

Idempotent: every payment is upserted by transaction_id
(repository.upsert_payment_with_customer selects-or-creates), and every
recovery attempt is only executed if one doesn't already exist for that
payment - safe to run this script multiple times without creating
duplicate transactions or duplicate recovery attempts.

Usage (from the backend/ directory):
    python -m scripts.seed_demo_data [--n-sample 30]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app.db import repository
from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.execution.enums import ForcedOutcome
from scripts.demo_fixtures import run_demo_a, run_demo_b, run_demo_c, run_demo_d

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
RAW_DATA_PATH = REPO_ROOT / "data" / "raw" / "synthetic_payments.csv"


def _seed_canonical_demos(session) -> None:
    print("Seeding canonical demo transactions (DEMO-A..D)...")

    demo_payments = {
        "TXN-DEMO-A": {
            "transaction_id": "TXN-DEMO-A",
            "customer_id": "cust_demo_a",
            "amount": 4999.0,
            "payment_method": "upi",
            "failure_reason": "network_timeout",
            "previous_transactions": 20,
            "previous_success_rate": 0.91,
            "subscription_status": "active",
            "customer_type": "returning",
            "historical_failure_count": 0,
            "simulation_outcome": ForcedOutcome.SUCCESS.value,
        },
        "TXN-DEMO-B": {
            "transaction_id": "TXN-DEMO-B",
            "customer_id": "cust_demo_b",
            "amount": 4999.0,
            "payment_method": "upi",
            "failure_reason": "network_timeout",
            "previous_transactions": 20,
            "previous_success_rate": 0.91,
            "subscription_status": "active",
            "customer_type": "returning",
            "historical_failure_count": 0,
            "simulation_outcome": ForcedOutcome.FAILURE.value,
        },
        "TXN-DEMO-C": {
            "transaction_id": "TXN-DEMO-C",
            "customer_id": "cust_demo_c",
            "amount": 4999.0,
            "payment_method": "upi",
            "failure_reason": "network_timeout",
            "previous_transactions": 20,
            "previous_success_rate": 0.91,
            "subscription_status": "active",
            "customer_type": "returning",
            "historical_failure_count": 0,
            "simulation_outcome": None,
        },
        "TXN-DEMO-D": {
            "transaction_id": "TXN-DEMO-D",
            "customer_id": "cust_demo_d",
            "amount": 68000.0,
            "payment_method": "upi",
            "failure_reason": "network_timeout",
            "previous_transactions": 20,
            "previous_success_rate": 0.91,
            "subscription_status": "active",
            "customer_type": "returning",
            "historical_failure_count": 0,
            "simulation_outcome": None,
        },
    }

    payment_rows = {}
    for txn_id, record in demo_payments.items():
        payment_rows[txn_id] = repository.upsert_payment_with_customer(session, record)
    session.commit()

    demo_runs = [
        ("TXN-DEMO-A", run_demo_a, 0, 0.84),
        ("TXN-DEMO-B", run_demo_b, 0, 0.84),
        ("TXN-DEMO-C", run_demo_c, 2, 0.84),
        ("TXN-DEMO-D", run_demo_d, 0, 0.84),
    ]

    for txn_id, run_fn, retry_count, probability in demo_runs:
        payment = payment_rows[txn_id]
        if repository.get_latest_attempt(session, payment) is not None:
            print(f"  {txn_id} already has a recovery attempt - skipping re-execution.")
            continue
        result = run_fn()
        repository.persist_recovery_result(
            session, payment, result, retry_count=retry_count, ml_probability=probability
        )
        print(f"  {txn_id}: {result.safety.decision} / {result.recovery_attempt.execution_status}")

    session.commit()


def _seed_hero_probability_scenarios(session) -> None:
    """pay_demo_low_probability and pay_demo_high_probability - feature
    profiles verified empirically against the real trained model (see
    docs/DEMO_SCENARIOS.md for the observed recovery_probability of each).
    Left unprocessed so a merchant triggers them live."""
    print("Seeding hero probability scenarios...")

    records = {
        "pay_demo_low_probability": {
            "transaction_id": "pay_demo_low_probability",
            "customer_id": "cust_demo_low_prob",
            "amount": 1299.0,
            "payment_method": "wallet",
            "failure_reason": "insufficient_funds",
            "previous_transactions": 0,
            "previous_success_rate": 0.5,
            "subscription_status": "none",
            "customer_type": "new",
            "historical_failure_count": 4,
            "days_since_failure": 12,
            "time_since_last_success": 720.0,
            "device_risk_score": 0.85,
            "simulation_outcome": None,
        },
        "pay_demo_high_probability": {
            "transaction_id": "pay_demo_high_probability",
            "customer_id": "cust_demo_high_prob",
            "amount": 999.0,
            "payment_method": "upi",
            "failure_reason": "network_timeout",
            "previous_transactions": 50,
            "previous_success_rate": 0.98,
            "subscription_status": "active",
            "customer_type": "loyal",
            "historical_failure_count": 0,
            "days_since_failure": 0,
            "time_since_last_success": 2.0,
            "device_risk_score": 0.02,
            "simulation_outcome": None,
        },
    }

    for txn_id, record in records.items():
        repository.upsert_payment_with_customer(session, record)
    session.commit()
    print(f"  {len(records)} hero probability scenarios seeded (unprocessed).")


def _seed_hard_stop_blocked_scenario(session) -> None:
    """pay_demo_hard_stop_fraud - a genuine HARD_STOP_FAILURE_REASON block,
    distinct from TXN-DEMO-C (which blocks via MAX_RETRIES_REACHED).
    failure_reason is "risk_flagged" - the actual configured default in
    HARD_STOP_FAILURE_REASONS (app.core.config) - so this transaction is
    blocked for the real configured reason, not a stand-in label. Uses
    the same AlwaysRetryProvider test stub already established by
    scripts/demo_fixtures.py:run_demo_c (reused, not duplicated) to force
    a genuine RETRY request despite the hard-stop, proving the rules
    engine - not the agent - is what actually blocks it."""
    print("Seeding hard-stop (fraud) blocked scenario...")

    from tests.test_agent import _AlwaysRetryProvider

    from app.execution.service import recover_transaction

    record = {
        "transaction_id": "pay_demo_hard_stop_fraud",
        "customer_id": "cust_demo_hard_stop",
        "amount": 9999.0,
        "payment_method": "card",
        "failure_reason": "risk_flagged",
        "previous_transactions": 3,
        "previous_success_rate": 0.6,
        "subscription_status": "none",
        "customer_type": "returning",
        "historical_failure_count": 1,
        "days_since_failure": 0,
        "time_since_last_success": 200.0,
        "device_risk_score": 0.9,
        "simulation_outcome": None,
    }
    payment = repository.upsert_payment_with_customer(session, record)
    session.commit()

    if repository.get_latest_attempt(session, payment) is not None:
        print("  pay_demo_hard_stop_fraud already has a recovery attempt - skipping re-execution.")
        return

    payload = {**record, "retry_count": 0, "recovery_probability": 0.7}
    result = recover_transaction(payload, provider=_AlwaysRetryProvider(), idempotency_store={})
    repository.persist_recovery_result(session, payment, result, retry_count=0, ml_probability=0.7)
    session.commit()
    print(f"  pay_demo_hard_stop_fraud: {result.safety.decision} / {result.recovery_attempt.execution_status}")


def _seed_realistic_batch(session) -> None:
    """~20 additional realistic failed-payment transactions spanning
    varied amounts, payment methods, failure reasons, and customer
    histories - for a compelling, populated Payments/Analytics view.
    Left unprocessed for live interactive triggering."""
    print("Seeding realistic demo batch (pay_demo_XXX, unprocessed)...")

    amounts = [299.0, 499.0, 799.0, 1299.0, 2499.0, 4999.0, 9999.0, 25000.0, 50000.0, 75000.0, 120000.0]
    methods = ["card", "upi", "netbanking", "wallet"]
    failure_reasons = [
        "insufficient_funds", "network_error", "bank_declined", "timeout",
        "authentication_failed", "card_expired", "rate_limit", "suspected_fraud",
        "duplicate_payment", "invalid_request",
    ]
    customer_profiles = [
        # (customer_type, previous_transactions, previous_success_rate, historical_failure_count)
        ("new", 0, 0.5, 0),
        ("returning", 8, 0.75, 1),
        ("returning", 12, 0.88, 0),
        ("loyal", 40, 0.96, 0),
        ("returning", 6, 0.6, 3),  # repeated failures
    ]

    records = []
    for i in range(20):
        amount = amounts[i % len(amounts)]
        method = methods[i % len(methods)]
        failure_reason = failure_reasons[i % len(failure_reasons)]
        customer_type, prev_txns, success_rate, hist_failures = customer_profiles[i % len(customer_profiles)]
        records.append(
            {
                "transaction_id": f"pay_demo_{i + 1:03d}",
                "customer_id": f"cust_demo_{(i % len(customer_profiles)) + 1:03d}",
                "amount": amount,
                "payment_method": method,
                "failure_reason": failure_reason,
                "previous_transactions": prev_txns,
                "previous_success_rate": success_rate,
                "subscription_status": "active" if customer_type != "new" else "none",
                "customer_type": customer_type,
                "historical_failure_count": hist_failures,
                "simulation_outcome": ForcedOutcome.SUCCESS.value if i % 3 != 0 else ForcedOutcome.FAILURE.value,
            }
        )

    for record in records:
        repository.upsert_payment_with_customer(session, record)
    session.commit()
    print(f"  {len(records)} realistic demo payments seeded (unprocessed).")


def _seed_sample_payments(session, n_sample: int) -> None:
    """Additional generic sample payments from Phase 2's synthetic
    dataset, on top of the curated batch above - purely for extra
    volume if desired."""
    if not RAW_DATA_PATH.exists():
        print(f"Skipping sample payments - {RAW_DATA_PATH} not found (run Phase 2's generate_dataset first).")
        return

    print(f"Seeding {n_sample} sample payments from the synthetic dataset (unprocessed, interactive)...")
    df = pd.read_csv(RAW_DATA_PATH).head(n_sample)

    for _, row in df.iterrows():
        record = {
            "transaction_id": row["transaction_id"],
            "customer_id": row["customer_id"],
            "amount": float(row["amount"]),
            "payment_method": row["payment_method"],
            "failure_reason": row["failure_reason"],
            "previous_transactions": int(row["previous_transactions"]),
            "previous_success_rate": float(row["previous_success_rate"]),
            "subscription_status": row["subscription_status"],
            "customer_type": row["customer_type"],
            "historical_failure_count": int(row["historical_failure_count"]),
            "simulation_outcome": (
                ForcedOutcome.SUCCESS.value if int(row["recovered"]) == 1 else ForcedOutcome.FAILURE.value
            ),
        }
        repository.upsert_payment_with_customer(session, record)

    session.commit()
    print(f"  {len(df)} sample payments seeded (left unprocessed - trigger via POST /api/recovery/{{id}}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed RecoverAI demo data")
    parser.add_argument("--n-sample", type=int, default=0, help="Number of additional generic sample payments to seed")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        _seed_canonical_demos(session)
        _seed_hero_probability_scenarios(session)
        _seed_hard_stop_blocked_scenario(session)
        _seed_realistic_batch(session)
        _seed_sample_payments(session, args.n_sample)
    finally:
        session.close()

    print("\nDemo data seeding complete.")


if __name__ == "__main__":
    main()
