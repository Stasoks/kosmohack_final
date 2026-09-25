from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEMO_DEFAULTS = {
    "demo-jwt-secret-change-me-at-least-32-bytes",
    "demo-owner-change-me",
    "demo-app-change-me",
    "demo-source-token-change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_name: str = "TRACE-Q"
    environment: Literal["development", "test", "production"] = "production"
    demo_mode: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://traceq_app:change-me@postgres:5432/traceq"
    migration_database_url: str | None = None
    demo_privileged_database_url: str | None = None

    jwt_signing_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_hours: int = 8
    aes_data_key_b64: SecretStr
    aes_key_id: str = "data-key-v1"
    integrity_hmac_key_b64: SecretStr
    integrity_key_id: str = "integrity-key-v1"

    erp_emulator_url: str = "http://erp-emulator:8090"
    erp_timeout_seconds: float = 5.0
    outbox_poll_seconds: float = 1.0
    outbox_max_attempts: int = 8
    source_demo_token: SecretStr | None = None

    demo_controller_password: SecretStr | None = None
    demo_master_password: SecretStr | None = None
    demo_technologist_password: SecretStr | None = None
    demo_manager_password: SecretStr | None = None
    demo_admin_password: SecretStr | None = None

    @field_validator("source_demo_token", mode="before")
    @classmethod
    def empty_source_token_is_none(cls, value):
        return None if value in (None, "") else value

    @field_validator("aes_data_key_b64")
    @classmethod
    def validate_aes_key(cls, value: SecretStr) -> SecretStr:
        try:
            decoded = base64.b64decode(value.get_secret_value(), validate=True)
        except Exception as exc:
            raise ValueError("AES_DATA_KEY_B64 must be valid base64") from exc
        if len(decoded) != 32:
            raise ValueError("AES_DATA_KEY_B64 must decode to exactly 32 bytes")
        return value

    @field_validator("integrity_hmac_key_b64")
    @classmethod
    def validate_hmac_key(cls, value: SecretStr) -> SecretStr:
        try:
            decoded = base64.b64decode(value.get_secret_value(), validate=True)
        except Exception as exc:
            raise ValueError("INTEGRITY_HMAC_KEY_B64 must be valid base64") from exc
        if len(decoded) < 32:
            raise ValueError("INTEGRITY_HMAC_KEY_B64 must decode to at least 32 bytes")
        return value

    @model_validator(mode="after")
    def reject_demo_secrets_outside_demo(self) -> "Settings":
        if self.demo_mode:
            return self
        values = [self.jwt_signing_secret.get_secret_value()]
        if self.source_demo_token:
            values.append(self.source_demo_token.get_secret_value())
        if any(value in DEMO_DEFAULTS or value.startswith("demo-") for value in values):
            raise ValueError("Known demo secrets are forbidden when DEMO_MODE=false")
        if len(self.jwt_signing_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SIGNING_SECRET must contain at least 32 characters")
        return self

    def aes_key(self) -> bytes:
        return base64.b64decode(self.aes_data_key_b64.get_secret_value())

    def integrity_key(self) -> bytes:
        return base64.b64decode(self.integrity_hmac_key_b64.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
