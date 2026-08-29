"""
Deterministic safety / rules engine.

WHY THIS EXISTS
----------------
The AI agent (Phase 4) will look at a failed payment and *recommend* an
action. An LLM recommendation is not a safe basis for a money-related
action on its own - it can be wrong, inconsistent, or manipulated by
adversarial input. This module is the single, deterministic gate that
every recommended action must pass through before anything is executed.
It contains no LLM calls, no network calls, and no non-deterministic
behavior: the same input always produces the same output.

WHY THE AI CANNOT BYPASS IT
----------------------------
The AI agent's output type (Phase 4) will only ever be a *requested*
action - a string the agent proposes. It is never treated as a decision.
Only `evaluate_recovery_action` in this module is allowed to produce a
`Decision` (ALLOW / BLOCK / HUMAN_APPROVAL), and every execution path in
later phases must call this function and act on *its* output, not on
anything the agent claims about safety. There is no code path anywhere
in this module that accepts a decision, reason, or threshold from a
caller - policy values come only from `app.rules.policies.get_active_policy`,
which itself reads only from environment-configured application settings.

RULE EVALUATION ORDER (deterministic, documented)
--------------------------------------------------
1. Validate input          - malformed input fails closed (BLOCK)
2. Validate requested action - unsupported action fails closed (BLOCK)
3. Check hard-stop conditions - e.g. a RETRY on a fraud-flagged failure
   reason is blocked outright, before any other check runs. Hard stops
   exist to encode non-negotiable safety facts that shouldn't be
   softened by a high probability score or a low retry count.
4. Check retry limit        - only applies to RETRY (the only action that
   re-attempts a charge). Runs before the probability check because a
   transaction that has already exhausted its retries shouldn't need a
   probability calculation to be explained as blocked.
5. Check recovery probability - only applies to RETRY.
6. Check transaction amount / human-approval threshold - applies to any
   action that engages with the recovery flow (RETRY, SEND_REMINDER,
   SUGGEST_ALTERNATIVE_PAYMENT). Runs after the BLOCK-tier checks because
   a transaction that's already going to be blocked doesn't need to be
   escalated to a human as well - BLOCK further checks are moot.
7. Resolve final decision by precedence: BLOCK > HUMAN_APPROVAL > ALLOW.
8. Return a structured, explainable decision.

FAIL-CLOSED BEHAVIOR
---------------------
Any invalid input, unsupported action, or unexpected internal error
results in BLOCK. The engine never defaults to ALLOW when something is
uncertain - see `_block()` and the top-level try/except in
`evaluate_recovery_action`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from app.rules.enums import (
    ACTIVE_ACTIONS,
    PASSIVE_ACTIONS,
    RETRY_GATED_ACTIONS,
    Decision,
    ReasonCode,
    RecoveryAction,
)
from app.rules.models import RecoveryActionRequest, RuleEngineDecision
from app.rules.policies import Policy, get_active_policy

# Precedence: if any BLOCK-tier reason is present, the decision is BLOCK
# regardless of any HUMAN_APPROVAL-tier reason also being present. This
# resolves cases where multiple conditions trigger simultaneously (e.g. a
# high-value transaction that has also exhausted its retry limit).
BLOCK_TIER_CODES = frozenset(
    {
        ReasonCode.HARD_STOP_FAILURE_REASON,
        ReasonCode.MAX_RETRIES_REACHED,
        ReasonCode.LOW_RECOVERY_PROBABILITY,
    }
)
HUMAN_APPROVAL_TIER_CODES = frozenset({ReasonCode.HIGH_VALUE_TRANSACTION})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decision(
    *,
    transaction_id: str,
    requested_action: str,
    decision: Decision,
    reason_codes: list[ReasonCode],
    explanation: str,
    policy_version: str,
) -> RuleEngineDecision:
    return RuleEngineDecision(
        transaction_id=transaction_id,
        requested_action=requested_action,
        decision=decision.value,
        reason_codes=[code.value for code in reason_codes],
        explanation=explanation,
        requires_human_approval=(decision == Decision.HUMAN_APPROVAL),
        policy_version=policy_version,
        evaluated_at=_now_iso(),
    )


def _block(
    *,
    transaction_id: str,
    requested_action: str,
    reason_code: ReasonCode,
    explanation: str,
    policy_version: str = "unknown",
) -> RuleEngineDecision:
    """Fail-closed helper: always returns BLOCK. Used for validation
    failures and unexpected errors, where ALLOW must never be the default."""
    return _decision(
        transaction_id=transaction_id,
        requested_action=requested_action,
        decision=Decision.BLOCK,
        reason_codes=[reason_code],
        explanation=explanation,
        policy_version=policy_version,
    )


def evaluate_recovery_action(
    raw_input: dict | RecoveryActionRequest,
    policy: Policy | None = None,
) -> RuleEngineDecision:
    """
    Public entrypoint. Accepts either a raw dict (as it would arrive from
    an API request or the future AI agent) or an already-validated
    RecoveryActionRequest. Always returns a RuleEngineDecision - never
    raises - because a caller (e.g. an execution service) must always
    have a decision to act on, and the safe action on any internal
    failure is BLOCK, not an unhandled exception that a caller might
    mishandle as "no objection".
    """
    try:
        return _evaluate(raw_input, policy)
    except Exception as exc:  # noqa: BLE001 - intentional catch-all, fail closed
        txn_id = "UNKNOWN"
        action = "UNKNOWN"
        if isinstance(raw_input, dict):
            txn_id = str(raw_input.get("transaction_id", "UNKNOWN"))
            action = str(raw_input.get("requested_action", "UNKNOWN"))
        elif isinstance(raw_input, RecoveryActionRequest):
            txn_id = raw_input.transaction_id
            action = raw_input.requested_action
        return _block(
            transaction_id=txn_id,
            requested_action=action,
            reason_code=ReasonCode.EVALUATION_ERROR,
            explanation=(
                "The rules engine could not evaluate this request safely due to an "
                f"internal error ({type(exc).__name__}). Failing closed: action blocked."
            ),
        )


def _evaluate(
    raw_input: dict | RecoveryActionRequest,
    policy: Policy | None,
) -> RuleEngineDecision:
    active_policy = policy or get_active_policy()

    # ---- Step 1: validate input ----
    if isinstance(raw_input, RecoveryActionRequest):
        request = raw_input
    else:
        try:
            request = RecoveryActionRequest(**raw_input)
        except ValidationError as exc:
            txn_id = str(raw_input.get("transaction_id", "UNKNOWN")) if isinstance(raw_input, dict) else "UNKNOWN"
            action = str(raw_input.get("requested_action", "UNKNOWN")) if isinstance(raw_input, dict) else "UNKNOWN"
            return _block(
                transaction_id=txn_id,
                requested_action=action,
                reason_code=ReasonCode.INVALID_INPUT,
                explanation=f"Input failed validation and was rejected: {_summarize_validation_error(exc)}",
                policy_version=active_policy.version,
            )

    # ---- Step 2: validate requested action ----
    try:
        action = RecoveryAction(request.requested_action)
    except ValueError:
        return _block(
            transaction_id=request.transaction_id,
            requested_action=request.requested_action,
            reason_code=ReasonCode.UNSUPPORTED_ACTION,
            explanation=(
                f"'{request.requested_action}' is not a supported recovery action. "
                f"Allowed actions: {', '.join(a.value for a in RecoveryAction)}."
            ),
            policy_version=active_policy.version,
        )

    # Passive actions never touch money or the recovery flow - always
    # allowed once input/action validation has passed.
    if action in PASSIVE_ACTIONS:
        return _decision(
            transaction_id=request.transaction_id,
            requested_action=action.value,
            decision=Decision.ALLOW,
            reason_codes=[],
            explanation=f"'{action.value}' is a passive action that does not move money or "
            "execute a recovery attempt, so it is allowed without further checks.",
            policy_version=active_policy.version,
        )

    reason_codes: list[ReasonCode] = []

    # ---- Step 3: hard-stop conditions ----
    if action in RETRY_GATED_ACTIONS and request.failure_reason in active_policy.hard_stop_failure_reasons:
        reason_codes.append(ReasonCode.HARD_STOP_FAILURE_REASON)

    # ---- Step 4: retry limit ----
    if action in RETRY_GATED_ACTIONS and request.retry_count >= active_policy.max_automated_retries:
        reason_codes.append(ReasonCode.MAX_RETRIES_REACHED)

    # ---- Step 5: recovery probability ----
    if action in RETRY_GATED_ACTIONS and request.recovery_probability < active_policy.min_recovery_probability:
        reason_codes.append(ReasonCode.LOW_RECOVERY_PROBABILITY)

    # ---- Step 6: transaction amount / human-approval threshold ----
    if action in ACTIVE_ACTIONS and request.amount >= active_policy.high_value_threshold_inr:
        reason_codes.append(ReasonCode.HIGH_VALUE_TRANSACTION)

    # ---- Step 7: resolve final decision by precedence ----
    final_decision = _resolve_decision(reason_codes)

    # ---- Step 8: build explanation and return ----
    explanation = _build_explanation(action, final_decision, reason_codes, active_policy)

    return _decision(
        transaction_id=request.transaction_id,
        requested_action=action.value,
        decision=final_decision,
        reason_codes=reason_codes,
        explanation=explanation,
        policy_version=active_policy.version,
    )


def _resolve_decision(reason_codes: list[ReasonCode]) -> Decision:
    """BLOCK takes precedence over HUMAN_APPROVAL, which takes precedence
    over ALLOW. This is what makes the outcome deterministic when
    multiple conditions trigger at once (e.g. retry limit reached AND
    high-value transaction)."""
    codes = set(reason_codes)
    if codes & BLOCK_TIER_CODES:
        return Decision.BLOCK
    if codes & HUMAN_APPROVAL_TIER_CODES:
        return Decision.HUMAN_APPROVAL
    return Decision.ALLOW


_EXPLANATIONS: dict[ReasonCode, str] = {
    ReasonCode.HARD_STOP_FAILURE_REASON: (
        "the failure reason is on the hard-stop list and automated retry is never permitted for it"
    ),
    ReasonCode.MAX_RETRIES_REACHED: "the maximum number of automated retries has already been reached",
    ReasonCode.LOW_RECOVERY_PROBABILITY: (
        "the predicted recovery probability is below the minimum threshold for automated retry"
    ),
    ReasonCode.HIGH_VALUE_TRANSACTION: (
        "the transaction amount is at or above the high-value threshold requiring human approval"
    ),
}


def _build_explanation(
    action: RecoveryAction,
    decision: Decision,
    reason_codes: list[ReasonCode],
    policy: Policy,
) -> str:
    if decision == Decision.ALLOW:
        return (
            f"'{action.value}' is permitted: it did not trigger the retry limit, the minimum "
            "recovery-probability floor, any hard-stop condition, or the high-value approval "
            "threshold under the active policy."
        )

    reasons_text = "; ".join(_EXPLANATIONS[code] for code in reason_codes if code in _EXPLANATIONS)

    if decision == Decision.BLOCK:
        return f"'{action.value}' is blocked because {reasons_text}."
    return f"'{action.value}' requires human approval because {reasons_text}."


def _summarize_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) or "input"
        parts.append(f"{field}: {error['msg']}")
    return "; ".join(parts)
