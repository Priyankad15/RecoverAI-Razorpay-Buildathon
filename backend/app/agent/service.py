"""
AI recovery agent orchestration.

Two public entrypoints:

- get_agent_recommendation(payment)         -> AgentRecommendation
    The agent's advisory output alone. Never raises.

- get_recommendation_and_decision(payment)  -> AgentRulesResult
    The full Phase 4 workflow: agent recommends, then the Phase 3 rules
    engine decides. This is the function any future caller (API route,
    batch job, Phase 5 execution) should actually use - it guarantees the
    agent's output is always run through the rules engine before anything
    else looks at it.

FAIL-SAFE BEHAVIOR (documented, per Phase 4 requirements)
-----------------------------------------------------------
If the provider is unavailable, times out, returns malformed JSON, an
unsupported action, an out-of-range confidence, or anything else
unexpected happens, get_agent_recommendation NEVER raises and NEVER
guesses. It returns a fallback AgentRecommendation with:
    requested_action = "HUMAN_REVIEW"
    confidence        = 0.0
    is_mock           = True
    reason_codes      = ["AGENT_FALLBACK", ...]
This fallback is still run through the Phase 3 rules engine exactly like
any other recommendation - HUMAN_REVIEW is itself a passive action, so it
is always ALLOWed by the rules engine, but the amount/probability that
produced it remains fully visible in the audit-ready output.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from app.agent.providers import LLMProvider, ProviderError, get_default_provider
from app.agent.schemas import AgentRecommendation, AgentRulesResult, SafetyDecisionSummary
from app.ml.predict import predict_recovery
from app.rules.engine import evaluate_recovery_action
from app.rules.policies import Policy

FALLBACK_ACTION = "HUMAN_REVIEW"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fallback_recommendation(transaction_id: str, provider_name: str, reason: str) -> AgentRecommendation:
    reason_tag = "".join(ch if ch.isalnum() else "_" for ch in reason.upper())[:60]
    return AgentRecommendation(
        transaction_id=transaction_id or "UNKNOWN",
        requested_action=FALLBACK_ACTION,
        confidence=0.0,
        explanation=(
            "[SYSTEM FALLBACK] The agent could not produce a valid recommendation "
            f"({reason}). Defaulting to the safe fallback action so a human reviews "
            "this transaction instead of an unsafe automated action being requested."
        ),
        reason_codes=["AGENT_FALLBACK", reason_tag],
        provider=provider_name or "unknown",
        is_mock=True,
        model=None,
        generated_at=_now_iso(),
    )


def _resolve_recovery_probability(payment: dict) -> float:
    """Reuses Phase 2's prediction service - never re-implements ML
    inference here. If the caller already supplied recovery_probability
    (e.g. from a prior call in the same request), that value is reused
    instead of recomputing, so a single logical recommendation always
    uses one consistent probability."""
    if payment.get("recovery_probability") is not None:
        return float(payment["recovery_probability"])
    return predict_recovery(payment)["recovery_probability"]


def get_agent_recommendation(payment: dict, provider: LLMProvider | None = None) -> AgentRecommendation:
    """
    Produces a REQUESTED action only - advisory, never authoritative.
    Always returns a valid AgentRecommendation; never raises.
    """
    active_provider = provider or get_default_provider()
    transaction_id = str(payment.get("transaction_id") or "UNKNOWN")

    try:
        recovery_probability = _resolve_recovery_probability(payment)

        context = dict(payment)
        context["transaction_id"] = transaction_id
        context["recovery_probability"] = recovery_probability

        raw = active_provider.generate_recommendation(context)

        return AgentRecommendation(
            transaction_id=transaction_id,
            requested_action=raw["requested_action"],
            confidence=float(raw["confidence"]),
            explanation=str(raw["explanation"]),
            reason_codes=[str(code) for code in raw.get("reason_codes", [])],
            provider=active_provider.name,
            is_mock=active_provider.is_mock,
            model=raw.get("model"),
            generated_at=_now_iso(),
        )

    except ProviderError as exc:
        return _fallback_recommendation(transaction_id, active_provider.name, f"provider error: {exc}")
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        return _fallback_recommendation(
            transaction_id, active_provider.name, f"invalid agent output: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 - intentional catch-all, fail safe
        return _fallback_recommendation(
            transaction_id,
            getattr(active_provider, "name", "unknown"),
            f"unexpected error: {type(exc).__name__}",
        )


def get_recommendation_and_decision(
    payment: dict,
    provider: LLMProvider | None = None,
    policy: Policy | None = None,
) -> AgentRulesResult:
    """
    The full Phase 4 workflow. The agent's recommendation is NEVER treated
    as authorization - final_decision always comes from the Phase 3 rules
    engine, never from the agent, even when they agree.
    """
    recovery_probability = None
    try:
        recovery_probability = _resolve_recovery_probability(payment)
    except Exception:  # noqa: BLE001 - if ML fails, proceed with None; the
        # rules engine's own input validation will reject a missing/invalid
        # probability and fail closed (BLOCK), which is the correct
        # behavior when the system can't establish a probability at all.
        pass

    payment_with_probability = dict(payment)
    payment_with_probability["recovery_probability"] = recovery_probability

    recommendation = get_agent_recommendation(payment_with_probability, provider)

    rules_raw_input = {
        "transaction_id": recommendation.transaction_id,
        "amount": payment.get("amount"),
        "recovery_probability": recovery_probability,
        "retry_count": payment.get("retry_count"),
        "requested_action": recommendation.requested_action,
        "failure_reason": payment.get("failure_reason"),
    }
    safety_decision = evaluate_recovery_action(rules_raw_input, policy)

    safety_summary = SafetyDecisionSummary(
        decision=safety_decision.decision,
        reason_codes=safety_decision.reason_codes,
        requires_human_approval=safety_decision.requires_human_approval,
        explanation=safety_decision.explanation,
        policy_version=safety_decision.policy_version,
    )

    return AgentRulesResult(
        agent=recommendation,
        safety=safety_summary,
        final_decision=safety_decision.decision,
    )
