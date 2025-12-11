"""Email service settings for SMTP configuration.

Environment variables use EMAIL_ prefix.
Example: EMAIL_ENABLED=true, EMAIL_SMTP_HOST=smtp.example.com
"""

from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from pydantic import EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EMAIL_FILE_DIR = Path(gettempdir()) / "example_service_emails"


class EmailSettings(BaseSettings):
    """Email service configuration.

    Supports multiple backends:
    - smtp: Standard SMTP/SMTPS delivery
    - console: Log emails to console (development)
    - file: Write emails to files (testing)

    Environment variables use EMAIL_ prefix.
    Example: EMAIL_SMTP_HOST=smtp.gmail.com, EMAIL_SMTP_PORT=587
    """

    # Feature toggle
    enabled: bool = Field(
        default=False,
        description="Enable email sending functionality",
    )

    # Backend selection
    backend: Literal["smtp", "console", "file"] = Field(
        default="smtp",
        description="Email backend: smtp (production), console (dev), file (testing)",
    )

    # SMTP Configuration
    smtp_host: str = Field(
        default="localhost",
        min_length=1,
        max_length=255,
        description="SMTP server hostname",
    )
    smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port (587 for TLS, 465 for SSL, 25 for plain)",
    )
    smtp_username: str | None = Field(
        default=None,
        max_length=255,
        description="SMTP authentication username",
    )
    smtp_password: SecretStr | None = Field(
        default=None,
        description="SMTP authentication password",
    )

    # TLS/SSL Configuration
    use_tls: bool = Field(
        default=True,
        description="Use STARTTLS (port 587). Set False for SSL (port 465) or plain (port 25)",
    )
    use_ssl: bool = Field(
        default=False,
        description="Use implicit SSL/TLS (port 465). Mutually exclusive with use_tls",
    )
    validate_certs: bool = Field(
        default=True,
        description="Validate SSL/TLS certificates. Set False for self-signed certs (not recommended)",
    )

    # Sender Configuration
    default_from_email: EmailStr = Field(
        default="noreply@example.com",
        description="Default sender email address",
    )
    default_from_name: str = Field(
        default="Example Service",
        max_length=100,
        description="Default sender display name",
    )

    # Delivery Settings
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="SMTP connection timeout in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed sends",
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Delay between retry attempts in seconds",
    )

    # Template Configuration
    template_dir: str = Field(
        default="templates/email",
        description="Directory containing email templates (relative to package root)",
    )
    default_template_context: dict | None = Field(
        default=None,
        description="Default context variables for all templates",
    )

    # File Backend Settings (for testing)
    file_path: str = Field(
        default=str(DEFAULT_EMAIL_FILE_DIR),
        description="Directory for file backend to write emails (development/testing only)",
    )

    # Rate Limiting
    rate_limit_per_minute: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Maximum emails per minute (0 = unlimited)",
    )

    # Batch Settings
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum recipients per batch send",
    )

    @model_validator(mode="after")
    def validate_tls_ssl_exclusive(self) -> EmailSettings:
        """Ensure TLS and SSL are mutually exclusive."""
        if self.use_tls and self.use_ssl:
            msg = "use_tls and use_ssl are mutually exclusive"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_smtp_auth(self) -> EmailSettings:
        """Warn if username provided without password or vice versa."""
        has_username = self.smtp_username is not None
        has_password = self.smtp_password is not None
        if has_username != has_password:
            msg = "Both smtp_username and smtp_password must be provided together"
            raise ValueError(msg)
        return self

    model_config = SettingsConfigDict(
        env_prefix="EMAIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    @property
    def is_configured(self) -> bool:
        """Check if email is properly configured for sending."""
        if not self.enabled:
            return False
        if self.backend == "smtp":
            return bool(self.smtp_host)
        return True  # console and file backends always work

    @property
    def requires_auth(self) -> bool:
        """Check if SMTP authentication is configured."""
        return self.smtp_username is not None and self.smtp_password is not None

    def get_smtp_url(self) -> str:
        """Get SMTP URL for debugging (without password)."""
        scheme = "smtps" if self.use_ssl else "smtp"
        auth = f"{self.smtp_username}@" if self.smtp_username else ""
        return f"{scheme}://{auth}{self.smtp_host}:{self.smtp_port}"
