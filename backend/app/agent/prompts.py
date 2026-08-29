"""
Prompt design for the AI recovery agent.

Deliberately contains NO copies of Phase 3's monetary policy thresholds
(max retries, probability floor, high-value amount). The agent recommends;
it never needs to know - and must never independently enforce - the exact
values that gate execution, because those values live in one place only
(app.core.config / .env) and are evaluated by app.rules.engine. Baking a
threshold into the prompt would risk it drifting out of sync with the
real configuration and would blur the "AI recommends, rules decide" line
this whole architecture depends on.
"""

from __future__ import annotations

import json

from app.rules.enums import RecoveryAction

ALLOWED_ACTIONS = [action.value for action in RecoveryAction]

SYSTEM_PROMPT = f"""ROLE:
You are a revenue recovery recommendation agent for RecoverAI, a payment
recovery system used by a merchant on Razorpay.

RESPONSIBILITY:
Analyze a single failed payment and recommend the safest useful recovery
action for it.

CONSTRAINTS:
- You are advisory only. You cannot execute financial actions.
- You cannot change policies, thresholds, or safety rules.
- You cannot bypass or override the deterministic safety system that
  reviews your recommendation afterward.
- You must choose exactly one action from this fixed list, and nothing
  else: {", ".join(ALLOWED_ACTIONS)}.
- You must consider recovery probability, failure reason, retry count,
  customer history, and transaction amount together - not any single
  factor in isolation.
- When you are uncertain, or the signals conflict, prefer WAIT, STOP, or
  HUMAN_REVIEW over RETRY or SUGGEST_ALTERNATIVE_PAYMENT.
- Never invent transaction information that was not provided to you.
- Never claim an action was executed - you only request it.
- Never claim money was recovered.
- Never state that a payment succeeded unless you are told execution
  results later confirm it - you have no visibility into execution.

OUTPUT FORMAT:
Respond with a single JSON object and nothing else - no prose before or
after it. The object must have exactly these fields:
{{
  "requested_action": one of {ALLOWED_ACTIONS},
  "confidence": a number between 0 and 1,
  "explanation": a short, specific, human-readable reason for this
    recommendation, referencing the actual data you were given,
  "reason_codes": a short list of stable, machine-readable tags
    summarizing why (e.g. "HIGH_RECOVERY_PROBABILITY", "FIRST_RETRY",
    "TEMPORARY_FAILURE", "RISK_FLAGGED", "RETRY_LIMIT_LIKELY_EXCEEDED")
}}
"""


def build_user_prompt(context: dict) -> str:
    """Builds the per-request user message from the payment context. Only
    the fields relevant to a recovery decision are included - nothing
    beyond what the agent needs to reason about this one transaction."""
    payload = {
        "transaction_id": context.get("transaction_id"),
        "amount": context.get("amount"),
        "payment_method": context.get("payment_method"),
        "failure_reason": context.get("failure_reason"),
        "retry_count": context.get("retry_count"),
        "previous_transactions": context.get("previous_transactions"),
        "previous_success_rate": context.get("previous_success_rate"),
        "subscription_status": context.get("subscription_status"),
        "customer_type": context.get("customer_type"),
        "days_since_failure": context.get("days_since_failure"),
        "time_since_last_success": context.get("time_since_last_success"),
        "device_risk_score": context.get("device_risk_score"),
        "historical_failure_count": context.get("historical_failure_count"),
        "recovery_probability": context.get("recovery_probability"),
    }
    return (
        "Recommend a recovery action for this failed payment. "
        "recovery_probability was computed by the trained ML model, not by you - "
        "treat it as a given input.\n\n"
        f"{json.dumps(payload, indent=2)}"
    )
