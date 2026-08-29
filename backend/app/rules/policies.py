"""
Policy values for the rules engine.

Every threshold here comes from app.core.config.Settings (i.e. from
environment variables), never a hard-coded literal buried in engine.py.
A Policy snapshot is attached to every decision so the audit trail shows
exactly which thresholds were in effect when a decision was made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings

POLICY_VERSION = "v1"


@dataclass(frozen=True)
class Policy:
    version: str
    max_automated_retries: int
    min_recovery_probability: float
    high_value_threshold_inr: float
    hard_stop_failure_reasons: frozenset[str] = field(default_factory=frozenset)


def get_active_policy() -> Policy:
    """Builds a Policy snapshot from current application settings.
    Called fresh on every evaluation, so a config change (e.g. via the
    /policies endpoint added in a later phase) takes effect immediately."""
    settings = get_settings()
    return Policy(
        version=POLICY_VERSION,
        max_automated_retries=settings.max_automated_retries,
        min_recovery_probability=settings.min_recovery_probability,
        high_value_threshold_inr=settings.high_value_threshold_inr,
        hard_stop_failure_reasons=frozenset(settings.hard_stop_failure_reasons_list),
    )
