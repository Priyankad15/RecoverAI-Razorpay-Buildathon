# AI Recovery Agent

**Phase 4.** Location: `backend/app/agent/` (`prompts.py`, `providers.py`, `schemas.py`, `service.py`).

## 1. Agent responsibility

Given one failed payment plus its Phase 2 recovery probability, recommend
exactly one recovery action from the approved list. That's the entire
job. It does not decide whether the action is safe to run — that's
Phase 3's job — and it does not run anything — that's Phase 5's job.

## 2. Agent limitations

The agent cannot, under any circumstance:

- authorize or execute a financial action,
- modify Phase 3's policies or thresholds,
- bypass or override a `BLOCK` or `HUMAN_APPROVAL` decision,
- invent an action outside the six approved values,
- claim money was recovered or a payment succeeded.

Its output type (`AgentRecommendation`) has no field that could be
mistaken for a decision — no `approved`, no `executed`, nothing. The only
decision-shaped object in the system is `SafetyDecisionSummary`, produced
exclusively by `app.rules.engine.evaluate_recovery_action()`.

## 3. Provider abstraction

`app.agent.providers.LLMProvider` is the interface. Two implementations
exist:

- `MockProvider` — deterministic, rule-of-thumb heuristic. No network
  call, no randomness. Every explanation it returns is prefixed
  `[MOCK]` and `is_mock` is always `True`.
- `AnthropicProvider` — calls the real Anthropic Messages API
  (`api.anthropic.com`) using `LLM_API_KEY` / `LLM_MODEL` from
  configuration. Not exercised by the automated test suite.

`get_default_provider()` selects between them purely from configuration
(`LLM_PROVIDER` env var) — business logic never imports a vendor SDK
directly, and adding a third provider (e.g. OpenAI) means implementing
`LLMProvider` and adding one branch to the factory, nothing else.

**Fail-safe selection**: if `LLM_PROVIDER=anthropic` but `LLM_API_KEY` is
empty, `get_default_provider()` returns `MockProvider` rather than
raising or returning a broken client — the agent must always have
something usable to call.

## 4. Structured output

`AgentRecommendation` (Pydantic, `extra="forbid"`) requires:

| Field | Constraint |
|---|---|
| `requested_action` | must be one of the six `RecoveryAction` enum values (imported from `app.rules.enums` — no second action vocabulary) |
| `confidence` | `0.0 <= confidence <= 1.0` |
| `explanation` | non-empty |
| `transaction_id` | non-empty |
| `reason_codes` | list of strings |
| `provider`, `is_mock`, `model`, `generated_at` | provenance — always populated |

Any provider output that fails these constraints never reaches the rest
of the system as-is — it triggers the fallback path (below).

## 5. Prompt constraints

The system prompt (`app.agent.prompts.SYSTEM_PROMPT`) explicitly states
the agent is advisory-only, cannot execute or approve anything, must
choose from the fixed action list, should prefer `WAIT`/`STOP`/
`HUMAN_REVIEW` when uncertain, and must never claim an action was
executed or money recovered. It deliberately contains **no copies of
Phase 3's numeric policy thresholds** (max retries, probability floor,
high-value amount) — those live in exactly one place
(`app.core.config` / `.env`) and are evaluated by the rules engine only;
duplicating them into a prompt would risk drift and blur the
"AI recommends, rules decide" boundary.

## 6. Mock provider

Deterministic heuristic (see `providers.py: MockProvider`):

- Terminal-looking failure reasons (`invalid_card`, `risk_flagged`) → `STOP`
- `retry_count >= 2` → `STOP`
- `recovery_probability >= 0.60` → `RETRY`
- `0.30 <= recovery_probability < 0.60` → `SEND_REMINDER`
- `recovery_probability < 0.30` → `HUMAN_REVIEW`

This is a testing/demo convenience, **not a real AI model** — it's
labeled as such everywhere it appears (explanation text, `is_mock=True`,
`provider="mock"`).

## 7. Failure behavior

`get_agent_recommendation()` never raises. On any of: provider
unavailable, timeout, malformed JSON, unsupported action, out-of-range
confidence, or any unexpected exception — it returns a fallback
`AgentRecommendation`:

```
requested_action = "HUMAN_REVIEW"
confidence        = 0.0
is_mock           = True
reason_codes      = ["AGENT_FALLBACK", "<REASON>"]
```

This fallback is still passed through the Phase 3 rules engine like any
other recommendation (`HUMAN_REVIEW` is a passive action, always
`ALLOW`ed) — the failure is fully visible in the output, never hidden.

## 8. AI vs. deterministic rules separation

`get_recommendation_and_decision()` is the one function that combines
both layers, and it keeps them as two separate objects on the result:
`result.agent` (advisory) and `result.safety` (authoritative).
`result.final_decision` is copied from `result.safety.decision` only —
never from `result.agent.requested_action`. "AI recommended RETRY" and
"RETRY is allowed" are different sentences and the code never conflates
them.

## 9. Example decisions

**Agreement** — AI requests RETRY, rules ALLOW it:
```json
{"agent": {"requested_action": "RETRY", "confidence": 0.6, ...},
 "safety": {"decision": "ALLOW", "reason_codes": []},
 "final_decision": "ALLOW"}
```

**Disagreement** — AI requests RETRY, rules BLOCK it (retries exhausted):
```json
{"agent": {"requested_action": "RETRY", "confidence": 0.9, ...},
 "safety": {"decision": "BLOCK", "reason_codes": ["MAX_RETRIES_REACHED"]},
 "final_decision": "BLOCK"}
```
The agent's request remains visible in `result.agent` for audit purposes,
but `final_decision` — the only field anything downstream should act
on — is `BLOCK`.

## 10. Why the agent cannot execute financial actions

There is no code path from `app.agent` to any payment execution. The
agent module has no import of, or reference to, Razorpay, a database
write, or any "execute" function. Its only outputs are immutable
Pydantic data objects. Execution (Phase 5) will only ever consume
`AgentRulesResult.final_decision` — never `AgentRulesResult.agent`
directly — enforcing "AI recommends, rules decide, execution obeys
rules" as a structural property of the codebase, not just a convention.
