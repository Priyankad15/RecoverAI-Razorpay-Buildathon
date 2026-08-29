"""
Enums for the Phase 5 execution layer.

ExecutionStatus values are deliberately more specific than a bare
SUCCESS/FAILED - BLOCKED and PENDING_HUMAN_APPROVAL exist precisely so an
audit reader (or a test) can tell "the rules engine refused this" apart
from "the simulated attempt itself failed" apart from "this action never
even needed a monetary attempt" (COMPLETED).
"""

from __future__ import annotations

from enum import Enum


class ExecutionStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"                  # execution never attempted (error, invalid input)
    BLOCKED = "BLOCKED"                             # rules engine returned BLOCK
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"  # rules engine returned HUMAN_APPROVAL
    SUCCESS = "SUCCESS"                             # monetary action executed and succeeded
    FAILED = "FAILED"                               # monetary action executed and failed
    COMPLETED = "COMPLETED"                         # non-monetary action executed (STOP/WAIT/HUMAN_REVIEW/outreach)


class ForcedOutcome(str, Enum):
    """Explicit, caller-controlled simulation outcome for a RETRY
    execution - see RecoveryExecutor. Never chosen by randomness."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
