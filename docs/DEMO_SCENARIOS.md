# Demo Scenarios

Six hero transactions, seeded by `python -m scripts.seed_demo_data`
(idempotent — safe to re-run), each demonstrating one of RecoverAI's
important decision branches. Every number below is a real, observed
output from the actual trained model / rules engine / execution
layer — captured by running the exact API calls listed, not estimated.
**Re-verify after retraining the ML model** (`python -m app.ml.train`) —
these numbers are read off one specific trained artifact, not derived
analytically, and retraining can shift them.

---

## Scenario 1 — Successful Automatic Recovery

| | |
|---|---|
| Transaction ID | `TXN-DEMO-A` |
| Amount | ₹4,999 |
| Failure reason | `network_timeout` |
| Customer profile | Returning, 20 prior transactions, 91% prior success rate |
| Recovery probability | 0.84 |
| Rules decision | `ALLOW` |
| Agent action | `RETRY` |
| Expected result | `execution_status = SUCCESS`, `recovered_amount = ₹4,999` |
| Endpoint | `GET /api/payments/TXN-DEMO-A` (pre-seeded — no trigger needed) |

## Scenario 2 — Failed Automatic Recovery

| | |
|---|---|
| Transaction ID | `TXN-DEMO-B` |
| Amount | ₹4,999 |
| Failure reason | `network_timeout` |
| Customer profile | Same as Scenario 1 |
| Recovery probability | 0.84 |
| Rules decision | `ALLOW` |
| Agent action | `RETRY` |
| Expected result | `execution_status = FAILED`, `recovered_amount = ₹0` — graceful failure, nothing falsely counted as recovered |
| Endpoint | `GET /api/payments/TXN-DEMO-B` (pre-seeded) |

## Scenario 3 — Human Approval

| | |
|---|---|
| Transaction ID | `TXN-DEMO-D` |
| Amount | ₹68,000 (above the ₹50,000 `HIGH_VALUE_THRESHOLD_INR`) |
| Failure reason | `network_timeout` |
| Customer profile | Same as Scenario 1 |
| Recovery probability | 0.84 |
| Rules decision | `HUMAN_APPROVAL` |
| Agent action | `RETRY` (requested, but not authorized) |
| Expected result | `execution_status = PENDING_HUMAN_APPROVAL`, `recovered_amount = ₹0` — execution never runs automatically |
| Endpoint | `GET /api/payments/TXN-DEMO-D` (pre-seeded) |

## Scenario 4 — Blocked

Two distinct BLOCK mechanisms are seeded — worth showing both live, since
they demonstrate different rules engine checks:

**4a. Hard-stop failure reason** (`pay_demo_hard_stop_fraud`)

| | |
|---|---|
| Transaction ID | `pay_demo_hard_stop_fraud` |
| Amount | ₹9,999 |
| Failure reason | `risk_flagged` (the actual configured `HARD_STOP_FAILURE_REASONS` value) |
| Customer profile | Returning, 3 prior transactions, 60% prior success rate |
| Recovery probability | 0.70 (irrelevant here — a high probability cannot override a hard-stop) |
| Rules decision | `BLOCK` (reason: `HARD_STOP_FAILURE_REASON`) |
| Agent action | `RETRY` (requested, blocked regardless) |
| Expected result | `execution_status = BLOCKED`, `recovered_amount = ₹0` |
| Endpoint | `GET /api/payments/pay_demo_hard_stop_fraud` (pre-seeded) |

**4b. Max retries exhausted** (`TXN-DEMO-C`)

| | |
|---|---|
| Transaction ID | `TXN-DEMO-C` |
| Amount | ₹4,999 |
| Rules decision | `BLOCK` (reason: `MAX_RETRIES_REACHED`, retry_count=2) |
| Expected result | `execution_status = BLOCKED`, `recovered_amount = ₹0` |
| Endpoint | `GET /api/payments/TXN-DEMO-C` (pre-seeded) |

## Scenario 5 — Low Probability

| | |
|---|---|
| Transaction ID | `pay_demo_low_probability` |
| Amount | ₹1,299 |
| Failure reason | `insufficient_funds` |
| Customer profile | New customer, 0 prior transactions, high device risk (0.85), 4 historical failures |
| Recovery probability | **0.0599** (observed) |
| Agent action | `HUMAN_REVIEW` — the agent itself declines to recommend an automated retry at this probability |
| Rules decision | `ALLOW` (a passive action needs no gate) |
| Expected result | `execution_status = COMPLETED`, `recovered_amount = ₹0` |
| Endpoint | `POST /api/recovery/pay_demo_low_probability` (seeded unprocessed — trigger live) |

## Scenario 6 — High Probability

| | |
|---|---|
| Transaction ID | `pay_demo_high_probability` |
| Amount | ₹999 |
| Failure reason | `network_timeout` |
| Customer profile | Loyal customer, 50 prior transactions, 98% prior success rate, minimal device risk (0.02) |
| Recovery probability | **0.7992** (observed) |
| Agent action | `RETRY` |
| Rules decision | `ALLOW` |
| Expected result | `execution_status = SUCCESS`, `recovered_amount = ₹999` (default simulation outcome is SUCCESS when unset) |
| Endpoint | `POST /api/recovery/pay_demo_high_probability` (seeded unprocessed — trigger live) |

---

## Full seeded dataset

`python -m scripts.seed_demo_data` seeds **27 payments** total: the 6+1
hero scenarios above, plus 20 additional realistic payments
(`pay_demo_001`..`pay_demo_020`) spanning the full requested amount range
(₹299–₹1,20,000), all four payment methods (card/UPI/netbanking/wallet),
and all ten requested failure reasons (`insufficient_funds`,
`network_error`, `bank_declined`, `timeout`, `authentication_failed`,
`card_expired`, `rate_limit`, `suspected_fraud`, `duplicate_payment`,
`invalid_request`), left unprocessed for live interactive triggering
through the dashboard. Optionally add more generic volume from the
Phase 2 synthetic dataset with `--n-sample N`.

Re-running the seed script is safe: every payment is upserted by
`transaction_id` (never duplicated), and a recovery attempt is only
executed if one doesn't already exist for that payment (verified by
running the script twice against a fresh database and confirming zero
duplicate `transaction_id`s and zero duplicate attempts per payment).
