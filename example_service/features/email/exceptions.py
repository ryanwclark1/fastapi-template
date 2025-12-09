"""Custom exceptions for email feature.

Provides domain-specific exceptions for better error handling and clarity.
"""

from __future__ import annotations


class EmailFeatureError(Exception):
    """Base exception for email feature errors."""

    def __init__(self, message: str, *, tenant_id: str | None = None) -> None:
        self.message = message
        self.tenant_id = tenant_id
        super().__init__(message)


class EmailConfigNotFoundError(EmailFeatureError):
    """Raised when email configuration is not found for a tenant."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            f"Email configuration not found for tenant: {tenant_id}",
            tenant_id=tenant_id,
        )


class EmailConfigValidationError(EmailFeatureError):
    """Raised when email configuration validation fails."""

    def __init__(
        self,
        message: str,
        *,
        tenant_id: str | None = None,
        provider_type: str | None = None,
        missing_fields: list[str] | None = None,
    ) -> None:
        self.provider_type = provider_type
        self.missing_fields = missing_fields or []
        super().__init__(message, tenant_id=tenant_id)


class EmailProviderError(EmailFeatureError):
    """Raised when there's an error with the email provider."""

    def __init__(
        self,
        message: str,
        *,
        tenant_id: str | None = None,
        provider: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.provider = provider
        self.error_code = error_code
        super().__init__(message, tenant_id=tenant_id)


class EmailRateLimitError(EmailFeatureError):
    """Raised when email rate limit is exceeded."""

    def __init__(
        self,
        tenant_id: str,
        *,
        limit_type: str = "per_minute",
        current_count: int | None = None,
        limit: int | None = None,
    ) -> None:
        self.limit_type = limit_type
        self.current_count = current_count
        self.limit = limit
        super().__init__(
            f"Rate limit exceeded for tenant {tenant_id}: {limit_type}",
            tenant_id=tenant_id,
        )


class EmailQuotaExceededError(EmailFeatureError):
    """Raised when email quota is exceeded."""

    def __init__(
        self,
        tenant_id: str,
        *,
        quota_type: str = "daily",
        current_usage: int | None = None,
        quota: int | None = None,
    ) -> None:
        self.quota_type = quota_type
        self.current_usage = current_usage
        self.quota = quota
        super().__init__(
            f"{quota_type.capitalize()} quota exceeded for tenant {tenant_id}",
            tenant_id=tenant_id,
        )


class EmailSendError(EmailFeatureError):
    """Raised when email sending fails."""

    def __init__(
        self,
        message: str,
        *,
        tenant_id: str | None = None,
        provider: str | None = None,
        recipient: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.provider = provider
        self.recipient = recipient
        self.error_code = error_code
        super().__init__(message, tenant_id=tenant_id)


__all__ = [
    "EmailConfigNotFoundError",
    "EmailConfigValidationError",
    "EmailFeatureError",
    "EmailProviderError",
    "EmailQuotaExceededError",
    "EmailRateLimitError",
    "EmailSendError",
]
