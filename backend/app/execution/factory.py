"""
Selects the active RecoveryExecutor implementation from configuration.

RECOVERY_EXECUTOR=simulation   (default) -> SimulationExecutor, unchanged
                                             from Phase 5, zero network calls.
RECOVERY_EXECUTOR=razorpay_test           -> RazorpayTestExecutor, real
                                             calls to Razorpay's Test Mode API.

This is the only place executor selection happens - app.execution.service
still just receives whatever executor object it's given (or defaults to
SimulationExecutor directly, unchanged from Phase 5) and calls
.execute(...) on it without caring which concrete class it is.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.execution.executor import RecoveryExecutor, SimulationExecutor
from app.integrations.razorpay.executor import RazorpayTestExecutor, build_razorpay_test_executor


def get_executor(settings: Settings | None = None) -> "RecoveryExecutor | RazorpayTestExecutor":
    settings = settings or get_settings()
    mode = (settings.recovery_executor or "simulation").strip().lower()

    if mode == "razorpay_test":
        return build_razorpay_test_executor(
            key_id=settings.razorpay_key_id,
            key_secret=settings.razorpay_key_secret,
            base_url=settings.razorpay_base_url,
            timeout_seconds=settings.razorpay_request_timeout_seconds,
            fallback_to_simulation=settings.razorpay_fallback_to_simulation,
        )

    # "simulation" or anything unrecognized - fail safe to the known-good default.
    return SimulationExecutor()
