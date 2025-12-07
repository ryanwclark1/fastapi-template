"""External authentication service settings."""

from __future__ import annotations

from typing import Any

from pydantic import AnyUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._sanitizers import sanitize_inline_numeric
from .yaml_sources import create_auth_yaml_source


class AuthSettings(BaseSettings):
    """Accent-Auth authentication and authorization settings.

    Environment variables use AUTH_ prefix.
    Example: AUTH_SERVICE_URL="http://accent-auth:9497"
    """

    # Accent-Auth service configuration
    service_url: AnyUrl | None = Field(
        default=None,
        alias="AUTH_SERVICE_URL",
        description="Base URL for Accent-Auth service (e.g., http://accent-auth:9497)",
    )
    health_checks_enabled: bool = Field(
        default=False,
        description="Enable auth service connectivity checks in health endpoints.",
    )

    # Accent-Auth uses /api/auth/0.1/token/{token} for validation
    # This setting is kept for compatibility but not used with accent-auth
    token_validation_endpoint: str = Field(
        default="/api/auth/0.1/token",
        description="Token validation endpoint path (accent-auth format)",
    )

    # Token settings
    token_cache_ttl: int = Field(
        default=300, ge=0, description="Validated token cache TTL in seconds"
    )
    token_header: str = Field(
        default="Authorization", description="HTTP header containing the token"
    )
    token_scheme: str = Field(default="Bearer", description="Token authentication scheme")

    # Service-to-service authentication
    service_token: SecretStr | None = Field(
        default=None, description="Service token for service-to-service auth"
    )
    service_id: str | None = Field(
        default=None, description="Service identifier for service-to-service auth"
    )

    # Retry and timeout settings
    request_timeout: float = Field(
        default=5.0, ge=0.1, le=30.0, description="Auth request timeout in seconds"
    )
    max_retries: int = Field(default=3, ge=0, le=5, description="Maximum retry attempts")

    # Optional features
    enable_permission_caching: bool = Field(default=True, description="Cache user ACL permissions")
    enable_acl_caching: bool = Field(default=True, description="Cache ACL validation results")

    # NOTE: Development/mock mode has moved to MockModeSettings
    # Use MOCK_MODE=true and MOCK_PERSONA=admin instead of AUTH_DEV_MODE
    # See: example_service.core.settings.mock

    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        extra="ignore",
        env_ignore_empty=True,  # Ignore empty string env vars
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_auth_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def is_configured(self) -> bool:
        """Check if auth service is configured."""
        return self.service_url is not None

    def get_validation_url(self) -> str:
        """Get full token validation URL."""
        if not self.service_url:
            msg = "Auth service URL not configured"
            raise ValueError(msg)
        base = str(self.service_url).rstrip("/")
        endpoint = self.token_validation_endpoint.lstrip("/")
        return f"{base}/{endpoint}"

    @field_validator("token_cache_ttl", mode="before")
    @classmethod
    def _normalize_token_cache_ttl(cls, value: Any) -> Any:
        """Allow inline comments in env values (e.g., "300  # seconds")."""
        return sanitize_inline_numeric(value)

