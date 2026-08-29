# Merchant Dashboard

**Phase 6.** Backend: `backend/app/api/{payments,recovery,audit,dashboard}.py`,
`backend/app/db/repository.py`. Frontend: `frontend/src/pages/`,
`frontend/src/components/`, `frontend/src/api/client.ts`.

## 1. Dashboard architecture

```
React (display + interaction only)
   │  typed fetch calls (frontend/src/api/client.ts)
   ▼
FastAPI routes (backend/app/api/*.py)
   │  read/write via repository functions only
   ▼
app/db/repository.py  (the ONLY module that touches SQLAlchemy models
   │                    for dashboard purposes)
   ▼
Phase 1 database (payments, customer_history, recovery_attempts, audit_log)
```

Business logic never lives in the frontend or in the API route handlers
themselves. A route handler's job is: read a request, call a Phase 2-5
function or a repository read, shape a response model, return it. The
one exception worth naming explicitly: `POST /api/recovery/{id}` calls
`recover_transaction()` (Phase 5) directly - that's the correct, singular
place ML → agent → rules → execution actually runs.

## 2. API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dashboard/summary` | KPI totals for the dashboard |
| GET | `/api/payments` | List payments (search, status filter, sort, pagination) |
| GET | `/api/payments/{transaction_id}` | Full transaction detail + latest attempt + audit trail |
| POST | `/api/recovery/{transaction_id}` | Run the recovery workflow (idempotent) |
| GET | `/api/recovery/{transaction_id}` | Retrieve the persisted recovery result |
| GET | `/api/audit` | Global audit feed |
| GET | `/api/audit/{transaction_id}` | Audit trail for one transaction |
| GET | `/api/analytics` | Status/failure-reason/reason-code breakdowns |

All routes are auto-documented via FastAPI's OpenAPI schema at `/docs`
(interactive) and `/openapi.json`.

**`POST /api/recovery/{transaction_id}` accepts no body.** There is no
field a client can send that influences `recovered_amount`,
`rules_decision`, or `execution_status` - the backend computes all three.
`test_frontend_cannot_supply_recovered_amount_or_decision` in
`tests/test_api.py` posts a spoofed body (`recovered_amount: 999999`) and
asserts it's completely ignored.

## 3. Data flow

```
Payment failed (seeded or real)
  → GET /api/payments shows it as UNPROCESSED
  → merchant clicks "Trigger recovery"
  → POST /api/recovery/{id}
      → load Payment + CustomerHistory from DB
      → predict_recovery() (Phase 2)
      → recover_transaction() (Phase 5: agent → rules → execution)
      → repository.persist_recovery_result() writes RecoveryAttempt + AuditLog rows
      → response returned to the frontend
  → GET /api/payments/{id} now shows the full decision + audit trail
```

## 4. Revenue metric definitions

- **Revenue at Risk** — sum of every persisted payment's amount. Every
  row in the `payments` table is a failed payment by this project's
  dataset design, so `failed_payments == total_payments`.
- **Potentially Recoverable Revenue** — sum of amounts for payments whose
  latest recovery attempt has `rules_decision` in `{ALLOW,
  HUMAN_APPROVAL}` — i.e. the rules engine did not `BLOCK` it outright.
  Payments with no attempt yet aren't counted (their rules decision is
  unknown until the workflow actually runs).
- **Recovered Revenue** — sum of `recovered_amount` **only** where
  `execution_status == SUCCESS`. `BLOCKED`, `FAILED`, and
  `PENDING_HUMAN_APPROVAL` never contribute, by construction (same
  invariant Phase 5 established, now backed by persisted data).
- **Recovery Rate** — `recovered_revenue / potentially_recoverable_revenue`
  (0 if the denominator is 0).

None of these read Phase 2's held-out test-set metrics (ROC-AUC,
precision/recall etc.) - those describe model quality on a fixed sample;
the dashboard describes actual/demo workflow outcomes, computed fresh on
every request from whatever is currently persisted.

## 5. Persistence

`app/db/repository.py` is the single point where `RecoveryTransactionResult`
(Phase 5's output) becomes database rows:

- `upsert_payment_with_customer()` — writes `Payment` + `CustomerHistory`
- `persist_recovery_result()` — writes one `RecoveryAttempt` row and one
  `AuditLog` row per audit event

Schema changes this phase made are purely additive (see `app/db/models.py`
comments): `Payment.simulation_outcome`; `RecoveryAttempt.rules_decision`,
`.failure_reason`; `AuditLog.requested_action`, `.rules_decision`,
`.execution_status`, `.reason_codes`, `.explanation`, `.simulation_mode`.
Nothing from Phases 1, 3, or 5's schema was removed or renamed. Legacy
columns from Phase 1's initial draft (`safety_status`, `execution_decision`,
`result`) are retained but no longer written to — `rules_decision` and
`execution_status` are the columns of record going forward.

**A real bug found and fixed during this phase**: `AuditLog.timestamp`
originally relied on `server_default=func.now()`, which on SQLite has
only 1-second resolution — two events from the same workflow (e.g.
`RECOVERY_RECOMMENDED` then `RECOVERY_BLOCKED`, microseconds apart) could
land in the same DB second and sort unpredictably. Fixed by reusing each
`AuditEvent`'s own precise (microsecond) timestamp — already generated by
Phase 5 — at insert time instead of leaving it to the database.
Verified with `TXN-DEMO-C`'s two events now returning in correct order.

**Verified against SQLite in this environment** (no live Postgres
available in the sandbox) — the same limitation and caveat noted in every
earlier phase's DB verification. Schema is standard SQLAlchemy and should
behave identically against Postgres; worth a real run against Supabase/
Postgres before a live demo.

## 6. Recovery workflow (UI)

The Dashboard page shows the pipeline as a horizontal step strip (Payment
Failed → Revenue Risk Detected → ML Prediction → AI Recommendation →
Safety Decision → Execution/Approval/Block → Result) purely as a static
label of the architecture — actual per-transaction values are shown on
the Transaction Detail page, not fabricated on this strip.

## 7. Audit trail

`AuditTimeline.tsx` renders persisted `AuditLog` rows in chronological
order (oldest first) with event type, requested action, rules decision,
execution status, reason codes, and explanation — nothing here is
generated client-side; every field is a direct read of what the backend
persisted during `recover_transaction()`.

## 8. Simulation mode

Every execution-adjacent surface — the sidebar footer, a banner on
Dashboard/Transaction Detail, and every executed audit event's
explanation text — carries an explicit **SIMULATION / TEST MODE** label,
consistent with Phase 5's `RecoveryExecutor`. No page implies real money
moved.

## 9. Frontend/backend separation

The frontend contains zero copies of: ML feature engineering, the
prompt/provider logic, Phase 3's policy thresholds, or revenue
arithmetic. `frontend/src/api/client.ts` is the only place `fetch` is
called from; every page imports typed functions from it rather than
hitting endpoints directly. Verified structurally by
`test_api_layer_has_no_rules_engine_logic` (backend) — the same
discipline extends to the frontend by construction: there is no code
path in any `.tsx` file that computes a probability, a decision, or a
recovered amount; every number displayed is read directly from an API
response.
