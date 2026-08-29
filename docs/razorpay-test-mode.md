# Razorpay Test Mode Integration

**Phase 7.** `backend/app/integrations/razorpay/` (`client.py`,
`executor.py`, `webhook_security.py`), `backend/app/api/razorpay_webhook.py`,
`backend/app/execution/factory.py`.

**This project uses Razorpay Test Mode. No real money is processed.**
`RAZORPAY_MODE` must be `"test"` — the application refuses to start
(`Settings` validation fails) if it's set to anything else.

**Verification status**: Razorpay Test Mode integration implemented and
locally verified with mocked API behavior (37 automated tests, zero real
network calls). Live external verification is pending because the
development sandbox has no access to `api.razorpay.com`.

## 1. Architecture

```
RecoveryExecutor  (interface every executor conforms to:
                    execute(action, transaction, forced_outcome=None) -> ExecutionResult)
       |
       +-- SimulationExecutor    (Phase 5, unchanged - in-process, deterministic, no network)
       +-- RazorpayTestExecutor  (Phase 7 - real Razorpay Test Mode API calls)
```

`app.execution.factory.get_executor()` selects between them via
`RECOVERY_EXECUTOR` (`simulation` default, or `razorpay_test`). The
orchestrator (`app.execution.service.recover_transaction()`) is
completely unaware which one it's calling — it always just calls
`executor.execute(...)` from the exact same single call site established
in Phase 5 (the `ALLOW` branch, and nowhere else).

**Naming note**: Phase 5's `RecoveryExecutor` class was not turned into
an abstract base class — Phase 5/6 code and tests construct it directly
(`RecoveryExecutor()`) and subclass it as spy/broken-executor test
doubles throughout. Making it abstract would have broken all of that for
a naming change alone. Instead, `SimulationExecutor = RecoveryExecutor`
is an explicit alias in `app/execution/executor.py` — both names refer
to the exact same, fully-instantiable class. `RazorpayTestExecutor`
satisfies the same call signature without needing formal inheritance
(Python's structural typing handles this cleanly).

## 2. Why Payment Links, not a Payments API capture call

Razorpay's documentation states that Payments APIs retrieve payment
details and capture an *already-authorized* payment — they are not used
to collect a new payment. A failed payment was never authorized, so
there is nothing to capture. **A Standard Payment Link** (`POST /v1/payment_links`)
is the documented, checkout-oriented way to give the customer a fresh,
hosted page to pay again. This project never calls
`POST /v1/payments/:id/capture` for a failed payment.

## 3. API endpoints used

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/v1/payment_links` | Create a Standard Payment Link for RETRY recovery |
| GET | `/v1/payment_links/{id}` | Fetch a Payment Link's current status (client method exists; not yet wired to a polling endpoint — see §6) |

Both are documented at `https://razorpay.com/docs/api/payment-links/`.
No undocumented or invented endpoint is used anywhere in this codebase.

## 4. Authentication

HTTP Basic Auth using `(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)`, exactly
as Razorpay's REST API documents. The secret is **never logged** —
`RazorpayClient` has no log/print statement that includes the key or a
raw `Authorization` header anywhere; error messages include only the
HTTP status code and Razorpay's own (non-secret) error description.

## 5. Test Mode configuration

| Env var | Default | Purpose |
|---|---|---|
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | empty | Test Mode credentials only — never production keys |
| `RAZORPAY_MODE` | `test` | Startup fails if set to anything else |
| `RAZORPAY_BASE_URL` | `https://api.razorpay.com/v1` | |
| `RAZORPAY_REQUEST_TIMEOUT_SECONDS` | `10.0` | |
| `RAZORPAY_WEBHOOK_SECRET` | empty | Verifies incoming webhook signatures |
| `RECOVERY_EXECUTOR` | `simulation` | `simulation` \| `razorpay_test` |
| `RAZORPAY_FALLBACK_TO_SIMULATION` | `false` | See §12 |

## 6. Payment Link flow

For a `RETRY` action under `RazorpayTestExecutor`:

1. Build a stable `reference_id` (`recoverai-{transaction_id}`) — the
   same transaction always maps to the same reference, which is what
   makes idempotency work (§10).
2. `POST /v1/payment_links` with `amount` (converted to paise),
   `currency`, `description`, `reference_id`, and `notes` containing the
   RecoverAI transaction reference.
3. Result: `execution_status = COMPLETED` (never `SUCCESS`),
   `recovered_amount = 0.0`, `execution_mode = "RAZORPAY_TEST_MODE"`.
   The returned `ExecutionResult` carries `razorpay_payment_link_id`,
   `razorpay_payment_link_url`, and `razorpay_reference_id` for display
   and later confirmation matching.

All other approved actions (`STOP`, `WAIT`, `HUMAN_REVIEW`,
`SEND_REMINDER`, `SUGGEST_ALTERNATIVE_PAYMENT`) don't involve Razorpay at
all — `RazorpayTestExecutor` delegates them to an internal
`SimulationExecutor` instance rather than duplicating that logic.

**Creating a Payment Link is not a successful recovery.** This is stated
explicitly in the result's `detail` text, enforced by never setting
`execution_status` to `SUCCESS` at creation time, and tested directly
(`test_payment_link_creation_does_not_count_as_recovered_revenue`).

## 7. Payment confirmation

Only two paths can ever set `execution_status = SUCCESS` for a
Razorpay-executed recovery and populate `recovered_amount`:

1. **Verified webhook** (`POST /api/integrations/razorpay/webhook`,
   implemented — see §8), or
2. The payment-link fetch/status API (`RazorpayClient.fetch_payment_link()`
   — the client method exists and is tested, but is not yet wired to a
   scheduled/on-demand polling endpoint in this phase; the webhook path
   is the primary confirmation mechanism implemented here).

A frontend-provided `payment_success: true` is **never** accepted
anywhere in this codebase — `POST /api/recovery/{id}` takes no body at
all (unchanged from Phase 6), and there is no endpoint that lets a
client directly set `execution_status` or `recovered_amount`.

## 8. Webhook verification

Razorpay signs webhook payloads with **HMAC-SHA256 over the raw request
body**, using the webhook secret configured in the Razorpay dashboard,
sent in the `X-Razorpay-Signature` header — this is Razorpay's documented
verification method. `app.integrations.razorpay.webhook_security.verify_webhook_signature()`
recomputes the HMAC and compares it to the header using
`hmac.compare_digest` (constant-time, avoiding timing attacks). A
request with a missing or incorrect signature is rejected with `401`
**before its payload is read for anything** — an attacker cannot get any
information out of a malformed signature attempt.

**Caveat, stated plainly**: this sandbox environment had no network
access to Razorpay's live documentation while implementing this file.
The HMAC-SHA256-over-raw-body scheme matches Razorpay's long-documented,
widely-referenced webhook verification approach, and the event names
used (`payment_link.paid`, `payment_link.cancelled`,
`payment_link.expired`) match Razorpay's documented Payment Links
webhook events — but neither was re-verified against current live docs
during this implementation. **Verify both against Razorpay's current
webhook documentation before relying on this in a real demo or
production.**

Webhook processing is **idempotent**: if the matched `RecoveryAttempt`
is already `SUCCESS`, a redelivered webhook is a no-op — it never
double-counts recovered revenue (Razorpay, like most webhook senders,
may redeliver the same event).

## 9. Revenue accounting

Unchanged from Phase 5's invariant, now also true across the Razorpay
path: **only a confirmed successful payment contributes to
`recovered_amount`.** None of the following count as recovered revenue:

- Payment Link created
- Payment Link issued / opened / pending
- Payment Link failed / cancelled / expired
- Webhook not yet received

`compute_batch_revenue_metrics()` (Phase 5) and the dashboard's revenue
definitions (Phase 6) require no changes — they already key off
`execution_status == SUCCESS`, which a Payment Link creation never sets.

## 10. Idempotency

The same DB-backed idempotency introduced in Phase 6
(`POST /api/recovery/{id}` returns the existing `RecoveryAttempt` if one
already exists for that payment, rather than re-executing) applies
identically here — `RazorpayTestExecutor` is called from the same single
call site as `SimulationExecutor`, so a repeated request never reaches
`create_payment_link()` a second time for the same transaction.
`test_duplicate_recovery_request_does_not_create_second_payment_link`
verifies this directly: two calls to `recover_transaction()` for the
same transaction result in exactly one `create_payment_link()` call.

## 11. Safety boundary

Identical to Phase 3/5's guarantee, now proven against the real Razorpay
adapter too:

```
AI recommendation -> Phase 3 rules -> ALLOW -> RazorpayTestExecutor
```

`BLOCK` and `HUMAN_APPROVAL` **never** reach `RazorpayTestExecutor.execute()`
— tested with a call-spy executor
(`test_block_prevents_razorpay_call`, `test_human_approval_prevents_razorpay_call`)
that records whether it was ever invoked and asserts it was not, exactly
mirroring Phase 5's equivalent proof for `SimulationExecutor`.

## 12. Simulation fallback

`RECOVERY_EXECUTOR=simulation` (default) continues working exactly as
in Phase 5 — zero behavioral change, verified by
`test_simulation_executor_unchanged_default_success`.

If `RECOVERY_EXECUTOR=razorpay_test` is set but `RAZORPAY_KEY_ID`/
`RAZORPAY_KEY_SECRET` are missing, the executor factory **fails closed
by default** — `get_executor()` raises `RazorpayConfigurationError`,
surfaced by the API as `503 Service Unavailable` with a message naming
which env vars to set (never a secret value). Setting
`RAZORPAY_FALLBACK_TO_SIMULATION=true` instead falls back to
`SimulationExecutor` — an explicit opt-in, never silent, and never a
path to live mode (that's blocked independently by the `RAZORPAY_MODE`
startup validation in §5).

## 13. Test Mode limitations

Razorpay documents a limit of **30 Payment Links per business in Test
Mode**. The automated test suite creates zero real Payment Links — every
test uses a `FakePaymentLinkClient` test double that never touches the
network (`RazorpayClient` itself is only constructed directly, without
calling any network method, in the auth-configuration tests). If a live
verification is performed, create at most one controlled test link — see
the Final Report for this phase's live verification result.

## 14. Security

- `.env` is gitignored (unchanged since Phase 1); `RAZORPAY_KEY_SECRET`
  and `RAZORPAY_WEBHOOK_SECRET` are never committed.
- `RazorpayClient` never logs the secret or a raw `Authorization` header.
- The webhook endpoint never trusts an unsigned or incorrectly-signed
  payload for anything — verified before any field of the body is read.
- Only `VITE_*` variables exist in the frontend environment; no Razorpay
  secret is ever sent to or readable from the frontend bundle.
- The `503` configuration-error response names only which env vars to
  set — never a secret value (there is none to leak when credentials are
  missing, and the code path never echoes a configured secret back).

## Frontend

`TransactionDetail.tsx` shows an `ExecutionModeBadge` — **"Simulation /
Test Mode"** (violet) vs **"Razorpay Test Mode"** (blue) — on every
executed transaction, plus (when Razorpay was used) the reference ID,
the Payment Link URL, and an explicit **"Creating a Payment Link does
not mean payment recovered"** caveat until `recovered_amount > 0`. The
audit timeline recognizes the three new Razorpay-specific event types
(`RAZORPAY_PAYMENT_LINK_CREATED`, `RAZORPAY_PAYMENT_CONFIRMED`,
`RAZORPAY_PAYMENT_FAILED`) with readable labels. No other page or
component was redesigned.
