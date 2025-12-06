"""Base email provider protocol and abstract class.

Defines the contract that all email providers must implement.

Usage:
    class MyProvider(BaseEmailProvider):
        async def send(self, message: EmailMessage) -> EmailDeliveryResult:
            # Implementation
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Result of an email delivery attempt.

    Immutable dataclass representing the outcome of sending an email.

    Attributes:
        success: Whether delivery succeeded
        message_id: Provider-assigned message ID (for tracking)
        provider: Provider name (smtp, sendgrid, etc.)
        recipients_accepted: List of accepted recipients
        recipients_rejected: List of rejected recipients
        error: Error message if failed
        error_code: Error category for programmatic handling
        duration_ms: Time taken to send in milliseconds
        metadata: Provider-specific metadata
    """

    success: bool
    message_id: str | None
    provider: str
    recipients_accepted: list[str] = field(default_factory=list)
    recipients_rejected: list[str] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate result consistency."""
        if self.success and not self.message_id:
            # Allow success without message_id for some providers
            pass
        if not self.success and not self.error:
            object.__setattr__(self, "error", "Unknown error")

    @classmethod
    def success_result(
        cls,
        message_id: str,
        provider: str,
        recipients: list[str] | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EmailDeliveryResult:
        """Create a successful delivery result.

        Args:
            message_id: Provider message ID
            provider: Provider name
            recipients: List of accepted recipients
            duration_ms: Delivery duration
            metadata: Additional metadata

        Returns:
            EmailDeliveryResult for successful delivery
        """
        return cls(
            success=True,
            message_id=message_id,
            provider=provider,
            recipients_accepted=recipients or [],
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    @classmethod
    def failure_result(
        cls,
        provider: str,
        error: str,
        error_code: str | None = None,
        recipients_rejected: list[str] | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EmailDeliveryResult:
        """Create a failed delivery result.

        Args:
            provider: Provider name
            error: Error message
            error_code: Error category
            recipients_rejected: List of rejected recipients
            duration_ms: Duration before failure
            metadata: Additional metadata

        Returns:
            EmailDeliveryResult for failed delivery
        """
        return cls(
            success=False,
            message_id=None,
            provider=provider,
            recipients_rejected=recipients_rejected or [],
            error=error,
            error_code=error_code,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capabilities supported by a provider.

    Used to determine what features are available for a given provider.

    Attributes:
        supports_attachments: Can send file attachments
        supports_html: Can send HTML content
        supports_templates: Has native template support
        supports_tracking: Can track opens/clicks
        supports_scheduling: Can schedule future sends
        supports_batch: Can send to multiple recipients efficiently
        max_recipients: Maximum recipients per send (0 = unlimited)
        max_attachment_size_mb: Maximum attachment size in MB
    """

    supports_attachments: bool = True
    supports_html: bool = True
    supports_templates: bool = False
    supports_tracking: bool = False
    supports_scheduling: bool = False
    supports_batch: bool = True
    max_recipients: int = 0  # 0 = unlimited
    max_attachment_size_mb: float = 25.0


@runtime_checkable
class EmailProvider(Protocol):
    """Protocol defining the email provider interface.

    All email providers must implement these methods.
    Using Protocol allows duck typing and easier testing.

    Example:
        def send_with_provider(provider: EmailProvider, msg: EmailMessage):
            result = await provider.send(msg)
            if result.success:
                print(f"Sent: {result.message_id}")
    """

    async def send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send an email message.

        Args:
            message: The email message to send

        Returns:
            EmailDeliveryResult with delivery status
        """
        ...

    async def health_check(self) -> bool:
        """Check if the provider is healthy and can send emails.

        Returns:
            True if provider is operational
        """
        ...

    def get_capabilities(self) -> ProviderCapabilities:
        """Get provider capabilities.

        Returns:
            ProviderCapabilities describing what this provider supports
        """
        ...

    @property
    def provider_name(self) -> str:
        """Get the provider name (e.g., 'smtp', 'sendgrid')."""
        ...


class BaseEmailProvider(ABC):
    """Abstract base class for email providers.

    Provides common functionality for all providers:
    - Timing measurement
    - Logging
    - Error handling patterns

    Subclasses must implement:
    - _do_send(): Actual sending logic
    - _do_health_check(): Health check logic
    - provider_name property

    Example:
        class MyProvider(BaseEmailProvider):
            @property
            def provider_name(self) -> str:
                return "myprovider"

            async def _do_send(self, message: EmailMessage) -> EmailDeliveryResult:
                # Send logic here
                return EmailDeliveryResult.success_result(...)

            async def _do_health_check(self) -> bool:
                return True
    """

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize provider with configuration.

        Args:
            config: Resolved email configuration for this provider
        """
        self._config = config
        self._capabilities = self._default_capabilities()

        logger.info(
            f"{self.provider_name} provider initialized",
            extra={
                "tenant_id": config.tenant_id,
                "source": config.source,
            },
        )

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        ...

    @abstractmethod
    async def _do_send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Implement the actual sending logic.

        Args:
            message: The email message to send

        Returns:
            EmailDeliveryResult with delivery status
        """
        ...

    @abstractmethod
    async def _do_health_check(self) -> bool:
        """Implement the actual health check logic.

        Returns:
            True if provider is healthy
        """
        ...

    def _default_capabilities(self) -> ProviderCapabilities:
        """Get default capabilities (can be overridden by subclasses).

        Returns:
            Default ProviderCapabilities
        """
        return ProviderCapabilities()

    async def send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send an email with timing and error handling.

        This wraps _do_send() with common functionality:
        - Timing measurement
        - Logging
        - Error handling

        Args:
            message: The email message to send

        Returns:
            EmailDeliveryResult with delivery status
        """
        start_time = time.perf_counter()

        try:
            result = await self._do_send(message)

            # Add timing if not already set
            if result.duration_ms is None:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                # Create new result with timing (dataclass is frozen)
                result = EmailDeliveryResult(
                    success=result.success,
                    message_id=result.message_id,
                    provider=result.provider,
                    recipients_accepted=result.recipients_accepted,
                    recipients_rejected=result.recipients_rejected,
                    error=result.error,
                    error_code=result.error_code,
                    duration_ms=duration_ms,
                    metadata=result.metadata,
                )

            # Log result
            if result.success:
                logger.info(
                    f"Email sent via {self.provider_name}",
                    extra={
                        "message_id": result.message_id,
                        "provider": self.provider_name,
                        "recipients": len(result.recipients_accepted),
                        "duration_ms": result.duration_ms,
                        "tenant_id": self._config.tenant_id,
                    },
                )
            else:
                logger.warning(
                    f"Email send failed via {self.provider_name}",
                    extra={
                        "provider": self.provider_name,
                        "error": result.error,
                        "error_code": result.error_code,
                        "duration_ms": result.duration_ms,
                        "tenant_id": self._config.tenant_id,
                    },
                )

            return result

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                f"Unexpected error in {self.provider_name} provider",
                extra={
                    "provider": self.provider_name,
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "tenant_id": self._config.tenant_id,
                },
            )
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=str(e),
                error_code="UNEXPECTED_ERROR",
                duration_ms=duration_ms,
            )

    async def health_check(self) -> bool:
        """Check if provider is healthy with logging.

        Returns:
            True if provider is operational
        """
        try:
            healthy = await self._do_health_check()
            logger.debug(
                f"{self.provider_name} health check: {'healthy' if healthy else 'unhealthy'}",
                extra={
                    "provider": self.provider_name,
                    "healthy": healthy,
                    "tenant_id": self._config.tenant_id,
                },
            )
            return healthy
        except Exception as e:
            logger.warning(
                f"{self.provider_name} health check failed",
                extra={
                    "provider": self.provider_name,
                    "error": str(e),
                    "tenant_id": self._config.tenant_id,
                },
            )
            return False

    def get_capabilities(self) -> ProviderCapabilities:
        """Get provider capabilities.

        Returns:
            ProviderCapabilities for this provider
        """
        return self._capabilities

    @property
    def config(self) -> ResolvedEmailConfig:
        """Get the resolved configuration."""
        return self._config


__all__ = [
    "BaseEmailProvider",
    "EmailDeliveryResult",
    "EmailProvider",
    "ProviderCapabilities",
]
