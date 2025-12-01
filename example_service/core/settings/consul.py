"""Consul service discovery configuration settings.

Environment variables use CONSUL_ prefix.
Example: CONSUL_ENABLED=true, CONSUL_HOST=consul.local

Supports two health check modes:
- TTL mode: App pushes status to Consul periodically
- HTTP mode: Consul pulls status from app's health endpoint
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_consul_yaml_source


class HealthCheckMode(str, Enum):
    """Health check mode for Consul service registration."""

    TTL = "ttl"  # App pushes status to Consul (works behind firewalls)
    HTTP = "http"  # Consul pulls from /health endpoint


class ConsulSettings(BaseSettings):
    """Consul service discovery settings.

    Environment variables use CONSUL_ prefix.
    Example: CONSUL_ENABLED=true

    This module provides fully optional service discovery that:
    - Never blocks application startup (graceful degradation)
    - Supports both TTL and HTTP health check modes
    - Falls back gracefully if netifaces is unavailable
    """

    # ──────────────────────────────────────────────────────────────
    # Enable/Disable toggle
    # ──────────────────────────────────────────────────────────────

    enabled: bool = Field(
        default=False,
        description="Enable Consul service discovery (disabled by default)",
    )

    # ──────────────────────────────────────────────────────────────
    # Consul agent connection
    # ──────────────────────────────────────────────────────────────

    host: str = Field(
        default="127.0.0.1",
        description="Consul agent hostname or IP address",
    )

    port: int = Field(
        default=8500,
        ge=1,
        le=65535,
        description="Consul agent HTTP API port",
    )

    scheme: str = Field(
        default="http",
        pattern=r"^https?$",
        description="HTTP scheme for Consul API (http or https)",
    )

    token: SecretStr | None = Field(
        default=None,
        description="Consul ACL token for authentication",
    )

    datacenter: str | None = Field(
        default=None,
        description="Consul datacenter (defaults to agent's datacenter)",
    )

    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates when using HTTPS",
    )

    connect_timeout: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        description="HTTP connection timeout in seconds",
    )

    # ──────────────────────────────────────────────────────────────
    # Service registration
    # ──────────────────────────────────────────────────────────────

    service_name: str | None = Field(
        default=None,
        description="Service name for registration (defaults to app.service_name)",
    )

    service_address: str | None = Field(
        default=None,
        description="Address to advertise. None=auto-detect, or explicit IP/hostname",
    )

    service_address_interface: str = Field(
        default="eth0",
        description="Network interface for auto-detection when service_address is None",
    )

    service_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port to advertise for this service",
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Service tags for filtering and routing",
    )

    meta: dict[str, str] = Field(
        default_factory=dict,
        description="Service metadata key-value pairs",
    )

    # ──────────────────────────────────────────────────────────────
    # Health check mode
    # ──────────────────────────────────────────────────────────────

    health_check_mode: HealthCheckMode = Field(
        default=HealthCheckMode.TTL,
        description="Health check mode: 'ttl' (app pushes) or 'http' (Consul pulls)",
    )

    # ──────────────────────────────────────────────────────────────
    # TTL mode settings (app pushes health status)
    # ──────────────────────────────────────────────────────────────

    ttl_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="TTL duration in seconds (how long before service is marked critical)",
    )

    ttl_heartbeat_interval: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Heartbeat interval in seconds (must be < ttl_seconds)",
    )

    # ──────────────────────────────────────────────────────────────
    # HTTP mode settings (Consul pulls from app)
    # ──────────────────────────────────────────────────────────────

    http_check_path: str = Field(
        default="/health/live",
        description="HTTP endpoint Consul will call for health checks",
    )

    http_check_interval: str = Field(
        default="10s",
        description="How often Consul performs the HTTP check (e.g., '10s', '1m')",
    )

    http_check_timeout: str = Field(
        default="5s",
        description="HTTP check request timeout (e.g., '5s')",
    )

    # ──────────────────────────────────────────────────────────────
    # Deregistration settings
    # ──────────────────────────────────────────────────────────────

    deregister_critical_after: str = Field(
        default="60s",
        description="Auto-deregister service after being critical for this duration",
    )

    # ──────────────────────────────────────────────────────────────
    # Validators
    # ──────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_ttl_settings(self) -> ConsulSettings:
        """Ensure TTL heartbeat interval is less than TTL duration."""
        if self.health_check_mode == HealthCheckMode.TTL and self.ttl_heartbeat_interval >= self.ttl_seconds:
            raise ValueError(
                f"ttl_heartbeat_interval ({self.ttl_heartbeat_interval}s) must be "
                f"less than ttl_seconds ({self.ttl_seconds}s) to avoid flapping"
            )
        return self

    @model_validator(mode="after")
    def _validate_http_settings(self) -> ConsulSettings:
        """Ensure HTTP check path starts with /."""
        if self.health_check_mode == HealthCheckMode.HTTP and not self.http_check_path.startswith("/"):
            raise ValueError("http_check_path must start with '/'")
        return self

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value: Any) -> list[str]:
        """Parse tags from JSON string or comma-separated list."""
        if isinstance(value, str):
            # Try JSON first
            if value.startswith("["):
                import json

                return json.loads(value)
            # Otherwise treat as comma-separated
            return [t.strip() for t in value.split(",") if t.strip()]
        return value if value else []

    @field_validator("meta", mode="before")
    @classmethod
    def _parse_meta(cls, value: Any) -> dict[str, str]:
        """Parse meta from JSON string."""
        if isinstance(value, str):
            import json

            return json.loads(value)
        return value if value else {}

    # ──────────────────────────────────────────────────────────────
    # Computed properties
    # ──────────────────────────────────────────────────────────────

    @computed_field
    @property
    def is_configured(self) -> bool:
        """Check if Consul service discovery is enabled and configured.

        Service discovery is considered configured when:
        - enabled=True
        - host is set (even if default)

        The actual advertise address can be auto-detected at runtime.
        """
        return self.enabled

    @computed_field
    @property
    def base_url(self) -> str:
        """Build Consul agent base URL."""
        return f"{self.scheme}://{self.host}:{self.port}"

    # ──────────────────────────────────────────────────────────────
    # Helper methods
    # ──────────────────────────────────────────────────────────────

    def get_auth_headers(self) -> dict[str, str]:
        """Get HTTP headers for Consul API authentication.

        Returns:
            Dictionary with X-Consul-Token header if token is set.
        """
        if self.token:
            return {"X-Consul-Token": self.token.get_secret_value()}
        return {}

    def build_ttl_check_definition(self) -> dict[str, Any]:
        """Build TTL health check definition for service registration.

        Returns:
            Dictionary for the 'Check' field in service registration.
        """
        return {
            "TTL": f"{self.ttl_seconds}s",
            "DeregisterCriticalServiceAfter": self.deregister_critical_after,
        }

    def build_http_check_definition(self, address: str, port: int) -> dict[str, Any]:
        """Build HTTP health check definition for service registration.

        Args:
            address: Service address for the health check URL.
            port: Service port for the health check URL.

        Returns:
            Dictionary for the 'Check' field in service registration.
        """
        return {
            "HTTP": f"http://{address}:{port}{self.http_check_path}",
            "Interval": self.http_check_interval,
            "Timeout": self.http_check_timeout,
            "DeregisterCriticalServiceAfter": self.deregister_critical_after,
        }

    # ──────────────────────────────────────────────────────────────
    # Model configuration
    # ──────────────────────────────────────────────────────────────

    model_config = SettingsConfigDict(
        env_prefix="CONSUL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_consul_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
