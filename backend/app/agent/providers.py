"""
Provider abstraction for the AI recovery agent.

Business logic (app.agent.service) never imports a specific vendor SDK
directly - it only calls the LLMProvider interface. Which concrete
provider is used is selected purely by configuration
(Settings.llm_provider / LLM_PROVIDER env var), via get_default_provider().

Every provider - mock or real - returns the same shape: a raw dict with
requested_action / confidence / explanation / reason_codes. Validation of
that shape happens one level up, in app.agent.service, so provider
implementations stay simple and swappable.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.core.config import Settings, get_settings


class ProviderError(Exception):
    """Raised by a provider on any failure: network error, timeout,
    non-2xx response, or a response that isn't parseable JSON. Callers
    (app.agent.service) catch this and fall back to a safe default -
    they never retry-forever or silently proceed."""


class LLMProvider(ABC):
    """Interface every provider (mock or real) must implement."""

    name: str
    is_mock: bool

    @abstractmethod
    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        """Returns a raw dict with (at least) requested_action, confidence,
        explanation, reason_codes. May raise ProviderError. Must never
        silently return a partially-formed or unsafe recommendation -
        anything it can't produce cleanly should be an exception, so the
        caller's fallback path is what runs, not a guess dressed up as
        real output."""
        raise NotImplementedError


class MockProvider(LLMProvider):
    """
    Deterministic, rule-of-thumb heuristic provider - NOT a real AI model.

    Exists so the full agent -> rules-engine workflow can be developed,
    demoed, and tested with zero external dependencies and 100%
    reproducible output. Every explanation this provider returns is
    prefixed with "[MOCK]" and `is_mock` is always True, so downstream
    consumers (UI, audit trail, tests) can never mistake this for a real
    LLM decision.

    This provider deliberately does NOT read Phase 3's policy thresholds -
    it has no notion of "blocked" or "allowed"; it just proposes an
    action using simple, transparent logic. The rules engine remains the
    only authority on what's actually permitted.
    """

    name = "mock"
    is_mock = True

    # Failure reasons a reasonable heuristic would treat as effectively
    # unrecoverable via automated retry - independent of Phase 3's own
    # hard-stop list, which is what's actually authoritative.
    _TERMINAL_FAILURE_REASONS = frozenset({"invalid_card", "risk_flagged"})
    _TEMPORARY_FAILURE_REASONS = frozenset({"network_timeout", "bank_server_error", "otp_failed"})

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        probability = float(context.get("recovery_probability") or 0.0)
        retry_count = int(context.get("retry_count") or 0)
        failure_reason = str(context.get("failure_reason") or "")

        reason_codes: list[str] = []

        if failure_reason in self._TERMINAL_FAILURE_REASONS:
            action = "STOP"
            reason_codes.append("RISK_OR_TERMINAL_FAILURE")
        elif retry_count >= 2:
            action = "STOP"
            reason_codes.append("RETRY_LIMIT_LIKELY_EXCEEDED")
        elif probability >= 0.6:
            action = "RETRY"
            reason_codes.append("HIGH_RECOVERY_PROBABILITY")
            if retry_count == 0:
                reason_codes.append("FIRST_RETRY")
            if failure_reason in self._TEMPORARY_FAILURE_REASONS:
                reason_codes.append("TEMPORARY_FAILURE")
        elif probability >= 0.30:
            action = "SEND_REMINDER"
            reason_codes.append("MODERATE_RECOVERY_PROBABILITY")
        else:
            action = "HUMAN_REVIEW"
            reason_codes.append("LOW_RECOVERY_PROBABILITY")

        # Deterministic confidence derived from probability - never exactly
        # 0 or 1, to honestly reflect that this is a heuristic, not certainty.
        confidence = round(min(max(probability, 0.05), 0.95), 2)

        explanation = (
            f"[MOCK] Deterministic heuristic recommendation - not a real AI decision. "
            f"Based on recovery_probability={probability:.2f}, retry_count={retry_count}, "
            f"failure_reason='{failure_reason or 'unknown'}'."
        )

        return {
            "requested_action": action,
            "confidence": confidence,
            "explanation": explanation,
            "reason_codes": reason_codes,
            "model": "mock-heuristic-v1",
        }


class AnthropicProvider(LLMProvider):
    """
    Real provider backed by the Anthropic Messages API. Requires
    LLM_API_KEY to be configured. Not exercised in the automated test
    suite (tests never depend on a live external API) - included so the
    provider abstraction has a genuine second implementation, and so
    switching LLM_PROVIDER=anthropic in .env is all that's needed to go
    live with a real model.
    """

    name = "anthropic"
    is_mock = False

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 10.0):
        if not api_key:
            raise ValueError("AnthropicProvider requires a non-empty api_key")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def generate_recommendation(self, context: dict) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx is a declared dependency
            raise ProviderError(f"httpx is required for AnthropicProvider: {exc}") from exc

        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 512,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": build_user_prompt(context)}],
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Anthropic API request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic API request failed: {exc}") from exc

        try:
            data = response.json()
            text_blocks = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
            raw_text = "".join(text_blocks).strip()
            parsed = json.loads(raw_text)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Anthropic API response was not valid JSON: {exc}") from exc

        parsed["model"] = data.get("model", self._model)
        return parsed


def get_default_provider(settings: Settings | None = None) -> LLMProvider:
    """
    Selects the active provider from configuration.

    Fail-safe by construction: if a real provider is configured but no
    API key is present, this returns MockProvider rather than raising or
    returning a broken provider - the agent must always have *something*
    usable to call, and that something must never silently pretend to be
    a real model when it isn't.
    """
    settings = settings or get_settings()
    provider_name = (settings.llm_provider or "mock").strip().lower()

    if provider_name == "anthropic" and settings.llm_api_key:
        return AnthropicProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )

    # provider_name == "mock", "none", unrecognized, or a real provider
    # requested without an API key configured.
    return MockProvider()
