"""
Full evaluation of the trained recovery-probability model on the held-out
test set. Reruns independently of train.py (loads the saved artifact and
saved test split), so it can be re-executed without retraining.

Usage (from the backend/ directory):
    python -m app.ml.evaluate

Reads:  data/processed/test.csv
        backend/app/ml/artifacts/recovery_model.joblib
Writes: data/reports/evaluation_report.json
        data/reports/threshold_analysis.csv
        data/reports/feature_importance.csv
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.ml.features import ALL_FEATURES, TARGET_COLUMN

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

TEST_DATA_PATH = REPO_ROOT / "data" / "processed" / "test.csv"
ARTIFACT_PATH = BACKEND_DIR / "app" / "ml" / "artifacts" / "recovery_model.joblib"
REPORTS_DIR = REPO_ROOT / "data" / "reports"

THRESHOLDS = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]


def _load_test_set() -> pd.DataFrame:
    if not TEST_DATA_PATH.exists():
        raise FileNotFoundError(f"{TEST_DATA_PATH} not found. Run `python -m app.ml.train` first.")
    return pd.read_csv(TEST_DATA_PATH)


def _load_model():
    if not ARTIFACT_PATH.exists():
        raise FileNotFoundError(f"{ARTIFACT_PATH} not found. Run `python -m app.ml.train` first.")
    return joblib.load(ARTIFACT_PATH)


def compute_test_metrics(y_true, y_proba, threshold: float = 0.5) -> dict:
    """All metrics below are computed on the TEST SET ONLY - never on
    training data. Nothing here is hard-coded."""
    y_pred = (y_proba >= threshold).astype(int)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()

    return {
        "threshold_used": threshold,
        "n_test_records": int(len(y_true)),
        "n_recovered": int((y_true == 1).sum()),
        "n_not_recovered": int((y_true == 0).sum()),
        "positive_class_rate": round(float((y_true == 1).mean()), 4),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_proba)), 4),
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
    }


def threshold_analysis(df_test: pd.DataFrame, y_true, y_proba) -> pd.DataFrame:
    rows = []
    for t in THRESHOLDS:
        y_pred = (y_proba >= t).astype(int)
        potential_revenue_selected = float(df_test.loc[y_pred == 1, "amount"].sum())
        rows.append(
            {
                "threshold": t,
                "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
                "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
                "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
                "n_predicted_recoverable": int((y_pred == 1).sum()),
                "potential_revenue_selected_inr": round(potential_revenue_selected, 2),
            }
        )
    return pd.DataFrame(rows)


def recommend_threshold(threshold_df: pd.DataFrame) -> dict:
    """Recommend the threshold with the highest F1 as an initial default -
    a reasonable, explainable starting point. The final action policy
    (which may weight recall higher, per the business framing in the
    architecture doc) is decided in a later phase by the rules engine."""
    best_row = threshold_df.loc[threshold_df["f1_score"].idxmax()]
    return {
        "recommended_threshold": float(best_row["threshold"]),
        "reason": (
            "Highest F1 score on the test set among the evaluated thresholds, "
            "balancing false positives (wasted retries) against false negatives "
            "(missed recoverable revenue). Recall-weighted thresholds can be "
            "revisited once the rules engine's cost of a wasted retry vs. a "
            "missed recovery is defined in a later phase."
        ),
    }


def business_metrics(df_test: pd.DataFrame, y_proba, threshold: float) -> dict:
    y_pred = (y_proba >= threshold).astype(int)

    total_failed_amount = float(df_test["amount"].sum())
    actual_recovered_amount = float(df_test.loc[df_test[TARGET_COLUMN] == 1, "amount"].sum())
    predicted_recoverable_amount = float(df_test.loc[y_pred == 1, "amount"].sum())
    avg_transaction_amount = float(df_test["amount"].mean())

    return {
        "note": (
            "actual_* figures are ground truth from the held-out test set. "
            "predicted_* figures are model output and have NOT been executed "
            "or confirmed - they must not be described as recovered revenue."
        ),
        "total_failed_payment_amount_inr": round(total_failed_amount, 2),
        "actual_recovered_amount_inr": round(actual_recovered_amount, 2),
        "predicted_potentially_recoverable_amount_inr_at_threshold": round(
            predicted_recoverable_amount, 2
        ),
        "threshold_used_for_prediction": threshold,
        "average_transaction_amount_inr": round(avg_transaction_amount, 2),
    }


def feature_importance(pipeline) -> pd.DataFrame:
    preprocessor = pipeline.named_steps["preprocessor"]
    classifier = pipeline.named_steps["classifier"]

    feature_names = preprocessor.get_feature_names_out()
    importances = classifier.feature_importances_

    df = pd.DataFrame({"feature": feature_names, "importance": importances})
    return df.sort_values("importance", ascending=False).reset_index(drop=True)


def evaluate() -> dict:
    df_test = _load_test_set()
    pipeline = _load_model()

    X_test = df_test[ALL_FEATURES]
    y_test = df_test[TARGET_COLUMN]
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    metrics = compute_test_metrics(y_test, y_proba, threshold=0.5)
    threshold_df = threshold_analysis(df_test, y_test, y_proba)
    recommendation = recommend_threshold(threshold_df)
    business = business_metrics(df_test, y_proba, threshold=recommendation["recommended_threshold"])
    importance_df = feature_importance(pipeline)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    threshold_df.to_csv(REPORTS_DIR / "threshold_analysis.csv", index=False)
    importance_df.to_csv(REPORTS_DIR / "feature_importance.csv", index=False)

    report = {
        "test_set_metrics": metrics,
        "threshold_analysis": threshold_df.to_dict(orient="records"),
        "recommended_threshold": recommendation,
        "business_metrics": business,
        "top_features": importance_df.head(10).to_dict(orient="records"),
    }
    with open(REPORTS_DIR / "evaluation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    _print_report(metrics, threshold_df, recommendation, business, importance_df)

    return report


def _print_report(metrics, threshold_df, recommendation, business, importance_df) -> None:
    print("=" * 60)
    print("TEST-SET METRICS (held-out, never seen during training)")
    print("=" * 60)
    for k, v in metrics.items():
        print(f"{k}: {v}")

    print()
    print("=" * 60)
    print("THRESHOLD ANALYSIS")
    print("=" * 60)
    print(threshold_df.to_string(index=False))
    print()
    print(f"Recommended threshold: {recommendation['recommended_threshold']}")
    print(f"Reason: {recommendation['reason']}")

    print()
    print("=" * 60)
    print("BUSINESS METRICS (test set)")
    print("=" * 60)
    for k, v in business.items():
        print(f"{k}: {v}")

    print()
    print("=" * 60)
    print("TOP 10 FEATURE IMPORTANCES")
    print("=" * 60)
    print(importance_df.head(10).to_string(index=False))
    print("=" * 60)
    print(f"Full report written to: {REPORTS_DIR / 'evaluation_report.json'}")


if __name__ == "__main__":
    evaluate()
