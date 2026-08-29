"""
Tests for the Phase 2 ML pipeline. Everything here runs against small,
in-memory synthetic data - no external APIs, no dependency on a
pre-existing trained artifact on disk.
"""

from __future__ import annotations

import joblib
import pandas as pd
import pytest

from app.ml.data_generation import REQUIRED_COLUMNS, generate_synthetic_dataset, validate_dataset
from app.ml.evaluate import business_metrics, compute_test_metrics, threshold_analysis
from app.ml.features import ALL_FEATURES, TARGET_COLUMN, build_feature_frame
from app.ml.train import build_pipeline


# ---------- Dataset generation ----------

def test_dataset_meets_minimum_size():
    df = generate_synthetic_dataset(n_records=1000, seed=1)
    assert len(df) >= 1000


def test_dataset_has_required_columns():
    df = generate_synthetic_dataset(n_records=200, seed=1)
    for col in REQUIRED_COLUMNS:
        assert col in df.columns, f"Missing required column: {col}"


def test_no_duplicate_transaction_ids():
    df = generate_synthetic_dataset(n_records=500, seed=2)
    assert df["transaction_id"].duplicated().sum() == 0


def test_target_contains_both_classes():
    df = generate_synthetic_dataset(n_records=1000, seed=3)
    classes = set(df["recovered"].unique())
    assert classes == {0, 1}


def test_dataset_passes_quality_validation():
    df = generate_synthetic_dataset(n_records=500, seed=4)
    report = validate_dataset(df)
    assert report.is_clean()


def test_dataset_is_reproducible_with_same_seed():
    df1 = generate_synthetic_dataset(n_records=200, seed=99)
    df2 = generate_synthetic_dataset(n_records=200, seed=99)
    pd.testing.assert_frame_equal(df1, df2)


# ---------- Model training ----------

@pytest.fixture(scope="module")
def small_trained_pipeline():
    """Trains a pipeline on a small synthetic sample - fast, self-contained,
    no dependency on the full 3000-row dataset or any file on disk."""
    df = generate_synthetic_dataset(n_records=600, seed=7)
    X = df[ALL_FEATURES]
    y = df[TARGET_COLUMN]

    pipeline = build_pipeline()
    pipeline.fit(X, y)
    return pipeline, df


def test_model_trains_successfully(small_trained_pipeline):
    pipeline, df = small_trained_pipeline
    X = df[ALL_FEATURES]
    preds = pipeline.predict(X)
    assert len(preds) == len(df)


def test_model_can_be_saved_and_loaded(tmp_path, small_trained_pipeline):
    pipeline, _ = small_trained_pipeline
    artifact_path = tmp_path / "model.joblib"
    joblib.dump(pipeline, artifact_path)

    assert artifact_path.exists()
    loaded = joblib.load(artifact_path)
    assert hasattr(loaded, "predict_proba")


def test_prediction_probability_in_valid_range(small_trained_pipeline):
    pipeline, df = small_trained_pipeline
    X = df[ALL_FEATURES]
    proba = pipeline.predict_proba(X)[:, 1]
    assert (proba >= 0).all() and (proba <= 1).all()


def test_predict_recovery_output_schema(tmp_path, monkeypatch, small_trained_pipeline):
    """Tests the app.ml.predict schema contract using a locally trained
    model, without touching the real artifact path or requiring one to
    already exist on disk."""
    import app.ml.predict as predict_module

    pipeline, _ = small_trained_pipeline
    artifact_path = tmp_path / "model.joblib"
    joblib.dump(pipeline, artifact_path)

    predict_module._load_model_from.cache_clear()
    monkeypatch.setattr(predict_module, "ARTIFACT_PATH", artifact_path)

    record = {
        "amount": 4999.0,
        "retry_count": 0,
        "previous_transactions": 12,
        "previous_success_rate": 0.91,
        "days_since_failure": 1,
        "time_since_last_success": 48.0,
        "device_risk_score": 0.15,
        "historical_failure_count": 1,
        "payment_method": "upi",
        "failure_reason": "network_timeout",
        "subscription_status": "active",
        "customer_type": "returning",
    }

    result = predict_module.predict_recovery(record)

    assert set(result.keys()) == {"recovery_probability", "predicted_recovered"}
    assert 0.0 <= result["recovery_probability"] <= 1.0
    assert isinstance(result["predicted_recovered"], bool)

    predict_module._load_model_from.cache_clear()


def test_predict_recovery_handles_missing_fields_with_defaults():
    frame = build_feature_frame({"amount": 500.0})
    assert list(frame.columns) == ALL_FEATURES
    assert frame.loc[0, "amount"] == 500.0
    assert frame.loc[0, "payment_method"] == "card"  # documented default


# ---------- Evaluation ----------

def test_evaluation_completes_successfully(small_trained_pipeline):
    pipeline, df = small_trained_pipeline
    X = df[ALL_FEATURES]
    y = df[TARGET_COLUMN]
    y_proba = pipeline.predict_proba(X)[:, 1]

    metrics = compute_test_metrics(y, y_proba, threshold=0.5)
    for key in ["accuracy", "precision", "recall", "f1_score", "roc_auc"]:
        assert key in metrics
        assert 0.0 <= metrics[key] <= 1.0

    threshold_df = threshold_analysis(df, y, y_proba)
    assert len(threshold_df) == 7  # 0.20..0.80 in steps of 0.10
    assert "potential_revenue_selected_inr" in threshold_df.columns

    business = business_metrics(df, y_proba, threshold=0.5)
    assert business["total_failed_payment_amount_inr"] >= business["actual_recovered_amount_inr"]
