"""External authentication service settings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import AnyUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._sanitizers import sanitize_inline_numeric
from .yaml_sources import create_auth_yaml_source

DEFAULT_DEV_PERSONAS: dict[str, dict[str, Any]] = {
    "admin": {
        "user_id": "dev-admin-001",
        "email": "admin@dev.local",
        "roles": ["admin"],
        "permissions": ["#"],
        "acl": ["#"],
        "metadata": {
            "tenant_uuid": "dev-tenant-001",
            "tenant_slug": "dev-tenant",
            "session_uuid": "dev-session-admin",
            "name": "Dev Admin",
        },
    },
    "user": {
        "user_id": "dev-user-001",
        "email": "user@dev.local",
        "roles": ["user"],
        "permissions": [
            "confd.users.me.read",
            "confd.users.me.update",
            "webhookd.subscriptions.*.read",
        ],
        "acl": [
            "confd.users.me.read",
            "confd.users.me.update",
            "webhookd.subscriptions.*.read",
        ],
        "metadata": {
            "tenant_uuid": "dev-tenant-001",
            "tenant_slug": "dev-tenant",
            "session_uuid": "dev-session-user",
            "name": "Dev User",
        },
    },
    "readonly": {
        "user_id": "dev-readonly-001",
        "email": "readonly@dev.local",
        "roles": ["viewer"],
        "permissions": [
            "confd.*.*.read",
            "webhookd.*.*.read",
        ],
        "acl": [
            "confd.*.*.read",
            "webhookd.*.*.read",
        ],
        "metadata": {
            "tenant_uuid": "dev-tenant-001",
            "tenant_slug": "dev-tenant",
            "session_uuid": "dev-session-readonly",
            "name": "Readonly User",
        },
    },
    "service": {
        "service_id": "dev-service-001",
        "email": "service@dev.local",
        "roles": ["service"],
        "permissions": [
            "*.*.*",
            "webhookd.#",
        ],
        "acl": [
            "*.*.*",
            "webhookd.#",
        ],
        "metadata": {
            "tenant_uuid": "dev-tenant-001",
            "tenant_slug": "dev-tenant",
            "session_uuid": "dev-session-service",
            "name": "Dev Service",
        },
    },
    "multitenant_admin": {
        "user_id": "dev-mt-admin-001",
        "email": "multitenant-admin@dev.local",
        "roles": ["admin", "support"],
        "permissions": [
            "#",
            "*.*.*",
        ],
        "acl": [
            "#",
            "*.*.*",
        ],
        "metadata": {
            "tenant_uuid": "dev-tenant-001",
            "tenant_slug": "dev-tenant",
            "session_uuid": "dev-session-mt-admin",
            "name": "Multi-tenant Admin",
            "can_switch_tenants": True,
        },
    },
    "limited_user": {
        "user_id": "dev-limited-001",
        "email": "limited@dev.local",
        "roles": ["user"],
        "permissions": [
            "confd.users.me.read",
            "confd.users.me.update",
        ],
        "acl": [
            "confd.users.me.read",
            "confd.users.me.update",
        ],
        "metadata": {
            "tenant_uuid": "dev-tenant-001",
            "tenant_slug": "dev-tenant",
            "session_uuid": "dev-session-limited",
            "name": "Limited User",
        },
    },
}


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
        default=300,
        ge=0,
        description="Validated token cache TTL in seconds",
    )
    token_header: str = Field(
        default="Authorization",
        description="HTTP header containing the token",
    )
    token_scheme: str = Field(
        default="Bearer",
        description="Token authentication scheme",
    )

    # Service-to-service authentication
    service_token: SecretStr | None = Field(
        default=None,
        description="Service token for service-to-service auth",
    )
    service_id: str | None = Field(
        default=None,
        description="Service identifier for service-to-service auth",
    )

    # Retry and timeout settings
    request_timeout: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Request timeout in seconds for auth service calls",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Whether to verify SSL certificates when calling auth service",
    )
    retry_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retries for failed requests",
    )
    retry_delay: float = Field(
        default=0.5,
        ge=0.1,
        le=10.0,
        description="Base delay between retries in seconds",
    )

    # Optional features
    enable_permission_caching: bool = Field(
        default=True,
        description="Cache user ACL permissions",
    )
    enable_acl_caching: bool = Field(
        default=True,
        description="Cache ACL validation results",
    )

    # Development mode configuration
    dev_mode: bool = Field(
        default=False,
        description="Enable Accent-Auth development mode (NEVER enable in production).",
    )
    dev_mock_user: str = Field(
        default="admin",
        description="Default persona to use when AUTH_DEV_MOCK_USER is not set.",
    )
    dev_mock_users: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Custom development personas keyed by persona name.",
    )

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

    @property
    def is_dev_mode(self) -> bool:
        """Return whether development mode is active."""
        return bool(self.dev_mode)

    def get_validation_url(self) -> str:
        """Get full token validation URL."""
        if not self.service_url:
            msg = "Auth service URL not configured"
            raise ValueError(msg)
        base = str(self.service_url).rstrip("/")
        endpoint = self.token_validation_endpoint.lstrip("/")
        return f"{base}/{endpoint}"

    def _available_personas(self) -> dict[str, dict[str, Any]]:
        personas = {
            name: deepcopy(config) for name, config in DEFAULT_DEV_PERSONAS.items()
        }
        for name, config in self.dev_mock_users.items():
            personas[name] = deepcopy(config)
        return personas

    def get_mock_user_config(self, persona: str | None = None) -> dict[str, Any]:
        """Get mock user configuration for dev mode."""
        persona_name = (persona or self.dev_mock_user or "admin").strip()
        personas = self._available_personas()
        if persona_name not in personas:
            available = ", ".join(sorted(personas))
            msg = f"Mock persona '{persona_name}' not found. Available personas: {available}"
            raise ValueError(msg)

        config = deepcopy(personas[persona_name])
        config.setdefault("metadata", {})
        config.setdefault("permissions", config.get("acl", []))
        config.setdefault("acl", config.get("permissions", []))
        return config

    @field_validator("token_cache_ttl", mode="before")
    @classmethod
    def _normalize_token_cache_ttl(cls, value: Any) -> Any:
        """Allow inline comments in env values (e.g., "300  # seconds")."""
        return sanitize_inline_numeric(value)

    @model_validator(mode="after")
    def _validate_dev_mode_environment(self) -> AuthSettings:
        """Prevent enabling dev mode outside development/test."""
        if self.dev_mode:
            app_settings = get_app_settings()
            environment = getattr(app_settings, "environment", "production")
            if environment not in {"development", "test"}:
                msg = (
                    "CRITICAL SECURITY ERROR: Development mode (AUTH_DEV_MODE=true) "
                    "is only allowed in development or test environments. "
                    "Set AUTH_DEV_MODE=false."
                )
                raise ValueError(msg)
        return self


def get_app_settings() -> AuthSettings:
    """Compatibility shim for tests patching this module-level helper."""
    from .loader import get_app_settings as _get_app_settings

    return _get_app_settings()
