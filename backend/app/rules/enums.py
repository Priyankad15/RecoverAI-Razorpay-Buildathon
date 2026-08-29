"""
Strict enums for the recovery rules engine.

Only these action strings and decision states are ever produced or
accepted. Nothing in this module accepts arbitrary strings from the
frontend, the future AI agent, or any other caller - the whole point of a
deterministic gate is that its vocabulary is fixed.
"""

from __future__ import annotations

from enum import Enum


class RecoveryAction(str, Enum):
    """The only actions the system is allowed to request. The future AI
    agent (Phase 4) may only recommend one of these - it cannot invent a
    new action string, and this engine rejects anything else."""

    RETRY = "RETRY"
    SEND_REMINDER = "SEND_REMINDER"
    SUGGEST_ALTERNATIVE_PAYMENT = "SUGGEST_ALTERNATIVE_PAYMENT"
    WAIT = "WAIT"
    STOP = "STOP"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Decision(str, Enum):
    """The only three outcomes the rules engine can produce. The AI agent
    never sets this value - only this engine does."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"


class ReasonCode(str, Enum):
    """Stable, machine-readable reason codes. New codes may be added over
    time, but existing values must never change meaning - the audit trail
    and any downstream consumers depend on that stability."""

    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    HARD_STOP_FAILURE_REASON = "HARD_STOP_FAILURE_REASON"
    MAX_RETRIES_REACHED = "MAX_RETRIES_REACHED"
    LOW_RECOVERY_PROBABILITY = "LOW_RECOVERY_PROBABILITY"
    HIGH_VALUE_TRANSACTION = "HIGH_VALUE_TRANSACTION"
    EVALUATION_ERROR = "EVALUATION_ERROR"


# Actions that never touch money or customer-facing recovery flow - always
# allowed once input/action validation passes, with no further checks.
PASSIVE_ACTIONS = frozenset({RecoveryAction.WAIT, RecoveryAction.STOP, RecoveryAction.HUMAN_REVIEW})

# Actions that engage with the recovery flow and are therefore subject to
# the hard-stop and high-value/human-approval checks.
ACTIVE_ACTIONS = frozenset(
    {RecoveryAction.RETRY, RecoveryAction.SEND_REMINDER, RecoveryAction.SUGGEST_ALTERNATIVE_PAYMENT}
)

# Only RETRY actually re-attempts a charge, so only RETRY is subject to
# the retry-count limit and the minimum-recovery-probability floor.
RETRY_GATED_ACTIONS = frozenset({RecoveryAction.RETRY})
