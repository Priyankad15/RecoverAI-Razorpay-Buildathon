"""
RazorpayTestExecutor: the second concrete executor behind the
RecoveryExecutor interface (see app/execution/executor.py for the
interface contract and the SimulationExecutor implementation).

This is the ONLY module in the codebase that knows Razorpay exists.
The orchestrator (app.execution.service.recover_transaction) calls
execute(action, transaction, forced_outcome=None) exactly like it calls
SimulationExecutor - it has no idea which concrete executor it's using,
and it never re-implements or bypasses Phase 3's safety rules: this
class is called from exactly the same single call site (the `ALLOW`
branch) that SimulationExecutor is called from.

RETRY IS NOT A CAPTURE CALL
----------------------------
Razorpay's Payments APIs retrieve payment details and capture an
*already-authorized* payment - they are not used to collect a new
payment, and a failed payment was never authorized. So RETRY here means:
create a Razorpay Test Mode Payment Link (a hosted checkout page) for the
customer to pay again - the documented, checkout-oriented recovery flow.

WHAT SUCCESS MEANS HERE
-------------------------
Creating a Payment Link is NOT a successful recovery. It's an outreach
action, exactly like SEND_REMINDER - `execution_status` is `COMPLETED`,
`recovered_amount` is `0.0`, and the detail text says so explicitly.
Only a confirmed successful payment (via the documented payment-link
fetch/status API, or a verified webhook - see
app/api/razorpay_webhook.py) can ever set `execution_status` to
`SUCCESS` and populate `recovered_amount`. See docs/razorpay-test-mode.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.execution.enums import ExecutionStatus
from app.execution.executor import RecoveryExecutor, SimulationExecutor
from app.execution.models import ExecutionResult
from app.integrations.razorpay.client import RazorpayClient, RazorpayClientError
from app.rules.enums import RecoveryAction

_MONETARY_ACTIONS = {RecoveryAction.RETRY}


class RazorpayConfigurationError(Exception):
    """Raised when RazorpayTestExecutor is constructed without valid
    credentials and no simulation fallback is configured. Fails closed:
    never silently proceeds without a working client."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RazorpayTestExecutor:
    """
    Executes RETRY via a real Razorpay Test Mode Payment Link. All other
    approved actions (STOP, WAIT, HUMAN_REVIEW, SEND_REMINDER,
    SUGGEST_ALTERNATIVE_PAYMENT) don't involve Razorpay at all, so they
    are delegated to an internal SimulationExecutor rather than
    duplicating that logic here.
    """

    def __init__(self, client: RazorpayClient):
        self._client = client
        self._simulation_fallback = SimulationExecutor()

    def execute(self, action: str, transaction: dict, forced_outcome: str | None = None) -> ExecutionResult:
        try:
            recovery_action = RecoveryAction(action)
        except ValueError:
            # Same closed action set as SimulationExecutor - re-raise the
            # identical exception type so callers don't need to know
            # which concrete executor is active.
            from app.execution.executor import UnsupportedExecutionAction

            raise UnsupportedExecutionAction(
                f"'{action}' is not an approved recovery action and cannot be executed"
            ) from None

        if recovery_action not in _MONETARY_ACTIONS:
            # Nothing Razorpay-specific about STOP/WAIT/HUMAN_REVIEW/
            # SEND_REMINDER/SUGGEST_ALTERNATIVE_PAYMENT - reuse the exact
            # same passive/outreach handling as the simulation executor.
            return self._simulation_fallback.execute(action, transaction, forced_outcome)

        return self._create_payment_link_for_retry(transaction)

    def _create_payment_link_for_retry(self, transaction: dict) -> ExecutionResult:
        transaction_id = str(transaction.get("transaction_id", "UNKNOWN"))
        amount = float(transaction.get("amount") or 0.0)
        # Deterministic, stable reference_id: the same transaction always
        # maps to the same reference_id, so a well-behaved caller (the
        # orchestrator's DB-backed idempotency, see app.execution.service
        # and app.api.recovery) never asks us to create a second link for
        # a transaction that already has one.
        reference_id = f"recoverai-{transaction_id}"

        try:
            link = self._client.create_payment_link(
                amount_inr=amount,
                reference_id=reference_id,
                description=f"RecoverAI payment recovery for {transaction_id}",
                notes={"recoverai_transaction_id": transaction_id, "source": "RecoverAI"},
            )
        except RazorpayClientError:
            # Let it propagate - app.execution.service's existing
            # executor-exception handling (Phase 5, unchanged) already
            # catches any exception from execute() and fails closed to
            # NOT_EXECUTED, never SUCCESS. No new error handling needed
            # at the orchestrator layer for this to be safe.
            raise

        return ExecutionResult(
            action=RecoveryAction.RETRY.value,
            status=ExecutionStatus.COMPLETED.value,
            simulation_mode=False,
            execution_mode="RAZORPAY_TEST_MODE",
            recovered_amount=0.0,  # creating a link is NOT a recovered payment
            failure_reason=None,
            executed_at=_now_iso(),
            detail=(
                f"[RAZORPAY TEST MODE] Payment Link created (id={link.id}, "
                f"reference_id={link.reference_id}). This does NOT mean payment was "
                "recovered - awaiting confirmed payment via the payment-link status "
                "check or a verified webhook."
            ),
            razorpay_payment_link_id=link.id,
            razorpay_payment_link_url=link.short_url,
            razorpay_reference_id=link.reference_id,
        )


def build_razorpay_test_executor(
    key_id: str,
    key_secret: str,
    base_url: str,
    timeout_seconds: float,
    fallback_to_simulation: bool,
) -> "RazorpayTestExecutor | RecoveryExecutor":
    """
    Factory used by app.execution.factory.get_executor(). Fails closed by
    default: if credentials are missing, raises RazorpayConfigurationError
    rather than silently doing something unexpected. Only falls back to
    SimulationExecutor if the caller explicitly opted in via
    `fallback_to_simulation` (RAZORPAY_FALLBACK_TO_SIMULATION=true).
    """
    if not key_id or not key_secret:
        if fallback_to_simulation:
            return SimulationExecutor()
        raise RazorpayConfigurationError(
            "RECOVERY_EXECUTOR=razorpay_test but RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET "
            "are not configured. Set both, or set RAZORPAY_FALLBACK_TO_SIMULATION=true "
            "to fall back to the simulation executor instead."
        )

    client = RazorpayClient(key_id=key_id, key_secret=key_secret, base_url=base_url, timeout_seconds=timeout_seconds)
    return RazorpayTestExecutor(client)
