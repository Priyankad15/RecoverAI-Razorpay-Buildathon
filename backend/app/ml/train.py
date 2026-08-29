"""
Trains the XGBoost recovery-probability model.

Usage (from the backend/ directory):
    python -m app.ml.train

Reads:  data/raw/synthetic_payments.csv   (produced by scripts/generate_dataset.py)
Writes: data/processed/train.csv, data/processed/test.csv
        backend/app/ml/artifacts/recovery_model.joblib
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from app.ml.data_generation import REQUIRED_COLUMNS
from app.ml.features import ALL_FEATURES, TARGET_COLUMN
from app.ml.preprocessing import build_preprocessor

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

RAW_DATA_PATH = REPO_ROOT / "data" / "raw" / "synthetic_payments.csv"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
ARTIFACT_PATH = BACKEND_DIR / "app" / "ml" / "artifacts" / "recovery_model.joblib"

RANDOM_SEED = 42
TEST_SIZE = 0.20


def build_pipeline() -> Pipeline:
    """Full preprocessing + model pipeline. Reasonable, non-tuned
    hyperparameters - this is a first honest baseline, not a
    metric-chasing configuration."""
    return Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            (
                "classifier",
                XGBClassifier(
                    n_estimators=200,
                    max_depth=4,
                    learning_rate=0.08,
                    subsample=0.85,
                    colsample_bytree=0.85,
                    eval_metric="logloss",
                    random_state=RANDOM_SEED,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def train() -> Path:
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at {RAW_DATA_PATH}. "
            "Run `python -m scripts.generate_dataset` first."
        )

    df = pd.read_csv(RAW_DATA_PATH)
    missing_cols = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Raw dataset is missing required columns: {missing_cols}")

    X = df[ALL_FEATURES]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test, df_train, df_test = _stratified_split_with_full_rows(df, X, y)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_train.to_csv(PROCESSED_DIR / "train.csv", index=False)
    df_test.to_csv(PROCESSED_DIR / "test.csv", index=False)

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, ARTIFACT_PATH)

    train_accuracy = pipeline.score(X_train, y_train)
    test_accuracy = pipeline.score(X_test, y_test)

    print("=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Train rows: {len(X_train)} | Test rows: {len(X_test)}")
    print(f"Train accuracy: {train_accuracy:.4f}")
    print(f"Test accuracy:  {test_accuracy:.4f}  (quick check - see `python -m app.ml.evaluate` for full metrics)")
    print(f"Model artifact saved to: {ARTIFACT_PATH}")
    print("=" * 60)

    return ARTIFACT_PATH


def _stratified_split_with_full_rows(df: pd.DataFrame, X: pd.DataFrame, y: pd.Series):
    """Splits X/y for training while keeping the corresponding full rows
    (including transaction_id, amount, recovery_outcome) so later
    evaluation/business-metric steps can use them without leakage."""
    train_idx, test_idx = train_test_split(
        df.index,
        test_size=TEST_SIZE,
        random_state=RANDOM_SEED,
        stratify=y,
    )
    X_train, X_test = X.loc[train_idx], X.loc[test_idx]
    y_train, y_test = y.loc[train_idx], y.loc[test_idx]
    df_train, df_test = df.loc[train_idx].reset_index(drop=True), df.loc[test_idx].reset_index(drop=True)
    return X_train, X_test, y_train, y_test, df_train, df_test


if __name__ == "__main__":
    train()
