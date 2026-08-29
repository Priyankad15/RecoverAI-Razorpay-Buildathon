# Bounded Recovery Execution

**Phase 5.** Location: `backend/app/execution/` (`enums.py`, `models.py`,
`executor.py`, `service.py`, `revenue.py`), demo fixtures in
`backend/scripts/demo_fixtures.py`.

## 1. Execution architecture

```
Payment -> ML prediction -> AI recommendation -> Rules Engine
                                                        |
                                        ALLOW / BLOCK / HUMAN_APPROVAL
                                                        |
                                    only ALLOW reaches RecoveryExecutor
                                                        |
                                              SUCCESS / FAILED / COMPLETED
                                                        |
                                    RecoveryAttemptRecord + AuditEvent(s)
```

`app.execution.service.recover_transaction()` is the single orchestrator
tying Phases 1–5 together. It calls Phase 4's
`get_recommendation_and_decision()` (which itself calls Phase 3's rules
engine), then branches on `final_decision`. `RecoveryExecutor.execute()`
is called from **exactly one place** in the codebase — the `ALLOW`
branch of that function — and nowhere else.

## 2. ALLOW / BLOCK / HUMAN_APPROVAL behavior

| `final_decision` | Executor called? | `execution_status` |
|---|---|---|
| `ALLOW` | Yes | `SUCCESS`, `FAILED`, or `COMPLETED` (outcome of the actual simulated action) |
| `BLOCK` | **Never** | `BLOCKED` |
| `HUMAN_APPROVAL` | **Never** (automatically) | `PENDING_HUMAN_APPROVAL` |
| anything else / error | **Never** | `NOT_EXECUTED` |

This isn't just a convention — `test_block_prevents_execution` and
`test_human_approval_prevents_automatic_execution` use a spy executor
that records whether it was ever called, and assert it was not.

## 3. Simulation adapter

`RecoveryExecutor` is TEST MODE / SIMULATION only. No real Razorpay call
is ever made; every result's `detail` field is explicitly prefixed
`[SIMULATION / TEST MODE]`. Only `RETRY` has a genuine monetary
SUCCESS/FAILURE outcome — it's the only action that represents an actual
attempt to move money. `SEND_REMINDER` and `SUGGEST_ALTERNATIVE_PAYMENT`
simulate as `COMPLETED` (outreach performed, no money moved by the
outreach itself). `STOP`, `WAIT`, `HUMAN_REVIEW` simulate as `COMPLETED`
trivially (nothing to run).

**How the outcome is chosen (deterministic, not random)** — mirrors how
Razorpay's own Test Mode works (specific test card numbers deterministically
produce specific results):

1. `forced_outcome` argument to `execute()` / `recover_transaction()`, if given, wins.
2. Otherwise `transaction["simulation_outcome"]`, if the caller set it.
3. Otherwise defaults to `SUCCESS`.

## 4. Success flow

`ALLOW` → `RecoveryExecutor.execute("RETRY", ...)` → outcome `SUCCESS` →
`recovered_amount = transaction amount` → `RecoveryAttemptRecord` with
`execution_status="SUCCESS"` → audit event `RECOVERY_EXECUTED`. The
system marks a transaction recovered **only** after the executor reports
success — never earlier.

## 5. Failure flow

`ALLOW` → executor outcome `FAILURE` → `recovered_amount = 0.0`,
`failure_reason` preserved → `RecoveryAttemptRecord` with
`execution_status="FAILED"` → audit event `RECOVERY_FAILED`. Nothing
here re-queues an automatic retry — the retry-count check that would
prevent a runaway loop lives entirely in Phase 3's rules engine and is
re-evaluated fresh the next time `recover_transaction()` is called for
that transaction with an incremented `retry_count`.

## 6. Idempotency

`recover_transaction()` accepts an `idempotency_store: dict` (defaults
to a process-local module-level dict if none is passed). The key is
`payment["idempotency_key"]` if the caller supplied one, else the
`transaction_id` itself. If a result already exists under that key, it
is returned as-is (with `idempotent_replay=True` set) — **the executor
is not called again**, even if the second call requests a different
`forced_outcome`.

This is intentionally process-local, not durable across restarts — it
exists to prevent accidental duplicate execution within one running
process/request lifecycle. A future phase backing this with a database
unique constraint (e.g. one row per `transaction_id` + attempt
generation) would make it durable across restarts and multiple
instances; the shape of `RecoveryAttemptRecord` is already designed for
that.

## 7. Revenue accounting

`app.execution.revenue.compute_batch_revenue_metrics()` computes three
figures from actual `RecoveryTransactionResult` objects — never
hard-coded:

- **`amount_at_risk_inr`** — sum of every processed transaction's amount.
- **`potentially_recoverable_amount_inr`** — sum where the rules engine
  did not `BLOCK` outright (`ALLOW` or `HUMAN_APPROVAL`) — still "in
  play", not yet recovered.
- **`recovered_amount_inr`** — sum **only** where `execution_status ==
  SUCCESS`. `BLOCKED`, `FAILED`, and `PENDING_HUMAN_APPROVAL` transactions
  never contribute here, by construction (see
  `test_failed_amount_not_counted_as_recovered` and
  `test_human_approved_amount_not_counted_as_recovered`).

## 8. Audit events

Every call to `recover_transaction()` produces at least two audit
events: `RECOVERY_RECOMMENDED` (always first) plus exactly one of
`RECOVERY_BLOCKED`, `RECOVERY_APPROVAL_REQUIRED`, `RECOVERY_EXECUTED`,
`RECOVERY_FAILED`, or `RECOVERY_COMPLETED` depending on the outcome.
Each event carries `transaction_id`, `requested_action`,
`rules_decision`, `execution_status`, `reason_codes`, `explanation`,
`simulation_mode`, and `timestamp` — ready for direct `audit_log`
persistence in a later phase (not wired to the database yet, same
"shape now, persist later" pattern used by Phase 3/4's decision
objects).

## 9. Safety guarantees

- Execution never happens unless `final_decision == "ALLOW"` — enforced
  structurally (one call site) and by tests using a call-spy executor.
- An execution adapter exception is caught and becomes
  `execution_status="NOT_EXECUTED"` — **never** `SUCCESS`.
- `recover_transaction()` never raises, for any input (missing
  transaction, `None` payload, broken executor, broken provider) — it
  always returns a valid `RecoveryTransactionResult`.
- The executor has zero imports from `app.rules` — it cannot duplicate
  or diverge from Phase 3's policy, because it doesn't contain any
  policy logic to diverge (verified directly by
  `test_executor_never_reevaluates_safety_rules_itself`, which asserts
  the executor's source file contains no rules-engine references).
- Only the six approved `RecoveryAction` values can ever reach
  `RecoveryExecutor.execute()` — anything else raises
  `UnsupportedExecutionAction` before any simulated action runs.

## 10. Demo scenarios

`backend/scripts/demo_fixtures.py` — four deterministic, reproducible
fixtures, MockProvider (or the existing Phase 4 `_AlwaysRetryProvider`
test stub for DEMO-C, reused rather than duplicated):

| Fixture | Amount | Retry count | AI request | Rules | Execution | Recovered |
|---|---|---|---|---|---|---|
| DEMO-A | ₹4,999 | 0 | RETRY | ALLOW | SUCCESS | ₹4,999 |
| DEMO-B | ₹4,999 | 0 | RETRY | ALLOW | FAILURE | ₹0 |
| DEMO-C | ₹4,999 | 2 | RETRY | BLOCK (MAX_RETRIES_REACHED) | not run | ₹0 |
| DEMO-D | ₹68,000 | 0 | RETRY | HUMAN_APPROVAL | not run | ₹0 |

All four are DEMO/TEST/SIMULATION only — no real money, no real
Razorpay calls, at any point.
