"""
Application configuration.

All configuration is loaded from environment variables (via a .env file in
local development). Nothing here is hard-coded: secrets and connection
strings must be supplied through the environment. See .env.example at the
repository root for the full list of variables this app expects.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App metadata ---
    app_name: str = "RecoverAI API"
    environment: str = Field(default="development")

    # --- CORS ---
    cors_allow_origins: str = Field(default="http://localhost:5173")

    # --- Database ---
    # Example: postgresql+psycopg2://user:password@localhost:5432/recoverai
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/recoverai"
    )

    # --- LLM provider (Phase 4) ---
    # "mock" | "anthropic" | "openai" | "none". If a real provider is
    # selected but no API key is configured, the agent factory falls back
    # to the mock provider rather than failing - see app/agent/providers.py.
    llm_provider: str = Field(default="mock")
    llm_api_key: str = Field(default="")
    # Model identifier passed to the real provider, if one is active.
    llm_model: str = Field(default="claude-sonnet-4-6")
    # Timeout for a single LLM provider call. On timeout the agent falls
    # back to HUMAN_REVIEW - see app/agent/service.py.
    llm_request_timeout_seconds: float = Field(default=10.0)

    # --- Recovery rules engine (Phase 3) ---
    # Maximum number of automated RETRY actions before the engine blocks
    # further automated retries for a transaction.
    max_automated_retries: int = Field(default=2)
    # Minimum ML-predicted recovery_probability required to allow an
    # automated RETRY. Below this, the engine blocks automated retry.
    min_recovery_probability: float = Field(default=0.30)
    # Transaction amount (INR) at or above which an active action
    # (RETRY / SEND_REMINDER / SUGGEST_ALTERNATIVE_PAYMENT) requires
    # human approval instead of being auto-allowed.
    high_value_threshold_inr: float = Field(default=50000.0)
    # Comma-separated failure_reason values that hard-block automated
    # RETRY regardless of probability or retry count (e.g. suspected fraud).
    hard_stop_failure_reasons: str = Field(default="risk_flagged")

    # --- Razorpay (Phase 7) ---
    razorpay_key_id: str = Field(default="")
    razorpay_key_secret: str = Field(default="")
    razorpay_base_url: str = Field(default="https://api.razorpay.com/v1")
    razorpay_request_timeout_seconds: float = Field(default=10.0)
    # MUST be "test" - this project never processes real money. Validated
    # below; get_settings() raises at startup if this is anything else.
    razorpay_mode: str = Field(default="test")
    # Verifies webhook payload authenticity - see app/api/razorpay_webhook.py.
    razorpay_webhook_secret: str = Field(default="")

    # --- Execution adapter selection (Phase 7) ---
    # "simulation" (Phase 5's in-process fake, default) | "razorpay_test"
    # (real calls to Razorpay's Test Mode API - see app/integrations/razorpay/).
    recovery_executor: str = Field(default="simulation")
    # If "razorpay_test" is selected but no Razorpay credentials are
    # configured, the executor factory fails with a clear configuration
    # error by default. Setting this to true instead falls back to the
    # simulation executor (logged, never silent) - useful for demos where
    # Razorpay credentials aren't available but RECOVERY_EXECUTOR is set
    # to razorpay_test in a shared .env. Never auto-enables live mode.
    razorpay_fallback_to_simulation: bool = Field(default=False)

    @field_validator("razorpay_mode")
    @classmethod
    def _razorpay_mode_must_be_test(cls, value: str) -> str:
        if value.strip().lower() != "test":
            raise ValueError(
                f"RAZORPAY_MODE must be 'test' - got '{value}'. This project never "
                "processes real money; live mode is refused at startup."
            )
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def hard_stop_failure_reasons_list(self) -> list[str]:
        return [r.strip() for r in self.hard_stop_failure_reasons.split(",") if r.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so the .env file is only parsed once."""
    return Settings()
