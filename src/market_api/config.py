from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .secrets import JsonFileSecretProvider, SecretProviderError

SECRET_FIELDS = {
    "data_encryption_keys",
    "development_auth_tokens",
    "onboarding_token_secret",
    "webhook_secret",
    "whatsapp_access_token",
    "whatsapp_app_secret",
    "whatsapp_verify_token",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MARKET_", extra="ignore")

    database_url: str = "sqlite:///./market.db"
    auto_create_schema: bool = True
    enforce_migration_head: bool = False
    environment: str = "development"
    log_level: str = "INFO"
    metrics_enabled: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    data_encryption_keys: dict[str, str] = Field(default_factory=dict)
    secrets_file: str | None = None
    operational_retention_days: int = Field(default=90, ge=1, le=3650)
    otp_ttl_minutes: int = 5
    onboarding_token_ttl_seconds: int = 900
    onboarding_token_secret: str = "development-only-onboarding-secret-change-me"
    registration_rate_limit_per_minute: int = 5
    otp_rate_limit_per_minute: int = 3
    chat_rate_limit_per_minute: int = 30
    webhook_secret: str = "change-me-in-production"
    notification_batch_size: int = 25
    notification_max_attempts: int = 5
    notification_poll_seconds: float = 2.0
    notification_retry_base_seconds: float = 30
    notification_retry_max_seconds: float = 3600
    notification_retry_jitter_ratio: float = 0.20
    integration_circuit_failure_threshold: int = 5
    integration_circuit_recovery_seconds: float = 30
    notification_provider: str = "console"
    whatsapp_graph_version: str = "v25.0"
    whatsapp_timeout_seconds: float = 15
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None
    whatsapp_template_name: str = "payment_declined_v1"
    whatsapp_template_language: str = "pt_BR"
    simulation_enabled: bool = False
    auth_mode: str = "disabled"
    development_auth_tokens: dict[str, str] = Field(default_factory=dict)
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_role_claim: str = "app_metadata.market_role"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secrets_file:
        return settings
    payload = JsonFileSecretProvider(settings.secrets_file).load()
    unknown = set(payload) - SECRET_FIELDS
    if unknown:
        raise SecretProviderError("unsupported secrets: " + ", ".join(sorted(unknown)))
    return Settings.model_validate({**settings.model_dump(), **payload})


def validate_runtime_settings(settings: Settings) -> None:
    if settings.environment.lower() != "production":
        return
    errors: list[str] = []
    if settings.database_url.startswith("sqlite"):
        errors.append("SQLite is not allowed")
    if settings.auto_create_schema:
        errors.append("automatic schema creation must be disabled")
    if not settings.enforce_migration_head:
        errors.append("migration head enforcement must be enabled")
    if settings.webhook_secret == "change-me-in-production":
        errors.append("payment webhook secret must be changed")
    if settings.onboarding_token_secret == "development-only-onboarding-secret-change-me":
        errors.append("onboarding token secret must be changed")
    if settings.simulation_enabled:
        errors.append("simulation endpoints must be disabled")
    if "*" in settings.cors_origins:
        errors.append("wildcard CORS origin is not allowed")
    if settings.auth_mode.lower() in {"disabled", "development"}:
        errors.append("production authentication provider must be configured")
    if settings.auth_mode.lower() == "supabase" and not settings.supabase_url:
        errors.append("Supabase URL must be configured")
    if not settings.data_encryption_keys:
        errors.append("data encryption keys must be configured")
    if errors:
        raise RuntimeError("unsafe production configuration: " + "; ".join(errors))
