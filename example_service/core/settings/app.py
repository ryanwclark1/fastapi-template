"""Application settings for FastAPI configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sources import app_source


class AppSettings(BaseSettings):
    """FastAPI application settings.

    Environment variables use APP_ prefix.
    Example: APP_DEBUG=true, APP_TITLE="My API"
    """

    # Service identity
    service_name: str = Field(
        default="example-service", description="Service name for logging/tracing"
    )
    title: str = Field(default="Example Service API", description="API title")
    version: str = Field(default="1.0.0", description="API version")
    environment: str = Field(
        default="development", description="Environment: development|staging|production"
    )

    # FastAPI toggles
    debug: bool = Field(default=False, description="Enable debug mode")
    docs_url: str | None = Field(default="/docs", description="Swagger UI path")
    redoc_url: str | None = Field(default="/redoc", description="ReDoc path")
    openapi_url: str | None = Field(
        default="/openapi.json", description="OpenAPI schema path"
    )
    disable_docs: bool = Field(
        default=False, description="Disable all API documentation"
    )
    root_path: str = Field(
        default="", description="Root path for proxy/ingress (e.g., /api/v1)"
    )

    # Server configuration
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server port")

    # CORS configuration
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins (JSON array or comma-separated)",
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials")
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed HTTP methods"
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed headers"
    )

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,  # Immutable settings
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Customize settings source precedence: init > files > env > dotenv > secrets."""

        def files_source(_):
            return app_source()

        return (init_settings, files_source, env_settings, dotenv_settings, file_secret_settings)

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
