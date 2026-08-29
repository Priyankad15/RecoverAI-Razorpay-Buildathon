# Deterministic Safety / Rules Engine

**Phase 3.** Location: `backend/app/rules/` (`enums.py`, `models.py`, `policies.py`, `engine.py`).

## 1. Why this exists

The AI agent (Phase 4) will look at a failed payment and *recommend* an
action. An LLM recommendation is not, by itself, a safe basis for a
money-related action — it can be wrong, inconsistent, or manipulated by
adversarial input. The rules engine is the single deterministic gate that
every requested action must pass through before anything is executed. It
contains no LLM calls, no network calls, and no non-deterministic
behavior: the same input always produces the same output.

## 2. Why the AI cannot bypass it

The AI agent's output (Phase 4) will only ever be a *requested* action — a
string it proposes. It is never treated as a decision. Only
`evaluate_recovery_action()` in `engine.py` is permitted to produce a
`Decision` (`ALLOW` / `BLOCK` / `HUMAN_APPROVAL`), and every future
execution path must call this function and act on *its* output — not on
anything the agent claims about safety (e.g. an LLM-generated
`"safety_status": "PASSED"` is never trusted). Policy thresholds come only
from `app.rules.policies.get_active_policy()`, which reads exclusively
from environment-configured application settings — never from the
frontend, the agent, or any request payload.

## 3. Rule evaluation order

Deterministic and fixed, documented in `engine.py`:

1. **Validate input** — malformed input fails closed (`BLOCK`, reason `INVALID_INPUT`).
2. **Validate requested action** — must be one of the six allowed action strings, or `BLOCK` (`UNSUPPORTED_ACTION`).
3. **Check hard-stop conditions** — e.g. a `RETRY` on a failure reason flagged as fraud (`risk_flagged` by default) is blocked outright, before any other check. Hard stops encode non-negotiable safety facts that shouldn't be softened by a high probability score.
4. **Check retry limit** — applies only to `RETRY` (the only action that re-attempts a charge).
5. **Check recovery probability** — applies only to `RETRY`.
6. **Check transaction amount / human-approval threshold** — applies to any action that engages with the recovery flow (`RETRY`, `SEND_REMINDER`, `SUGGEST_ALTERNATIVE_PAYMENT`).
7. **Resolve final decision by precedence** — `BLOCK` > `HUMAN_APPROVAL` > `ALLOW`. If a transaction has both exhausted its retries *and* is high-value, it's `BLOCK`ed — a blocked action has no need to also be escalated.
8. **Return a structured, explainable decision.**

Passive actions (`WAIT`, `STOP`, `HUMAN_REVIEW`) never touch money or the
customer-facing recovery flow, so once steps 1–2 pass, they are allowed
immediately without steps 3–7 — this is a deliberate design choice: gating
exists to control money-adjacent actions, not to add friction to inert
ones.

## 4. Default policies

All values are read from environment configuration
(`app/core/config.py` / `.env`), never hard-coded inline:

| Setting | Env var | Default |
|---|---|---|
| Max automated retries | `MAX_AUTOMATED_RETRIES` | `2` |
| Minimum recovery probability | `MIN_RECOVERY_PROBABILITY` | `0.30` (inclusive floor) |
| High-value threshold | `HIGH_VALUE_THRESHOLD_INR` | `₹50,000` (inclusive) |
| Hard-stop failure reasons | `HARD_STOP_FAILURE_REASONS` | `risk_flagged` |

A `Policy` snapshot is attached to every decision (`policy_version`), so
the audit trail shows exactly which thresholds were in effect.

## 5. Decision states

Exactly three, produced only by this engine:

- `ALLOW` — action may proceed.
- `BLOCK` — action is not permitted, automated or otherwise, right now.
- `HUMAN_APPROVAL` — action may proceed only after a human approves it.

## 6. Reason codes

Stable, machine-readable strings, safe to key dashboards/alerts off of:

- `INVALID_INPUT`
- `UNSUPPORTED_ACTION`
- `HARD_STOP_FAILURE_REASON`
- `MAX_RETRIES_REACHED`
- `LOW_RECOVERY_PROBABILITY`
- `HIGH_VALUE_TRANSACTION`
- `EVALUATION_ERROR`

Multiple reason codes can appear together (e.g. a transaction that has
both exhausted retries and is high-value carries both
`MAX_RETRIES_REACHED` and `HIGH_VALUE_TRANSACTION`) — the `decision`
field alone tells you the outcome; `reason_codes` gives full audit
transparency into everything that was actually evaluated.

## 7. Fail-closed behavior

- Invalid input → `BLOCK`.
- Unsupported action → `BLOCK`.
- Any unexpected internal error during evaluation → `BLOCK` (reason `EVALUATION_ERROR`) — `evaluate_recovery_action()` wraps all evaluation in a catch-all and never raises, and never defaults to `ALLOW` on uncertainty.

## 8. How future execution will consume the decision

`RuleEngineDecision` (see `models.py`) is already shaped to be written
directly into the `audit_log` table: `transaction_id`, `requested_action`,
`decision`, `reason_codes`, `explanation`, `requires_human_approval`,
`policy_version`, `evaluated_at`. In Phase 5 (execution), the flow will
be: agent requests an action → `evaluate_recovery_action()` is called →
only if `decision == ALLOW` does the execution adapter run; if
`HUMAN_APPROVAL`, the case is queued for a human; if `BLOCK`, nothing
happens and the reason is logged. No other code path is permitted to
authorize a money-related action.
