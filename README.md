# RecoverAI — Autonomous Revenue Recovery Agent

**Razorpay Buildathon 2026 · Track 03: AI Revenue Recovery**

> **Status: Phase 7 — Razorpay Test Mode Integration.**
> Phases 1–6 (foundation, synthetic data + ML, rules engine, AI agent,
> bounded execution, merchant dashboard) are complete. Phase 7 adds a real
> Razorpay Test Mode adapter (`RazorpayTestExecutor`) behind the same
> `RecoveryExecutor` interface Phase 5 established — RETRY now optionally
> creates a real Razorpay Test Mode Payment Link instead of a pure
> in-process simulation, gated by the exact same Phase 3 safety rules.
> **This project uses Razorpay Test Mode only. No real money is
> processed.** Authentication and production deployment are still not
> implemented.

---

## Why RecoverAI is Different

Most automated payment-recovery tools do one of two things: blindly
retry every failed payment (wasting attempts on unrecoverable ones), or
hand everything to an LLM and hope for the best. RecoverAI does neither:

- **AI recommends. Deterministic rules decide.** The LLM (or the
  deterministic mock provider) never authorizes a money-related action —
  it only *requests* one. A separate, dependency-free rules engine
  (Phase 3) is the only component that can produce `ALLOW` / `BLOCK` /
  `HUMAN_APPROVAL`, and it's fully unit-tested in isolation, independent
  of any AI behavior.
- **Every number is measured, not claimed.** Recovered revenue is
  computed only from confirmed successful executions — never from a
  Payment Link being created, an AI's confidence score, or a model's
  training-set accuracy. The three are kept structurally distinct
  throughout the codebase.
- **Bounded, auditable execution.** A hard retry ceiling, a probability
  floor, a high-value approval threshold, and a hard-stop list for
  suspected-fraud failure reasons all gate every automated action, with
  a full audit trail explaining *why* each decision was made — not just
  *what* happened.
- **Honest about its own limitations.** The ML metrics reported below
  are real, moderate, and reproducible — not tuned to look impressive.
  The Razorpay integration is clearly labeled as mocked-and-tested, not
  live-verified, because this development environment has no network
  access to Razorpay's API.

## Demo Flow

1. **Select a failed payment** from the Failed Payments list (or use one
   of the four seeded canonical demo transactions).
2. **Show the recovery probability** — computed by the Phase 2 XGBoost
   model, visible on Transaction Detail.
3. **Show the AI recommendation** — action, confidence, and explanation,
   clearly labeled "AI Recommendation — Advisory only."
4. **Show the safety decision** — `ALLOW` / `BLOCK` / `HUMAN_APPROVAL`
   with reason codes, clearly labeled "Final Safety Decision —
   Authoritative," visually separated from the AI's request.
5. **Show execution** — Simulation or real Razorpay Test Mode Payment
   Link, both explicitly labeled; execution only ever runs on `ALLOW`.
6. **Show recovered revenue** — updates on the dashboard only after a
   confirmed successful outcome, never at Payment Link creation.
7. **Show the audit trail** — the full chronological event history for
   that transaction, from recommendation through execution.

## Key Innovation

**AI recommends. Deterministic rules decide. Execution is bounded and
auditable.**

---



```
recoverai/
├── backend/
│   ├── app/
│   │   ├── ml/                    # Phase 2: dataset gen, features, preprocessing, train, evaluate, predict
│   │   │   └── artifacts/         # saved model (recovery_model.joblib)
│   │   ├── rules/                 # Phase 3: enums, models, policies, engine
│   │   ├── agent/                 # Phase 4: prompts, providers, schemas, service
│   │   ├── execution/             # Phase 5: enums, models, executor, service, revenue; Phase 7: factory.py
│   │   ├── integrations/razorpay/ # Phase 7: client, executor, webhook_security
│   │   ├── api/                   # Phase 6: payments, recovery, audit, dashboard routes + schemas; Phase 7: razorpay_webhook
│   │   └── db/                    # Phase 1 models; Phase 6 adds repository.py
│   ├── scripts/
│   │   ├── init_db.py             # Phase 1
│   │   ├── generate_dataset.py    # Phase 2
│   │   ├── demo_fixtures.py       # Phase 5: DEMO-A..D
│   │   └── seed_demo_data.py      # Phase 6: seeds DB for the dashboard
│   └── tests/
│       ├── test_health.py         # Phase 1
│       ├── test_ml.py             # Phase 2
│       ├── test_rules_engine.py   # Phase 3
│       ├── test_agent.py          # Phase 4
│       ├── test_execution.py      # Phase 5
│       ├── test_api.py            # Phase 6
│       └── test_razorpay.py       # Phase 7
├── frontend/
│   ├── src/
│   │   ├── pages/                 # Dashboard, FailedPayments, TransactionDetail, AuditTrail, Analytics
│   │   ├── components/            # AppShell, StatusBadge, KpiCard, AgentVsRules, AuditTimeline, States
│   │   ├── api/client.ts          # typed API functions - the only place fetch() is called
│   │   └── types/api.ts           # TypeScript types mirroring backend response models
│   ├── package.json
│   └── vite.config.ts
├── data/
│   ├── raw/       synthetic_payments.csv (generated)
│   ├── processed/ train.csv / test.csv (generated)
│   ├── models/    reserved - primary artifact lives under backend/app/ml/artifacts/
│   └── reports/   evaluation_report.json, threshold_analysis.csv, feature_importance.csv (generated)
├── docs/          Architecture and design docs
├── .env.example   Env var template (backend)
└── .gitignore
```

---

## Prerequisites

- Python 3.11+
- Node.js 20+
- A PostgreSQL database (local Postgres or a free Supabase project)

---

## Windows Quick Start (PowerShell)

A complete, copy-pasteable path for a Windows machine with nothing set
up yet. Every command below is PowerShell — open it via Start Menu →
"PowerShell" (not Command Prompt).

**1. Install prerequisites**
- Python 3.11+: https://www.python.org/downloads/ — check "Add python.exe to PATH" during install.
- Node.js 20+: https://nodejs.org/ (LTS installer).
- PostgreSQL: https://www.postgresql.org/download/windows/ — run the installer, set a password for the `postgres` user when prompted (remember it), keep the default port `5432`. The installer includes **pgAdmin** and the `psql` command-line tool.

**2. Create the database**

Open **pgAdmin** (installed with PostgreSQL) → connect to your local
server with the password you set → right-click "Databases" → "Create" →
"Database..." → name it `recoverai`.

Or via `psql` in PowerShell (it will prompt for the password you set):
```powershell
psql -U postgres -c "CREATE DATABASE recoverai;"
```

**3. Clone and configure**
```powershell
cd C:\Users\<you>\Projects
git clone <your-repo-url> recoverai
cd recoverai
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env
```
Edit `.env` in Notepad and set:
```
DATABASE_URL=postgresql+psycopg2://postgres:<your-password>@localhost:5432/recoverai
```

**4. Backend setup**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.init_db
python -m scripts.seed_demo_data
uvicorn app.main:app --reload --port 8000
```
Leave this PowerShell window open — the API is now running at
`http://localhost:8000`. Visit `http://localhost:8000/docs` for the
interactive API documentation (auto-generated by FastAPI/OpenAPI).

**5. Frontend setup** (open a **second** PowerShell window)
```powershell
cd C:\Users\<you>\Projects\recoverai\frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

**6. Simulation Mode vs. Razorpay Test Mode**

By default (`RECOVERY_EXECUTOR=simulation` in `.env`), every "Trigger
Recovery" click runs entirely in-process — no external API calls, fully
deterministic, no Razorpay account needed. This is what the demo
scenarios below use. Setting `RECOVERY_EXECUTOR=razorpay_test` plus real
`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` (Test Mode keys only, from your
Razorpay dashboard) switches `RETRY` actions to create real Razorpay
Test Mode Payment Links instead — see
[`docs/razorpay-test-mode.md`](docs/razorpay-test-mode.md).

**7. Demo scenarios**

See [`docs/DEMO_SCENARIOS.md`](docs/DEMO_SCENARIOS.md) for the 6 hero
transactions with their exact expected outcomes, and [Demo Flow](#demo-flow)
above for the presentation script.

**8. Troubleshooting**

| Problem | Fix |
|---|---|
| `psql` not recognized | Add `C:\Program Files\PostgreSQL\<version>\bin` to your PATH, or use pgAdmin instead |
| `password authentication failed` | Check the password in `DATABASE_URL` matches what you set during PostgreSQL install |
| Backend starts but dashboard shows all zeros | Run `python -m scripts.seed_demo_data` (Step 4) — an empty database is valid, just has nothing to show yet |
| Frontend shows "Backend unreachable" | Confirm the backend PowerShell window (Step 4) is still running and shows `Uvicorn running on http://0.0.0.0:8000` |
| `pip install` fails on a package | Upgrade pip first: `python -m pip install --upgrade pip`, then retry |
| Port 8000 or 5173 already in use | Another process is using it — close it, or run with a different port (`--port 8001`, and update `frontend/.env`'s `VITE_API_URL` to match) |

---

## 1. Environment Configuration

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Edit `.env` and set `DATABASE_URL` to your Postgres instance. Leave
`LLM_API_KEY`, `RAZORPAY_KEY_ID`, and `RAZORPAY_KEY_SECRET` blank — they
aren't used until later phases.

**Never commit `.env` or `frontend/.env`.** Only the `.env.example` files are tracked.

---

## 2. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create the database tables:

```bash
python -m scripts.init_db
```

Seed demo data for the dashboard (optional, but needed to see the demo
scenarios — see [`docs/DEMO_SCENARIOS.md`](docs/DEMO_SCENARIOS.md) for
the full list with verified expected outcomes):

```bash
python -m scripts.seed_demo_data
```

Seeds 27 payments (idempotent — safe to re-run). Add `--n-sample N` for
extra generic volume from the Phase 2 synthetic dataset.

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Verify it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"RecoverAI API"}
```

Run tests:

```bash
pytest tests/ -v
```

---

## 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. You should see the RecoverAI merchant
dashboard — Dashboard, Failed Payments, Audit Trail, and Analytics in the
sidebar, populated from whatever is currently in the database (empty
until you run `seed_demo_data`, above).

Build for production:

```bash
npm run build
```

---

## 4. ML Pipeline (Phase 2)

All commands below run from the `backend/` directory with the virtualenv
active (see Backend Setup above; `xgboost`, `scikit-learn`, `pandas` etc.
are already in `requirements.txt`).

**Step 1 — Generate the synthetic dataset** (≥1,000 records; default 3,000):

```bash
python -m scripts.generate_dataset --n-records 3000 --seed 42
```

Writes `data/raw/synthetic_payments.csv` and prints a data-quality report
(missing values, duplicate IDs, invalid ranges, class balance). The script
raises an error and refuses to write the file if validation fails.

**Step 2 — Train the model:**

```bash
python -m app.ml.train
```

Splits the data 80/20 (stratified, seed 42), saves the split to
`data/processed/train.csv` / `test.csv`, fits an XGBoost pipeline, and
saves it to `backend/app/ml/artifacts/recovery_model.joblib`.

**Step 3 — Evaluate on the held-out test set:**

```bash
python -m app.ml.evaluate
```

Reloads the saved model and test split independently of training, and
prints/saves: accuracy, precision, recall, F1, ROC-AUC, confusion matrix,
a 7-point threshold analysis (0.20–0.80), business revenue metrics, and
top feature importances. Full report written to
`data/reports/evaluation_report.json`.

**Run the ML test suite:**

```bash
pytest tests/test_ml.py -v
```

Tests are self-contained — they generate small synthetic samples and train
throwaway pipelines in-memory/tempdir, so they don't depend on the real
3,000-row dataset or a pre-existing artifact on disk.

**Use the prediction function directly** (this is what the AI agent will
call in Phase 4 — not wired into an API route yet):

```python
from app.ml.predict import predict_recovery

predict_recovery({
    "amount": 4999.0,
    "retry_count": 0,
    "previous_transactions": 20,
    "previous_success_rate": 0.91,
    "payment_method": "upi",
    "failure_reason": "network_timeout",
    "customer_type": "returning",
})
# {"recovery_probability": 0.60, "predicted_recovered": True}
```

---

## 5. Rules Engine (Phase 3)

The rules engine is the deterministic gate every recovery action must
pass through — see [`docs/rules-engine.md`](docs/rules-engine.md) for the
full design rationale, evaluation order, and reason-code reference.

```python
from app.rules.engine import evaluate_recovery_action

result = evaluate_recovery_action({
    "transaction_id": "TXN1001",
    "amount": 4999.0,
    "recovery_probability": 0.84,
    "retry_count": 0,
    "requested_action": "RETRY",
    "failure_reason": "network_timeout",
})
# result.decision -> "ALLOW" | "BLOCK" | "HUMAN_APPROVAL"
# result.reason_codes, result.explanation, result.requires_human_approval
```

Run the rules-engine test suite:

```bash
pytest tests/test_rules_engine.py -v
```

Default policy (all configurable via `.env` — see `.env.example`):

| Policy | Default |
|---|---|
| Max automated retries | 2 |
| Minimum recovery probability | 0.30 |
| High-value threshold | ₹50,000 |
| Hard-stop failure reasons | `risk_flagged` |

---

## 6. AI Recovery Agent (Phase 4)

Provider-agnostic recommendation layer — see
[`docs/ai-agent.md`](docs/ai-agent.md) for the full design, prompt
constraints, and fail-safe behavior.

```python
from app.agent.service import get_recommendation_and_decision
from app.agent.providers import MockProvider  # or get_default_provider()

result = get_recommendation_and_decision({
    "transaction_id": "TXN1001",
    "amount": 4999.0,
    "failure_reason": "network_timeout",
    "retry_count": 0,
    "recovery_probability": 0.84,
}, MockProvider())

# result.agent.requested_action  -> the AI's advisory request
# result.safety.decision         -> the authoritative ALLOW/BLOCK/HUMAN_APPROVAL
# result.final_decision          -> always == result.safety.decision
```

`LLM_PROVIDER=mock` by default, so this works with zero API keys
configured. Set `LLM_PROVIDER=anthropic` and `LLM_API_KEY` to use a real
model.

```bash
pytest tests/test_agent.py -v
```

---

## 7. Bounded Recovery Execution (Phase 5)

Full end-to-end pipeline, TEST MODE / SIMULATION only — see
[`docs/recovery-execution.md`](docs/recovery-execution.md) for the
complete design.

```python
from app.execution.service import recover_transaction
from app.agent.providers import MockProvider
from app.execution.enums import ForcedOutcome

result = recover_transaction(
    {
        "transaction_id": "TXN1001",
        "amount": 4999.0,
        "failure_reason": "network_timeout",
        "retry_count": 0,
        "recovery_probability": 0.84,
    },
    provider=MockProvider(),
    forced_outcome=ForcedOutcome.SUCCESS.value,  # deterministic - see docs
)

# result.recovery_attempt.execution_status  -> SUCCESS / FAILED / BLOCKED / PENDING_HUMAN_APPROVAL / ...
# result.recovery_attempt.recovered_amount  -> only > 0 when execution_status == SUCCESS
# result.audit_events                       -> full trail for this transaction
```

Run the four deterministic demo fixtures (DEMO-A..D):

```bash
python -c "
from scripts.demo_fixtures import run_demo_a, run_demo_b, run_demo_c, run_demo_d
for demo in [run_demo_a, run_demo_b, run_demo_c, run_demo_d]:
    r = demo()
    print(r.recovery_attempt.transaction_id, r.safety.decision, r.recovery_attempt.execution_status, r.recovery_attempt.recovered_amount)
"
```

Run the execution test suite:

```bash
pytest tests/test_execution.py -v
```

---

## 8. Merchant Dashboard (Phase 6)

Full REST API + React dashboard — see
[`docs/dashboard.md`](docs/dashboard.md) for the complete architecture,
API reference, and revenue metric definitions.

**Seed demo data** (creates DB tables if needed, then seeds 27 curated
demo transactions — see [`docs/DEMO_SCENARIOS.md`](docs/DEMO_SCENARIOS.md)):

```bash
cd backend
python -m scripts.seed_demo_data
```

**Run the backend and frontend** (see setup sections above), then open
`http://localhost:5173` — you'll land on the Dashboard showing live KPIs,
with Failed Payments, Audit Trail, and Analytics in the sidebar. Click
into any transaction for the full AI-vs-rules breakdown and audit
timeline; click "Trigger recovery" on any unprocessed payment to run the
live pipeline through the browser.

Run the API test suite:

```bash
pytest tests/test_api.py -v
```

---

## 9. Deployment (Render backend + Vercel frontend)

**Not deployed from this development environment** — no network access
to Render or Vercel here. `render.yaml` (repo root) and the steps below
are ready to use but have not been executed or live-verified.

**Backend (Render):**
1. Push this repo to GitHub.
2. In the Render dashboard: "New +" → "Blueprint" → select the repo. It
   reads `render.yaml` automatically (web service + free Postgres).
3. After the Postgres instance provisions, run once from a shell with
   `DATABASE_URL` pointed at it: `python -m scripts.init_db` then
   `python -m scripts.seed_demo_data`.
4. Note the deployed URL (e.g. `https://recoverai-api.onrender.com`).

**Frontend (Vercel):**
1. Import the repo in Vercel, set the project root to `frontend/`.
2. Build command `npm run build`, output directory `dist`.
3. Set the environment variable **`VITE_API_URL`** (or `VITE_API_BASE_URL`
   — the client reads either) to the Render URL from above, for the
   Production environment. `frontend/vercel.json` adds the SPA rewrite
   rule react-router-dom's client-side routes need on refresh/deep-link.
4. **Never leave this pointed at `localhost:8000` in production** — the
   client falls back to that only when neither env var is set, which
   should not happen once configured.

---

## 10. Razorpay Test Mode Integration (Phase 7)

**This project uses Razorpay Test Mode. No real money is processed.**
See [`docs/razorpay-test-mode.md`](docs/razorpay-test-mode.md) for the
full architecture, API reference, and security notes.

> Razorpay Test Mode integration implemented and locally verified with
> mocked API behavior. Live external verification is pending because the
> development sandbox has no access to `api.razorpay.com`.

```bash
# .env — switch from the default in-process simulation to real
# Razorpay Test Mode Payment Links:
RECOVERY_EXECUTOR=razorpay_test
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...          # for payment confirmation
```

`RECOVERY_EXECUTOR=simulation` (the default) is unchanged from Phase 5
— zero network calls, zero behavioral difference. With
`RECOVERY_EXECUTOR=razorpay_test` and credentials configured, a `RETRY`
action creates a real Razorpay Test Mode Payment Link instead of a
simulated outcome — gated by the exact same Phase 3 rules engine, from
the exact same single call site Phase 5 established. If credentials are
missing, the API fails closed with `503` (or falls back to simulation if
`RAZORPAY_FALLBACK_TO_SIMULATION=true` is explicitly set) — it never
silently does something unexpected.

Run the Razorpay integration test suite (fully mocked, zero real API calls):

```bash
pytest tests/test_razorpay.py -v
```

---

## What's Implemented in Phase 1

- [x] Repository and folder structure
- [x] FastAPI backend scaffold with modular `api/ core/ db/ ml/ agent/ rules/ execution/ audit/` packages (the latter five are empty placeholders until their respective phases)
- [x] React + TypeScript + Vite + Tailwind frontend scaffold
- [x] Environment-variable-based configuration (no hard-coded secrets)
- [x] PostgreSQL database models: `payments`, `customer_history`, `recovery_attempts`, `audit_log`, `policies`
- [x] `GET /health` API
- [x] Frontend → backend connectivity check
- [x] Git configuration (`.gitignore`, `.env.example`)

## What's Implemented in Phase 2

- [x] Synthetic dataset generator with a hidden, noisy, probabilistic recovery mechanism (no label leakage)
- [x] Data-quality validation (missing values, duplicate IDs, invalid ranges, class balance) with a printed report
- [x] Stratified 80/20 train/test split, reproducible (seed 42)
- [x] Reusable scikit-learn preprocessing (`ColumnTransformer`: scaling + one-hot encoding)
- [x] XGBoost classifier producing `predict_proba()`
- [x] Real test-set metrics: accuracy, precision, recall, F1, ROC-AUC, confusion matrix
- [x] Threshold analysis across 7 thresholds (0.20–0.80) with precision/recall/F1/revenue-selected per threshold
- [x] Business metrics with actual-vs-predicted revenue clearly distinguished
- [x] Feature importance analysis
- [x] Saved, loadable model artifact (`recovery_model.joblib`)
- [x] Reusable `predict_recovery()` function with a fixed output schema
- [x] 13 automated tests (6 data, 4 model, 1 schema/defaults, 1 evaluation), no external dependencies

## What's Implemented in Phase 3

- [x] Strict `RecoveryAction` enum (6 actions) — no arbitrary action strings accepted
- [x] Strict `Decision` enum (`ALLOW` / `BLOCK` / `HUMAN_APPROVAL`) — produced only by the engine, never by a caller
- [x] Typed, strictly-validated input model (`RecoveryActionRequest`) with fail-closed behavior on any invalid field
- [x] Configurable policy values (retry limit, probability floor, high-value threshold, hard-stop failure reasons) — all environment-driven, no magic numbers
- [x] Documented, deterministic 8-step evaluation order
- [x] Deterministic precedence when multiple conditions trigger simultaneously (`BLOCK` > `HUMAN_APPROVAL` > `ALLOW`)
- [x] Stable, machine-readable reason codes
- [x] Deterministic, non-LLM-generated explanations for every decision
- [x] Fail-closed on invalid input, unsupported actions, and unexpected internal errors — engine never raises and never defaults to `ALLOW`
- [x] Output shape ready for direct `audit_log` persistence
- [x] 40 automated tests covering all 16 required scenarios plus boundary/edge cases

## What's Implemented in Phase 4

- [x] Provider-agnostic `LLMProvider` interface, selected via `LLM_PROVIDER` config
- [x] `MockProvider` — deterministic heuristic, clearly labeled, zero external dependencies
- [x] `AnthropicProvider` — real-model implementation (untested live in CI; no API key in this environment)
- [x] Strict `AgentRecommendation` schema reusing Phase 3's `RecoveryAction` enum (one action vocabulary, not two)
- [x] Fail-safe fallback to `HUMAN_REVIEW` (confidence 0.0) on any provider error, timeout, malformed output, or invalid action/confidence — never raises, never guesses
- [x] `get_recommendation_and_decision()` — the combined workflow: agent recommends, Phase 3 rules engine decides, `final_decision` sourced only from the rules engine
- [x] Reuses Phase 2's `predict_recovery()` for probability — no duplicated ML logic
- [x] Audit-ready `to_audit_dict()` output
- [x] 25 automated tests covering all 20 required scenarios plus extras — no test depends on a real external LLM API

## What's Implemented in Phase 5

- [x] `RecoveryExecutor` — simulation/test-mode-only adapter for the six approved actions, zero imports from `app.rules` (cannot duplicate/diverge from Phase 3 policy)
- [x] Deterministic, reproducible simulation outcomes (`forced_outcome` / `transaction["simulation_outcome"]` — never random)
- [x] `recover_transaction()` orchestrator — the one call site where execution is triggered, and only on `ALLOW`
- [x] Explicit `ExecutionStatus` states: `NOT_EXECUTED`, `BLOCKED`, `PENDING_HUMAN_APPROVAL`, `SUCCESS`, `FAILED`, `COMPLETED`
- [x] `recovery_attempts` schema extended additively (execution_status, recovered_amount, simulation_mode, completed_at) — no existing columns touched
- [x] Full audit trail per transaction (`RECOVERY_RECOMMENDED` + outcome-specific event)
- [x] Process-local idempotency — duplicate calls for the same transaction never re-execute
- [x] Fail-closed on missing transaction, broken executor, or broken provider — never raises, never returns `SUCCESS` on error
- [x] Batch revenue accounting (`amount_at_risk`, `potentially_recoverable_amount`, `recovered_amount`) computed from real attempts only
- [x] Four deterministic demo fixtures (DEMO-A..D)
- [x] 35 automated tests covering all 21 required scenarios plus extras

## What's Implemented in Phase 6

- [x] Full REST API: `/api/dashboard/summary`, `/api/payments`, `/api/payments/{id}`, `POST/GET /api/recovery/{id}`, `/api/audit`, `/api/audit/{id}`, `/api/analytics` — documented via FastAPI's OpenAPI schema
- [x] Database persistence: `RecoveryAttempt` and `AuditLog` rows written for every recovery workflow run, via a single repository module (`app/db/repository.py`)
- [x] Additive-only schema changes across `Payment`, `RecoveryAttempt`, `AuditLog` — no Phase 1/3/5 columns touched
- [x] DB-backed idempotency — re-triggering recovery for the same transaction returns the persisted result, never re-executes
- [x] React dashboard: Dashboard, Failed Payments (search/filter/sort), Transaction Detail, Audit Trail, Analytics (Recharts)
- [x] Clear visual separation of **AI Recommendation** (advisory) vs **Final Safety Decision** (authoritative) vs **Execution Status** on every transaction
- [x] SIMULATION / TEST MODE shown throughout — sidebar, banners, every executed audit event
- [x] Typed API client (`api/client.ts`) — no raw `fetch()` calls in any page component
- [x] Loading / error / empty states on every page
- [x] Demo seed script producing all four canonical outcomes (SUCCESS, FAILED, BLOCKED, PENDING_HUMAN_APPROVAL) plus interactive sample payments
- [x] 21 new API tests (134 total) — including a test proving the frontend cannot spoof `recovered_amount`/`rules_decision`/`execution_status`, and a test asserting the API layer contains zero rules-engine logic

## What's Implemented in Phase 7

- [x] `RazorpayTestExecutor` — real Razorpay Test Mode Payment Link creation, behind the same `RecoveryExecutor` interface as `SimulationExecutor`
- [x] `RazorpayClient` — typed wrapper around two documented endpoints (`POST/GET /v1/payment_links`), HTTP Basic Auth, no secret logging, proper timeout/error handling
- [x] Executor factory (`RECOVERY_EXECUTOR=simulation|razorpay_test`) — fails closed by default if credentials are missing, explicit opt-in fallback only
- [x] `RAZORPAY_MODE` startup validation — refuses to start if set to anything but `test`
- [x] Payment Link creation correctly recorded as `COMPLETED`, never `SUCCESS` — `recovered_amount` stays `0.0` until confirmed
- [x] Webhook receiver with documented HMAC-SHA256 signature verification, idempotent processing (no double-counting on redelivery)
- [x] Distinct `RAZORPAY_PAYMENT_LINK_CREATED` / `RAZORPAY_PAYMENT_CONFIRMED` / `RAZORPAY_PAYMENT_FAILED` audit events
- [x] Safety boundary proven with call-spy tests: `BLOCK`/`HUMAN_APPROVAL` never reach the Razorpay client
- [x] DB-backed idempotency extended to the Razorpay path — never creates a duplicate Payment Link for the same transaction
- [x] Frontend: `ExecutionModeBadge` distinguishes "Simulation / Test Mode" from "Razorpay Test Mode"; Payment Link reference/URL shown with an explicit "does not mean recovered" caveat until confirmed
- [x] 37 automated tests (all mocked, zero real Razorpay API calls) covering all 21 required scenarios plus 2 audit-event regression guards

## What's Explicitly Not in Phase 1-7

- Live Razorpay Test Mode verification (no network access to `api.razorpay.com` in this environment — see `docs/razorpay-test-mode.md`)
- Payment-link status polling endpoint (client method exists; webhook is the implemented confirmation path)
- Authentication
- Production deployment / infrastructure
- Multi-merchant architecture
- Email/SMS/WhatsApp notifications

---

## Actual Test-Set Results (this run, seed 42, 3,000 records)

**This section is Phase 2 ML model evaluation on a synthetic, held-out
test set — it is not a recovered-revenue figure.** The dashboard's live
revenue numbers (Section 8 — Merchant Dashboard) are computed
separately, from actual persisted recovery attempts, and use none of
these values.

These are the real numbers produced by the commands above — not
hand-picked or fabricated. Re-running `generate_dataset` → `train` →
`evaluate` with the same seed reproduces them exactly.

| Metric | Value |
|---|---|
| Test records | 600 (2,400 train) |
| Class balance (test) | 223 recovered / 377 not recovered (37.2% positive) |
| Accuracy | 0.670 |
| Precision | 0.566 |
| Recall | 0.480 |
| F1 | 0.519 |
| ROC-AUC | 0.705 |

Confusion matrix (test set): TN 295, FP 82, FN 116, TP 107.

These are honest, moderate numbers for a genuinely noisy problem — not an
artificially easy dataset. ROC-AUC of ~0.70 indicates real, learnable
signal without being suspiciously perfect. See `data/reports/evaluation_report.json`
for the full breakdown including all 7 thresholds and business metrics.

---

## Database Schema (Phase 1)

| Table | Purpose |
|---|---|
| `payments` | Failed payment records |
| `customer_history` | Per-customer recovery-relevant history |
| `recovery_attempts` | One row per recovery decision/execution (populated starting Phase 3+) |
| `audit_log` | Append-only event trail (populated starting Phase 3+) |
| `policies` | Configurable safety-rule thresholds (populated starting Phase 4) |

Tables are created via `python -m scripts.init_db`, which calls
`Base.metadata.create_all()` against the models in `app/db/models.py`. This
is a lightweight bootstrap for Phase 1; versioned migrations (e.g. Alembic)
can be introduced later if the schema needs to evolve without a full
rebuild.

---

## Next Recommended Phase

**Phase 8 — Live Razorpay Test Mode Verification + Payment Status Polling**:
this environment had no network access to `api.razorpay.com`, so
Phase 7's Razorpay integration is fully implemented and tested with mocks
but has never made a real Test Mode API call. Phase 8 should: (1) run
the existing mocked test suite unchanged in an environment with real
network access, (2) perform one controlled live Test Mode Payment Link
creation and confirm the full webhook round-trip against Razorpay's
actual current API/webhook behavior (re-verifying the event names and
signature scheme documented with a stated caveat in
`docs/razorpay-test-mode.md`), and (3) wire `RazorpayClient.fetch_payment_link()`
(already implemented, not yet exposed) to an on-demand
`GET /api/recovery/{id}/razorpay-status` endpoint as a polling
alternative to the webhook.
