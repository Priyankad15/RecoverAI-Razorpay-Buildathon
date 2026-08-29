"""
Shared feature schema for the recovery-probability model.

Both training (train.py) and inference (predict.py) import from this module
so the two never drift apart.
"""

from __future__ import annotations

import pandas as pd

NUMERIC_FEATURES = [
    "amount",
    "retry_count",
    "previous_transactions",
    "previous_success_rate",
    "days_since_failure",
    "time_since_last_success",
    "device_risk_score",
    "historical_failure_count",
]

CATEGORICAL_FEATURES = [
    "payment_method",
    "failure_reason",
    "subscription_status",
    "customer_type",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

TARGET_COLUMN = "recovered"

# Sensible defaults used when a field is missing from a single prediction
# request - keeps predict() usable even with a partial payload.
DEFAULT_VALUES: dict[str, object] = {
    "amount": 1000.0,
    "retry_count": 0,
    "previous_transactions": 0,
    "previous_success_rate": 0.5,
    "days_since_failure": 0,
    "time_since_last_success": 720.0,
    "device_risk_score": 0.3,
    "historical_failure_count": 0,
    "payment_method": "card",
    "failure_reason": "network_timeout",
    "subscription_status": "none",
    "customer_type": "new",
}


def build_feature_frame(record: dict) -> pd.DataFrame:
    """Convert a single feature dict into a one-row DataFrame with the exact
    column set/order the trained pipeline expects, filling any missing
    fields with documented defaults."""

    row = {feature: record.get(feature, DEFAULT_VALUES[feature]) for feature in ALL_FEATURES}
    return pd.DataFrame([row], columns=ALL_FEATURES)
