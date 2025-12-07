"""Enhanced email service with multi-tenant support and provider abstraction.

This module provides an enhanced email service that integrates:
- Multi-tenant configuration resolution
- Provider factory for multiple email backends
- Rate limiting (Phase 3)
- Usage logging (Phase 3)
- Audit logging (Phase 3)
- Prometheus metrics (Phase 3)

Usage:
    # Initialize during app startup
    from example_service.infra.email.enhanced_service import (
        initialize_enhanced_email_service,
        get_enhanced_email_service,
    )

    service = initialize_enhanced_email_service(session_factory, settings)

    # Send email with optional tenant context
    result = await service.send(
        to="user@example.com",
        subject="Hello!",
        body="Welcome!",
        tenant_id="tenant-123",  # Optional - uses tenant config if provided
    )
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any

from example_service.core.exceptions import RateLimitException
from example_service.core.models.email_config import (
    EmailAuditLog,
    EmailProviderType,
    EmailUsageLog,
)
from example_service.infra.ratelimit import check_rate_limit

from . import metrics
from .providers import EmailProviderFactory, initialize_provider_factory
from .resolver import (
    EmailConfigResolver,
    ResolvedEmailConfig,
    initialize_email_config_resolver,
)
from .schemas import (
    EmailAttachment,
    EmailMessage,
    EmailPriority,
    EmailResult,
    EmailStatus,
)
from .templates import (
    EmailTemplateRenderer,
    TemplateNotFoundError,
    get_template_renderer,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.settings.email import EmailSettings
    from example_service.infra.email.providers.base import EmailDeliveryResult
    from example_service.infra.ratelimit import RateLimiter

logger = logging.getLogger(__name__)


class EnhancedEmailService:
    """Enhanced email service with multi-tenant support.

    This service extends the basic EmailService with:
    - Per-tenant email provider configuration
    - Provider factory for multiple backends (SMTP, SES, SendGrid, Mailgun)
    - Configuration caching with TTL
    - Rate limiting with Redis (Phase 3)
    - Usage logging for billing (Phase 3)
    - Audit logging for compliance (Phase 3)
    - Prometheus metrics (Phase 3)

    Example:
        service = get_enhanced_email_service()

        # System-level send (uses global settings)
        result = await service.send(
            to="user@example.com",
            subject="System notification",
            body="...",
        )

        # Tenant-specific send (uses tenant's provider config)
        result = await service.send(
            to="user@example.com",
            subject="Welcome!",
            body="...",
            tenant_id="tenant-123",
        )
    """

    def __init__(
        self,
        resolver: EmailConfigResolver,
        factory: EmailProviderFactory,
        renderer: EmailTemplateRenderer,
        settings: EmailSettings,
        rate_limiter: RateLimiter | None = None,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        """Initialize enhanced email service.

        Args:
            resolver: Config resolver for multi-tenant lookups
            factory: Provider factory for creating email providers
            renderer: Template renderer for email templates
            settings: System-level email settings (fallback)
            rate_limiter: Optional rate limiter (for Phase 3 features)
            session_factory: Optional session factory (for Phase 3 logging)
        """
        self._resolver = resolver
        self._factory = factory
        self._renderer = renderer
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._session_factory = session_factory

        # Track whether Phase 3 features are enabled
        self._rate_limiting_enabled = rate_limiter is not None
        self._logging_enabled = session_factory is not None

        logger.info(
            "Enhanced email service initialized",
            extra={
                "enabled": settings.enabled,
                "default_backend": settings.backend,
                "available_providers": factory.list_providers(),
                "rate_limiting_enabled": self._rate_limiting_enabled,
                "logging_enabled": self._logging_enabled,
            },
        )

    async def send(
        self,
        to: str | list[str],
        subject: str,
        body: str | None = None,
        body_html: str | None = None,
        *,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        attachments: list[EmailAttachment] | None = None,
        priority: EmailPriority = EmailPriority.NORMAL,
        headers: dict[str, str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> EmailResult:
        """Send an email.

        Args:
            to: Recipient email(s)
            subject: Email subject
            body: Plain text body
            body_html: HTML body
            cc: CC recipients
            bcc: BCC recipients
            reply_to: Reply-to address
            from_email: Sender email (overrides config)
            from_name: Sender name (overrides config)
            attachments: File attachments
            priority: Email priority
            headers: Additional headers
            tags: Tags for tracking
            metadata: Custom metadata
            tenant_id: Tenant ID for per-tenant config (optional)

        Returns:
            EmailResult with delivery status
        """
        # Check if email is enabled
        if not self._settings.enabled:
            logger.warning("Email sending is disabled")
            return EmailResult.failure_result(
                error="Email sending is disabled",
                error_code="EMAIL_DISABLED",
                backend=self._settings.backend,
            )

        # Normalize recipients
        recipients = [to] if isinstance(to, str) else list(to)

        # Create message
        message = EmailMessage(
            to=recipients,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            body_text=body,
            body_html=body_html,
            attachments=attachments or [],
            priority=priority,
            headers=headers or {},
            tags=tags or [],
            metadata=metadata or {},
        )

        # Resolve configuration for tenant
        config = await self._resolver.get_config(tenant_id)
        effective_tenant_id = tenant_id or "system"

        # Phase 3: Check rate limits before sending
        try:
            await self._check_rate_limits(config, effective_tenant_id)
        except RateLimitException as e:
            # Rate limit exceeded - record metrics
            metrics.email_delivery_total.labels(
                provider=config.provider_type.value,
                tenant_id=effective_tenant_id,
                status="rate_limited",
            ).inc()
            metrics.email_rate_limit_hits_total.labels(
                tenant_id=effective_tenant_id,
                limit_type="per_minute",
            ).inc()

            logger.warning(
                "Email rate limit exceeded",
                extra={
                    "tenant_id": effective_tenant_id,
                    "provider": config.provider_type.value,
                    "rate_limit": e.extra.get("limit"),
                },
            )

            return EmailResult.failure_result(
                error=str(e),
                error_code="RATE_LIMIT_EXCEEDED",
                backend=config.provider_type.value,
            )

        # Get provider and send
        start_time = time.perf_counter()
        try:
            provider = self._factory.get_provider(config)
            delivery_result = await provider.send(message)

            # Convert provider result to EmailResult
            result = self._convert_delivery_result(delivery_result, config)

            # Phase 3: Record metrics
            duration_seconds = time.perf_counter() - start_time
            metrics.email_delivery_duration_seconds.labels(
                provider=config.provider_type.value
            ).observe(duration_seconds)
            metrics.email_delivery_total.labels(
                provider=config.provider_type.value,
                tenant_id=effective_tenant_id,
                status="success" if result.success else "failed",
            ).inc()
            metrics.email_recipients_total.labels(
                provider=config.provider_type.value,
                tenant_id=effective_tenant_id,
            ).inc(message.recipient_count)

            # Phase 3: Log usage and audit trail
            await self._log_usage(message, result, config, effective_tenant_id, duration_seconds)
            await self._log_audit(message, result, config, effective_tenant_id)

            return result

        except ValueError as e:
            # Provider not available
            logger.error(f"Provider error: {e}", extra={"tenant_id": effective_tenant_id})

            # Record provider error metrics
            metrics.email_provider_errors_total.labels(
                provider=config.provider_type.value,
                tenant_id=effective_tenant_id,
                error_category="provider_unavailable",
            ).inc()

            return EmailResult.failure_result(
                error=str(e),
                error_code="PROVIDER_ERROR",
                backend=config.provider_type.value,
            )
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(
                "Unexpected error sending email",
                extra={"tenant_id": effective_tenant_id, "duration_ms": duration_ms},
            )

            # Record unexpected error metrics
            metrics.email_provider_errors_total.labels(
                provider=config.provider_type.value,
                tenant_id=effective_tenant_id,
                error_category="unexpected",
            ).inc()

            return EmailResult.failure_result(
                error=str(e),
                error_code="UNEXPECTED_ERROR",
                backend=config.provider_type.value,
            )

    async def send_template(
        self,
        to: str | list[str],
        template: str,
        context: dict[str, Any] | None = None,
        subject: str | None = None,
        *,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        attachments: list[EmailAttachment] | None = None,
        priority: EmailPriority = EmailPriority.NORMAL,
        headers: dict[str, str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> EmailResult:
        """Send an email using a template.

        Args:
            to: Recipient email(s)
            template: Template name (without extension)
            context: Template context variables
            subject: Email subject (uses template subject if not provided)
            cc: CC recipients
            bcc: BCC recipients
            reply_to: Reply-to address
            from_email: Sender email
            from_name: Sender name
            attachments: File attachments
            priority: Email priority
            headers: Additional headers
            tags: Tags for tracking
            metadata: Custom metadata
            tenant_id: Tenant ID for per-tenant config

        Returns:
            EmailResult with delivery status

        Raises:
            TemplateNotFoundError: If template doesn't exist
        """
        # Merge context
        full_context = context or {}
        recipients = [to] if isinstance(to, str) else list(to)
        if recipients:
            full_context.setdefault("user_email", recipients[0])

        # Render template
        try:
            html_content, text_content = self._renderer.render(template, **full_context)
        except TemplateNotFoundError:
            logger.error(f"Email template not found: {template}")
            raise

        # Extract subject from context if not provided
        email_subject = subject or full_context.get("subject", f"Email: {template}")

        # Add template tag
        email_tags = list(tags or [])
        email_tags.append(f"template:{template}")

        return await self.send(
            to=to,
            subject=email_subject,
            body=text_content,
            body_html=html_content,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            from_email=from_email,
            from_name=from_name,
            attachments=attachments,
            priority=priority,
            headers=headers,
            tags=email_tags,
            metadata=metadata,
            tenant_id=tenant_id,
        )

    async def send_async(
        self,
        to: str | list[str],
        subject: str,
        body: str | None = None,
        body_html: str | None = None,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Queue an email for background delivery with tenant support.

        Uses tenant-aware background tasks that leverage the EnhancedEmailService
        for per-tenant provider configuration, rate limiting, and usage logging.

        Args:
            to: Recipient email(s)
            subject: Email subject
            body: Plain text body
            body_html: HTML body
            tenant_id: Tenant ID for per-tenant config
            **kwargs: Additional email options

        Returns:
            Task ID for tracking
        """
        from example_service.workers.notifications.tasks import send_tenant_email_task

        recipients = [to] if isinstance(to, str) else list(to)

        # Use tenant-aware task that leverages EnhancedEmailService
        task = await send_tenant_email_task.kiq(
            to=recipients,
            subject=subject,
            body=body,
            body_html=body_html,
            tenant_id=tenant_id,
            **kwargs,
        )

        logger.info(
            "Email queued for background delivery",
            extra={
                "task_id": task.task_id,
                "to": recipients,
                "subject": subject[:50],
                "tenant_id": tenant_id,
            },
        )

        return task.task_id  # type: ignore[no-any-return]

    async def send_template_async(
        self,
        to: str | list[str],
        template: str,
        context: dict[str, Any] | None = None,
        subject: str | None = None,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Queue a template email for background delivery with tenant support.

        Uses tenant-aware background tasks that leverage the EnhancedEmailService
        for per-tenant provider configuration, rate limiting, and usage logging.

        Args:
            to: Recipient email(s)
            template: Template name
            context: Template context
            subject: Email subject override
            tenant_id: Tenant ID for per-tenant config
            **kwargs: Additional email options

        Returns:
            Task ID for tracking
        """
        from example_service.workers.notifications.tasks import (
            send_tenant_template_email_task,
        )

        recipients = [to] if isinstance(to, str) else list(to)

        # Use tenant-aware task that leverages EnhancedEmailService
        task = await send_tenant_template_email_task.kiq(
            to=recipients,
            template=template,
            context=context or {},
            subject=subject,
            tenant_id=tenant_id,
            **kwargs,
        )

        logger.info(
            "Template email queued for background delivery",
            extra={
                "task_id": task.task_id,
                "to": recipients,
                "template": template,
                "tenant_id": tenant_id,
            },
        )

        return task.task_id  # type: ignore[no-any-return]

    async def health_check(self, tenant_id: str | None = None) -> bool:
        """Check if email service is healthy.

        Args:
            tenant_id: Optional tenant ID to check tenant-specific provider

        Returns:
            True if service is operational
        """
        try:
            config = await self._resolver.get_config(tenant_id)
            provider = self._factory.get_provider(config)
            return await provider.health_check()
        except Exception as e:
            logger.warning(
                f"Email health check failed: {e}",
                extra={"tenant_id": tenant_id},
            )
            return False

    def _convert_delivery_result(
        self,
        delivery_result: EmailDeliveryResult,
        config: ResolvedEmailConfig,
    ) -> EmailResult:
        """Convert provider delivery result to EmailResult.

        Args:
            delivery_result: Result from provider
            config: Resolved configuration

        Returns:
            EmailResult compatible with existing API
        """
        if delivery_result.success:
            return EmailResult(
                success=True,
                message_id=delivery_result.message_id,
                status=EmailStatus.SENT,
                recipients_accepted=delivery_result.recipients_accepted,
                recipients_rejected=delivery_result.recipients_rejected,
                backend=delivery_result.provider,
                retry_count=0,
                metadata={
                    "provider": delivery_result.provider,
                    "duration_ms": delivery_result.duration_ms,
                    "tenant_id": config.tenant_id,
                    **delivery_result.metadata,
                },
            )
        return EmailResult(
            success=False,
            message_id=delivery_result.message_id,
            status=EmailStatus.FAILED,
            recipients_accepted=delivery_result.recipients_accepted,
            recipients_rejected=delivery_result.recipients_rejected,
            backend=delivery_result.provider,
            error=delivery_result.error,
            error_code=delivery_result.error_code,
            retry_count=0,
            metadata={
                "provider": delivery_result.provider,
                "duration_ms": delivery_result.duration_ms,
                "tenant_id": config.tenant_id,
                **delivery_result.metadata,
            },
        )

    def template_exists(self, template_name: str) -> bool:
        """Check if a template exists.

        Args:
            template_name: Template name to check

        Returns:
            True if template exists
        """
        return self._renderer.template_exists(template_name)

    def list_templates(self) -> list[str]:
        """List available email templates.

        Returns:
            List of template names
        """
        return self._renderer.list_templates()

    def list_providers(self) -> list[str]:
        """List available email providers.

        Returns:
            List of provider names
        """
        return self._factory.list_providers()

    def invalidate_config_cache(self, tenant_id: str | None = None) -> int:
        """Invalidate configuration cache.

        Call after updating tenant email configuration.

        Args:
            tenant_id: Tenant to invalidate, or None for all

        Returns:
            Number of entries invalidated
        """
        if tenant_id:
            self._resolver.invalidate(tenant_id)
            self._factory.invalidate_cache(tenant_id)
            return 1
        count = self._resolver.invalidate_all()
        self._factory.invalidate_cache()
        return count

    # =========================================================================
    # Phase 3: Rate Limiting, Usage Logging, and Audit Logging
    # =========================================================================

    async def _check_rate_limits(self, config: ResolvedEmailConfig, tenant_id: str) -> None:
        """Check rate limits before sending email.

        Args:
            config: Resolved email configuration
            tenant_id: Tenant ID (or 'system')

        Raises:
            RateLimitException: If rate limit exceeded
        """
        if not self._rate_limiting_enabled or self._rate_limiter is None:
            return

        # Get rate limit from tenant config or system settings
        rate_limit = config.rate_limit_per_minute or self._settings.rate_limit_per_minute

        # Skip if no rate limit configured
        if rate_limit <= 0:
            return

        # Check rate limit (raises RateLimitException if exceeded)
        key = f"email:{tenant_id}"
        await check_rate_limit(
            self._rate_limiter,
            key=key,
            limit=rate_limit,
            window=60,  # 1 minute window
            endpoint="email.send",
        )

    async def _log_usage(
        self,
        message: EmailMessage,
        result: EmailResult,
        config: ResolvedEmailConfig,
        tenant_id: str,
        duration_seconds: float,
    ) -> None:
        """Log email usage for billing and analytics.

        Args:
            message: Email message that was sent
            result: Result of the send operation
            config: Resolved email configuration
            tenant_id: Tenant ID (or 'system')
            duration_seconds: Time taken to send
        """
        if not self._logging_enabled or self._session_factory is None:
            return

        try:
            # Calculate provider cost (rough estimates, adjust per actual pricing)
            cost_per_recipient = self._estimate_cost_per_recipient(config.provider_type)
            total_cost = cost_per_recipient * message.recipient_count if cost_per_recipient else None

            usage_log = EmailUsageLog(
                tenant_id=tenant_id if tenant_id != "system" else None,
                provider=config.provider_type.value,
                recipients_count=message.recipient_count,
                cost_usd=total_cost,
                success=result.success,
                duration_ms=int(duration_seconds * 1000),
                message_id=result.message_id,
                trace_id=message.metadata.get("trace_id"),
            )

            async with self._session_factory() as session:
                session.add(usage_log)
                await session.commit()

            # Update cost metrics
            if total_cost is not None:
                metrics.email_cost_usd_total.labels(
                    provider=config.provider_type.value,
                    tenant_id=tenant_id,
                ).inc(total_cost)

            logger.debug(
                "Email usage logged",
                extra={
                    "tenant_id": tenant_id,
                    "provider": config.provider_type.value,
                    "cost_usd": total_cost,
                    "recipients": message.recipient_count,
                },
            )

        except Exception as e:
            # Log error but don't fail the email send
            logger.error(
                f"Failed to log email usage: {e}",
                extra={"tenant_id": tenant_id},
                exc_info=True,
            )

    async def _log_audit(
        self,
        message: EmailMessage,
        result: EmailResult,
        _config: ResolvedEmailConfig,
        tenant_id: str,
    ) -> None:
        """Log email audit trail (privacy-compliant).

        Uses SHA256 hashing of recipient emails for privacy.

        Args:
            message: Email message that was sent
            result: Result of the send operation
            config: Resolved email configuration
            tenant_id: Tenant ID (or 'system')
        """
        if not self._logging_enabled or self._session_factory is None:
            return

        try:
            # Hash all recipients for privacy
            all_recipients = message.all_recipients
            recipient_hashes = [
                hashlib.sha256(email.encode("utf-8")).hexdigest()[:16] for email in all_recipients
            ]

            # Determine error category
            error_category = None
            if not result.success and result.error_code:
                error_category = self._categorize_error(result.error_code)

            # Create audit logs (one per recipient for compliance)
            audit_logs = [
                EmailAuditLog(
                    tenant_id=tenant_id if tenant_id != "system" else None,
                    recipient_hash=recipient_hash,
                    template_name=message.template_name,
                    status=result.status.value,
                    error_category=error_category,
                )
                for recipient_hash in recipient_hashes
            ]

            async with self._session_factory() as session:
                session.add_all(audit_logs)
                await session.commit()

            logger.debug(
                "Email audit logged",
                extra={
                    "tenant_id": tenant_id,
                    "recipients_count": len(recipient_hashes),
                    "status": result.status.value,
                },
            )

        except Exception as e:
            # Log error but don't fail the email send
            logger.error(
                f"Failed to log email audit: {e}",
                extra={"tenant_id": tenant_id},
                exc_info=True,
            )

    @staticmethod
    def _estimate_cost_per_recipient(provider_type: EmailProviderType) -> float | None:
        """Estimate cost per recipient for a provider.

        These are rough estimates based on typical pricing.
        Update with actual pricing from your provider agreements.

        Args:
            provider_type: Email provider type

        Returns:
            Estimated cost in USD per recipient, or None if free
        """
        # Rough cost estimates (adjust based on actual pricing)
        cost_map = {
            EmailProviderType.AWS_SES: 0.0001,  # $0.10 per 1000 emails
            EmailProviderType.SENDGRID: 0.00015,  # ~$0.15 per 1000 emails (Essentials plan)
            EmailProviderType.MAILGUN: 0.0008,  # $0.80 per 1000 emails (Foundation plan)
            EmailProviderType.SMTP: None,  # Typically no per-email cost
            EmailProviderType.CONSOLE: None,  # Free (dev)
            EmailProviderType.FILE: None,  # Free (test)
        }
        return cost_map.get(provider_type)

    @staticmethod
    def _categorize_error(error_code: str) -> str:
        """Categorize error for audit logging.

        Args:
            error_code: Error code from EmailResult

        Returns:
            Error category (auth, network, recipient, quota, config)
        """
        error_categories = {
            "EMAIL_DISABLED": "config",
            "PROVIDER_ERROR": "config",
            "RATE_LIMIT_EXCEEDED": "quota",
            "UNEXPECTED_ERROR": "network",
        }
        return error_categories.get(error_code, "unknown")


# Module-level singleton
_service: EnhancedEmailService | None = None


def get_enhanced_email_service() -> EnhancedEmailService:
    """Get the singleton enhanced email service.

    Returns:
        EnhancedEmailService instance

    Raises:
        RuntimeError: If service not initialized
    """
    global _service
    if _service is None:
        msg = (
            "Enhanced email service not initialized. "
            "Call initialize_enhanced_email_service() during app startup."
        )
        raise RuntimeError(
            msg
        )
    return _service


def initialize_enhanced_email_service(
    session_factory: Callable[[], AsyncSession],
    settings: EmailSettings,
    cache_ttl: int = 300,
) -> EnhancedEmailService:
    """Initialize the singleton enhanced email service.

    Call this during application startup.

    Args:
        session_factory: Factory for database sessions
        settings: System-level email settings
        cache_ttl: Configuration cache TTL in seconds

    Returns:
        Initialized EnhancedEmailService
    """
    global _service

    # Initialize resolver
    resolver = initialize_email_config_resolver(
        session_factory=session_factory,
        settings=settings,
        cache_ttl=cache_ttl,
    )

    # Initialize provider factory
    factory = initialize_provider_factory()

    # Get template renderer
    renderer = get_template_renderer(settings)

    # Create service
    _service = EnhancedEmailService(
        resolver=resolver,
        factory=factory,
        renderer=renderer,
        settings=settings,
    )

    logger.info(
        "Enhanced email service initialized",
        extra={
            "providers": factory.list_providers(),
            "cache_ttl": cache_ttl,
        },
    )

    return _service


__all__ = [
    "EnhancedEmailService",
    "get_enhanced_email_service",
    "initialize_enhanced_email_service",
]
