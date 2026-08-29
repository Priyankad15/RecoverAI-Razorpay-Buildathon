"""
Reusable prediction service.

This is what the AI agent (Phase 4) will call to get a recovery
probability for a single failed payment. Not wired into any API route yet
- that happens once the agent layer exists.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import joblib

from app.ml.features import build_feature_frame

BACKEND_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = BACKEND_DIR / "app" / "ml" / "artifacts" / "recovery_model.joblib"

DEFAULT_THRESHOLD = 0.5


@lru_cache
def _load_model_from(artifact_path: str):
    path = Path(artifact_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Model artifact not found at {path}. Run `python -m app.ml.train` first."
        )
    return joblib.load(path)


def _get_model():
    """Reads the module-level ARTIFACT_PATH at call time (not at import
    time), so tests can monkeypatch it. Caching happens in
    _load_model_from, keyed on the resolved path string."""
    return _load_model_from(str(ARTIFACT_PATH))


def predict_recovery(record: dict, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """
    Predict recovery probability for a single failed payment.

    Input:  a dict of feature values (missing fields fall back to
            documented defaults - see app.ml.features.DEFAULT_VALUES).
    Output: {"recovery_probability": float, "predicted_recovered": bool}
    """
    model = _get_model()
    X = build_feature_frame(record)
    probability = float(model.predict_proba(X)[0, 1])

    return {
        "recovery_probability": round(probability, 4),
        "predicted_recovered": probability >= threshold,
    }
