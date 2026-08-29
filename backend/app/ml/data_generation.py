"""
Synthetic failed-payment dataset generation for RecoverAI.

Design principle: the `recovered` target is NOT derived from a trivial
threshold on a visible "recovery score" column (that would be leakage).
Instead, a hidden logit is built from a weighted combination of features
plus Gaussian noise, converted to a probability via a sigmoid, and the
final label is drawn from a Bernoulli distribution with that probability.
The model that trains on this data later has to *learn* the relationship
from noisy realizations, the same way it would from real payment data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RANDOM_SEED = 42

PAYMENT_METHODS = ["card", "upi", "netbanking", "wallet", "emi"]
PAYMENT_METHOD_WEIGHTS = [0.40, 0.35, 0.12, 0.09, 0.04]
# Effect on recovery logit - UPI/card retries tend to succeed more easily
# than netbanking/EMI failures in practice.
PAYMENT_METHOD_EFFECT = {"upi": 0.25, "card": 0.15, "wallet": 0.05, "netbanking": -0.10, "emi": -0.20}

FAILURE_REASONS = [
    "network_timeout",
    "insufficient_funds",
    "bank_server_error",
    "otp_failed",
    "card_declined_bank",
    "risk_flagged",
    "invalid_card",
]
FAILURE_REASON_WEIGHTS = [0.22, 0.20, 0.15, 0.14, 0.13, 0.09, 0.07]
# Temporary/technical failures recover well; hard declines and invalid
# cards essentially never recover on retry.
FAILURE_REASON_EFFECT = {
    "network_timeout": 0.9,
    "bank_server_error": 0.7,
    "otp_failed": 0.5,
    "insufficient_funds": -0.1,
    "risk_flagged": -0.6,
    "card_declined_bank": -0.9,
    "invalid_card": -1.6,
}

CUSTOMER_TYPES = ["new", "returning", "loyal"]
CUSTOMER_TYPE_WEIGHTS = [0.35, 0.45, 0.20]
CUSTOMER_TYPE_EFFECT = {"new": -0.35, "returning": 0.10, "loyal": 0.45}

SUBSCRIPTION_STATUSES = ["active", "none", "paused", "cancelled"]
SUBSCRIPTION_STATUS_WEIGHTS = [0.30, 0.45, 0.15, 0.10]
SUBSCRIPTION_STATUS_EFFECT = {"active": 0.30, "paused": -0.05, "none": 0.0, "cancelled": -0.35}

REQUIRED_COLUMNS = [
    "transaction_id",
    "customer_id",
    "amount",
    "payment_method",
    "failure_reason",
    "retry_count",
    "previous_transactions",
    "previous_success_rate",
    "subscription_status",
    "customer_type",
    "days_since_failure",
    "time_since_last_success",
    "device_risk_score",
    "historical_failure_count",
    "recovered",
    "recovery_outcome",
]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def generate_synthetic_dataset(n_records: int = 3000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Generate a synthetic failed-payment dataset with a hidden, noisy,
    probabilistic recovery mechanism (not a deterministic rule)."""

    rng = np.random.default_rng(seed)

    customer_type = rng.choice(CUSTOMER_TYPES, size=n_records, p=CUSTOMER_TYPE_WEIGHTS)
    payment_method = rng.choice(PAYMENT_METHODS, size=n_records, p=PAYMENT_METHOD_WEIGHTS)
    failure_reason = rng.choice(FAILURE_REASONS, size=n_records, p=FAILURE_REASON_WEIGHTS)
    subscription_status = rng.choice(
        SUBSCRIPTION_STATUSES, size=n_records, p=SUBSCRIPTION_STATUS_WEIGHTS
    )

    # Amount: log-normal, clipped to a plausible INR transaction range.
    amount = np.clip(rng.lognormal(mean=7.6, sigma=0.9, size=n_records), 49, 150000).round(2)

    # Retry count so far: mostly 0, some 1, few 2 (matches the "max 2
    # automated retries" policy that later phases enforce).
    retry_count = rng.choice([0, 1, 2], size=n_records, p=[0.62, 0.28, 0.10])

    # New customers have zero prior transactions by definition; returning
    # and loyal customers have a history.
    previous_transactions = np.where(
        customer_type == "new",
        0,
        rng.poisson(lam=np.where(customer_type == "loyal", 18, 6), size=n_records),
    )

    # Previous success rate is only meaningful when there is history.
    # New customers get a neutral prior (0.5) rather than a fabricated rate.
    base_success_rate = np.clip(rng.beta(a=5, b=2, size=n_records), 0.0, 1.0)
    previous_success_rate = np.where(customer_type == "new", 0.5, base_success_rate).round(3)

    days_since_failure = rng.integers(0, 31, size=n_records)

    # Time since last successful payment (hours). New customers have no
    # prior success, so this is set to a large sentinel value rather than
    # a fabricated recency.
    time_since_last_success = np.where(
        customer_type == "new",
        720.0,
        np.clip(rng.exponential(scale=96, size=n_records), 1, 2000),
    ).round(1)

    device_risk_score = np.clip(rng.beta(a=2, b=6, size=n_records), 0.0, 1.0).round(3)

    historical_failure_count = np.where(
        customer_type == "new",
        rng.poisson(lam=0.3, size=n_records),
        rng.poisson(lam=1.8, size=n_records),
    )

    # ---- Hidden probabilistic recovery mechanism (not visible as a column) ----
    logit = (
        -0.35  # intercept: recovery is not the default outcome
        + 1.6 * (previous_success_rate - 0.5)
        - 0.55 * retry_count
        + np.vectorize(FAILURE_REASON_EFFECT.get)(failure_reason)
        + np.vectorize(CUSTOMER_TYPE_EFFECT.get)(customer_type)
        + np.vectorize(SUBSCRIPTION_STATUS_EFFECT.get)(subscription_status)
        + np.vectorize(PAYMENT_METHOD_EFFECT.get)(payment_method)
        - 0.55 * (days_since_failure / 30.0)
        - 0.30 * np.minimum(historical_failure_count, 10) / 10.0
        - 0.9 * device_risk_score
        - 0.15 * (np.log1p(amount) - 7.6) / 2.0
    )

    # Realistic noise so the relationship is learnable but not perfect.
    noise = rng.normal(loc=0.0, scale=0.85, size=n_records)
    hidden_probability = _sigmoid(logit + noise)

    recovered = (rng.random(n_records) < hidden_probability).astype(int)
    recovery_outcome = np.where(recovered == 1, "recovered", "not_recovered")

    # Transaction IDs are derived from the seeded RNG (not uuid4) so the
    # entire dataset is exactly reproducible for a given seed.
    txn_suffixes = rng.integers(0, 16**12, size=n_records)
    transaction_id = [f"txn_{suffix:012x}" for suffix in txn_suffixes]
    customer_id = [f"cust_{i:06d}" for i in rng.integers(0, n_records // 2 + 50, size=n_records)]

    df = pd.DataFrame(
        {
            "transaction_id": transaction_id,
            "customer_id": customer_id,
            "amount": amount,
            "payment_method": payment_method,
            "failure_reason": failure_reason,
            "retry_count": retry_count,
            "previous_transactions": previous_transactions,
            "previous_success_rate": previous_success_rate,
            "subscription_status": subscription_status,
            "customer_type": customer_type,
            "days_since_failure": days_since_failure,
            "time_since_last_success": time_since_last_success,
            "device_risk_score": device_risk_score,
            "historical_failure_count": historical_failure_count,
            "recovered": recovered,
            "recovery_outcome": recovery_outcome,
        }
    )

    return df


@dataclass
class DataQualityReport:
    n_records: int
    n_columns: int
    missing_values: dict
    duplicate_transaction_ids: int
    invalid_amounts: int
    invalid_categoricals: dict
    invalid_retry_counts: int
    invalid_probabilities: dict
    class_distribution: dict

    def is_clean(self) -> bool:
        return (
            sum(self.missing_values.values()) == 0
            and self.duplicate_transaction_ids == 0
            and self.invalid_amounts == 0
            and sum(self.invalid_categoricals.values()) == 0
            and self.invalid_retry_counts == 0
            and sum(self.invalid_probabilities.values()) == 0
            and min(self.class_distribution.values()) > 0
        )

    def print_report(self) -> None:
        print("=" * 60)
        print("DATA QUALITY REPORT")
        print("=" * 60)
        print(f"Records: {self.n_records} | Columns: {self.n_columns}")
        print(f"Missing values (non-zero only): "
              f"{ {k: v for k, v in self.missing_values.items() if v > 0} or 'none'}")
        print(f"Duplicate transaction_ids: {self.duplicate_transaction_ids}")
        print(f"Invalid amounts (<=0): {self.invalid_amounts}")
        print(f"Invalid categorical values: "
              f"{ {k: v for k, v in self.invalid_categoricals.items() if v > 0} or 'none'}")
        print(f"Invalid retry counts (<0 or >2): {self.invalid_retry_counts}")
        print(f"Invalid probabilities (outside [0,1]): "
              f"{ {k: v for k, v in self.invalid_probabilities.items() if v > 0} or 'none'}")
        print(f"Class distribution (recovered): {self.class_distribution}")
        print(f"Overall status: {'PASS' if self.is_clean() else 'FAIL - see issues above'}")
        print("=" * 60)


def validate_dataset(df: pd.DataFrame) -> DataQualityReport:
    """Run structural and semantic validation checks on the generated dataset."""

    missing_values = df.isna().sum().to_dict()

    duplicate_transaction_ids = int(df["transaction_id"].duplicated().sum())

    invalid_amounts = int((df["amount"] <= 0).sum())

    invalid_categoricals = {
        "payment_method": int((~df["payment_method"].isin(PAYMENT_METHODS)).sum()),
        "failure_reason": int((~df["failure_reason"].isin(FAILURE_REASONS)).sum()),
        "customer_type": int((~df["customer_type"].isin(CUSTOMER_TYPES)).sum()),
        "subscription_status": int((~df["subscription_status"].isin(SUBSCRIPTION_STATUSES)).sum()),
    }

    invalid_retry_counts = int(((df["retry_count"] < 0) | (df["retry_count"] > 2)).sum())

    invalid_probabilities = {
        "previous_success_rate": int(
            ((df["previous_success_rate"] < 0) | (df["previous_success_rate"] > 1)).sum()
        ),
        "device_risk_score": int(
            ((df["device_risk_score"] < 0) | (df["device_risk_score"] > 1)).sum()
        ),
    }

    class_distribution = df["recovered"].value_counts().to_dict()
    class_distribution = {int(k): int(v) for k, v in class_distribution.items()}

    return DataQualityReport(
        n_records=len(df),
        n_columns=len(df.columns),
        missing_values=missing_values,
        duplicate_transaction_ids=duplicate_transaction_ids,
        invalid_amounts=invalid_amounts,
        invalid_categoricals=invalid_categoricals,
        invalid_retry_counts=invalid_retry_counts,
        invalid_probabilities=invalid_probabilities,
        class_distribution=class_distribution,
    )
