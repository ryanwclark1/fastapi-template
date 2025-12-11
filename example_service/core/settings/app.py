"""Application settings for FastAPI configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_app_yaml_source

Environment = Literal["development", "staging", "production", "test"]


class AppSettings(BaseSettings):
    """FastAPI application settings.

    Environment variables use APP_ prefix.
    Example: APP_DEBUG=true, APP_TITLE="My API"
    """

    # Service identity
    service_name: str = Field(
        default="example-service",
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Service name for logging/tracing (lowercase, hyphens allowed)",
    )
    title: str = Field(
        default="Example Service API",
        min_length=1,
        max_length=200,
        description="API title displayed in documentation",
    )
    summary: str | None = Field(
        default=None,
        max_length=500,
        description="Brief API summary shown in documentation",
    )
    description: str = Field(
        default="FastAPI service template following standard architecture patterns",
        description="API description (supports Markdown)",
    )
    version: str = Field(
        default="1.0.0",
        min_length=1,
        max_length=50,
        pattern=r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$",
        description="API version (semver format)",
    )
    environment: Environment = Field(
        default="development", description="Environment: development|staging|production|test",
    )
    api_prefix: str = Field(
        default="/api/v1",
        min_length=1,
        max_length=255,
        pattern=r"^/.*$",
        description="Base URL prefix for API routes (e.g., /api/v1)",
    )

    # FastAPI toggles
    debug: bool = Field(default=False, description="Enable debug mode")
    docs_url: str | None = Field(default="/docs", description="Swagger UI path")
    redoc_url: str | None = Field(default="/redoc", description="ReDoc path")
    openapi_url: str | None = Field(default="/openapi.json", description="OpenAPI schema path")
    disable_docs: bool = Field(default=False, description="Disable all API documentation")
    root_path: str = Field(
        default="",
        description="Root path for proxy/ingress (set when behind a reverse proxy)",
    )
    root_path_in_servers: bool = Field(
        default=True,
        description="Include root_path in OpenAPI servers list automatically",
    )

    # OpenAPI configuration
    openapi_tags: list[dict[str, Any]] | None = Field(
        default=None,
        description="OpenAPI tags for grouping endpoints (JSON array of tag objects)",
    )
    servers: list[dict[str, Any]] | None = Field(
        default=None,
        description="OpenAPI servers list for multi-environment APIs (JSON array)",
    )

    # Swagger UI configuration
    swagger_ui_oauth2_redirect_url: str | None = Field(
        default="/docs/oauth2-redirect",
        description="OAuth2 redirect URL for Swagger UI",
    )
    swagger_ui_init_oauth: dict[str, Any] | None = Field(
        default=None,
        description="Swagger UI OAuth2 initialization config (JSON object)",
    )
    swagger_ui_parameters: dict[str, Any] | None = Field(
        default=None,
        description="Swagger UI display parameters (JSON object)",
    )
    contact: dict[str, str] | None = Field(
        default=None,
        description="OpenAPI contact info (name, url, email)",
    )
    license_info: dict[str, str] | None = Field(
        default=None,
        description="OpenAPI license info (name, url)",
    )

    # Behavioral settings
    redirect_slashes: bool = Field(
        default=True,
        description="Redirect URLs with trailing slashes to non-trailing (or vice versa)",
    )
    separate_input_output_schemas: bool = Field(
        default=True,
        description="Generate separate OpenAPI schemas for request/response bodies",
    )

    # Server configuration
    host: str = Field(
        default="0.0.0.0", min_length=1, max_length=255, description="Server bind host",
    )
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")

    # CORS configuration
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins (JSON array or comma-separated)",
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials")
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed HTTP methods",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed headers",
    )
    cors_max_age: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="CORS preflight cache max-age in seconds (0-86400)",
    )

    # Security headers configuration
    hsts_max_age: int = Field(
        default=31536000,
        ge=0,
        le=63072000,
        description="HSTS max-age in seconds (default: 1 year, max: 2 years, 0 to disable)",
    )

    # Trusted Host configuration (production only)
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed host headers for TrustedHostMiddleware (production only)",
    )

    # Middleware configuration
    enable_request_size_limit: bool = Field(
        default=True, description="Enable request size limit middleware",
    )
    request_size_limit: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        ge=1024,  # Min 1KB
        le=100 * 1024 * 1024,  # Max 100MB
        description="Maximum request size in bytes",
    )
    enable_rate_limiting: bool = Field(
        default=False, description="Enable rate limiting middleware (requires Redis)",
    )
    rate_limit_per_minute: int = Field(
        default=100, ge=1, le=10000, description="Rate limit per minute",
    )
    rate_limit_window_seconds: int = Field(
        default=60, ge=1, le=3600, description="Rate limit window in seconds",
    )

    # Debug middleware configuration (distributed tracing)
    enable_debug_middleware: bool = Field(
        default=False, description="Enable debug middleware with distributed tracing",
    )
    debug_log_requests: bool = Field(
        default=True, description="Log request details in debug middleware",
    )
    debug_log_responses: bool = Field(
        default=True, description="Log response details in debug middleware",
    )
    debug_log_timing: bool = Field(
        default=True, description="Log timing information in debug middleware",
    )
    debug_header_prefix: str = Field(
        default="X-", description="Header prefix for trace context (X-, Trace-, etc.)",
    )

    # Security settings
    strict_csp: bool = Field(
        default=True,
        description=(
            "Use strict CSP without 'unsafe-inline'/'unsafe-eval'. "
            "Auto-enabled when docs are disabled. Set to False to allow "
            "relaxed CSP even in production (not recommended)."
        ),
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> AppSettings:
        """Validate settings for production environment."""
        if self.environment == "production" and self.debug:
            msg = "Debug mode cannot be enabled in production environment"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_port_range(self) -> AppSettings:
        """Validate port is not using privileged range in production."""
        if self.environment == "production" and self.port < 1024:
            msg = "Cannot use privileged port (<1024) in production without proper setup"
            raise ValueError(
                msg,
            )
        return self

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,  # Immutable settings
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
            create_app_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def docs_enabled(self) -> bool:
        """Check if API documentation is enabled."""
        return not self.disable_docs

    def get_docs_url(self) -> str | None:
        """Get docs URL or None if disabled."""
        return None if self.disable_docs else self.docs_url

    def get_redoc_url(self) -> str | None:
        """Get ReDoc URL or None if disabled."""
        return None if self.disable_docs else self.redoc_url

    def get_openapi_url(self) -> str | None:
        """Get OpenAPI schema URL or None if disabled."""
        return None if self.disable_docs else self.openapi_url

    def get_swagger_ui_oauth2_redirect_url(self) -> str | None:
        """Get Swagger UI OAuth2 redirect URL or None if docs disabled."""
        return None if self.disable_docs else self.swagger_ui_oauth2_redirect_url

    def get_contact(self) -> dict[str, str] | None:
        """Get contact info as dict for FastAPI, or None if empty."""
        return self.contact if self.contact else None

    def get_license_info(self) -> dict[str, str] | None:
        """Get license info as dict for FastAPI, or None if empty."""
        return self.license_info if self.license_info else None

    def get_swagger_ui_parameters(self) -> dict[str, Any] | None:
        """Get Swagger UI parameters, with sensible defaults merged in."""
        if self.disable_docs:
            return None
        # Default Swagger UI parameters for better UX
        defaults: dict[str, Any] = {
            "persistAuthorization": True,  # Keep auth tokens across page reloads
            "filter": True,  # Enable filtering operations
            "deepLinking": True,  # Enable deep linking to operations
        }
        if self.swagger_ui_parameters:
            defaults.update(self.swagger_ui_parameters)
        return defaults
