"""
RecoveryExecutor: the ONLY component permitted to simulate a recovery
action. It has no knowledge of whether an action is "allowed" - it just
runs whatever action it's given, once called. The caller (app.execution.service)
is responsible for only ever calling this when the Phase 3 rules engine
returned ALLOW; the executor itself does not re-check policy, because
duplicating safety rules here would be exactly the "AI/executor with its
own independent safety rules" anti-pattern the architecture forbids.

TEST MODE ONLY. No real Razorpay call is ever made. No real money moves.
Every result this class returns is explicitly labeled
"[SIMULATION / TEST MODE]" in its `detail` field.

How the demo/tests choose an outcome (deterministic, not random)
------------------------------------------------------------------
RETRY is the only action with a genuine SUCCESS/FAILURE outcome (it's
the only one that attempts to move money). That outcome is controlled
explicitly:

1. `forced_outcome` argument to `execute()`, if given, wins.
2. Otherwise, `transaction["simulation_outcome"]` (a field the caller can
   set on the payment dict), if present, is used.
3. Otherwise, defaults to SUCCESS.

This mirrors how Razorpay's own Test Mode works (specific test card
numbers deterministically produce success or failure) - nothing here is
random, so every demo run is reproducible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.execution.enums import ExecutionStatus, ForcedOutcome
from app.execution.models import ExecutionResult
from app.rules.enums import RecoveryAction

_MONETARY_ACTIONS = {RecoveryAction.RETRY}
_OUTREACH_ACTIONS = {RecoveryAction.SEND_REMINDER, RecoveryAction.SUGGEST_ALTERNATIVE_PAYMENT}
_PASSIVE_ACTIONS = {RecoveryAction.WAIT, RecoveryAction.STOP, RecoveryAction.HUMAN_REVIEW}


class UnsupportedExecutionAction(ValueError):
    """Raised when execute() is asked to run something outside the
    approved RecoveryAction enum. No arbitrary action strings reach
    execution - this is the executor's own closed action set, enforced
    independent of anything the rules engine already checked."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecoveryExecutor:
    """Simulation/test-mode execution adapter for approved recovery actions."""

    def execute(
        self,
        action: str,
        transaction: dict,
        forced_outcome: str | None = None,
    ) -> ExecutionResult:
        try:
            recovery_action = RecoveryAction(action)
        except ValueError as exc:
            raise UnsupportedExecutionAction(
                f"'{action}' is not an approved recovery action and cannot be executed"
            ) from exc

        amount = float(transaction.get("amount") or 0.0)
        now = _now_iso()

        if recovery_action in _MONETARY_ACTIONS:
            return self._execute_monetary(recovery_action, amount, transaction, forced_outcome, now)

        if recovery_action in _OUTREACH_ACTIONS:
            return ExecutionResult(
                action=recovery_action.value,
                status=ExecutionStatus.COMPLETED.value,
                simulation_mode=True,
                recovered_amount=0.0,
                failure_reason=None,
                executed_at=now,
                detail=(
                    f"[SIMULATION / TEST MODE] {recovery_action.value} simulated as sent. "
                    "This is outreach only - it does not itself move money."
                ),
            )

        # _PASSIVE_ACTIONS: WAIT / STOP / HUMAN_REVIEW - nothing to run.
        return ExecutionResult(
            action=recovery_action.value,
            status=ExecutionStatus.COMPLETED.value,
            simulation_mode=True,
            recovered_amount=0.0,
            failure_reason=None,
            executed_at=now,
            detail=f"[SIMULATION / TEST MODE] {recovery_action.value} recorded - passive action, no execution required.",
        )

    def _execute_monetary(
        self,
        recovery_action: RecoveryAction,
        amount: float,
        transaction: dict,
        forced_outcome: str | None,
        now: str,
    ) -> ExecutionResult:
        outcome = forced_outcome or transaction.get("simulation_outcome") or ForcedOutcome.SUCCESS.value

        if outcome == ForcedOutcome.SUCCESS.value:
            return ExecutionResult(
                action=recovery_action.value,
                status=ExecutionStatus.SUCCESS.value,
                simulation_mode=True,
                recovered_amount=amount,
                failure_reason=None,
                executed_at=now,
                detail=(
                    f"[SIMULATION / TEST MODE] {recovery_action.value} simulated as SUCCESSFUL. "
                    "No real Razorpay call was made; no real money moved."
                ),
            )

        if outcome == ForcedOutcome.FAILURE.value:
            failure_reason = transaction.get("simulated_failure_reason", "simulated_retry_failure")
            return ExecutionResult(
                action=recovery_action.value,
                status=ExecutionStatus.FAILED.value,
                simulation_mode=True,
                recovered_amount=0.0,
                failure_reason=failure_reason,
                executed_at=now,
                detail=(
                    f"[SIMULATION / TEST MODE] {recovery_action.value} simulated as FAILED "
                    f"({failure_reason}). No revenue recovered."
                ),
            )

        raise ValueError(
            f"Unsupported simulation_outcome '{outcome}' - must be '{ForcedOutcome.SUCCESS.value}' "
            f"or '{ForcedOutcome.FAILURE.value}'"
        )


# --- Added in Phase 7 ---
#
# Phase 7 introduces a second executor (RazorpayTestExecutor, in
# app/integrations/razorpay/executor.py) that satisfies the same
# interface as this class: execute(action, transaction, forced_outcome=None)
# -> ExecutionResult. `SimulationExecutor` is the Phase 7-facing name for
# exactly this class - it is not a new implementation, just an explicit
# alias so the two concrete executors (SimulationExecutor,
# RazorpayTestExecutor) are named consistently with the architecture:
#
#   RecoveryExecutor (interface/name every executor conforms to)
#         |
#         +-- SimulationExecutor   (this class - in-process, deterministic, no network)
#         +-- RazorpayTestExecutor (real Razorpay Test Mode API calls)
#
# `RecoveryExecutor` is intentionally NOT turned into an abstract base
# class here: Phase 5/6 code and tests construct it directly
# (`RecoveryExecutor()`), subclass it as a spy/broken-executor test
# double, and type-hint against it throughout - forcing it to become
# non-instantiable would break all of that for a naming change alone.
# Both names point at the same concrete, fully-instantiable class.
SimulationExecutor = RecoveryExecutor
