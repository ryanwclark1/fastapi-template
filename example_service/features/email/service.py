"""Service layer for email feature.

Orchestrates email configuration operations using repositories and the
infrastructure email service.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING

from example_service.core.services.base import BaseService
from example_service.features.email.models import EmailConfig, EmailProviderType
from example_service.features.email.repository import (
    EmailAuditLogRepository,
    EmailConfigRepository,
    EmailUsageLogRepository,
    get_email_audit_log_repository,
    get_email_config_repository,
    get_email_usage_log_repository,
)
from example_service.infra.email.metrics import email_rate_limit_hits_total

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.core.database.repository import SearchResult
    from example_service.features.email.models import EmailAuditLog
    from example_service.features.email.schemas import (
        EmailConfigCreate,
        EmailConfigUpdate,
        EmailUsageStats,
        TestEmailResponse,
    )
    from example_service.infra.email.enhanced_service import EnhancedEmailService


logger = logging.getLogger(__name__)


class EmailConfigService(BaseService):
    """Service for managing email configurations.

    Orchestrates:
    - CRUD operations via EmailConfigRepository
    - Cache invalidation via EnhancedEmailService
    - Business logic and validation
    """

    def __init__(
        self,
        session: AsyncSession,
        email_service: EnhancedEmailService,
        *,
        config_repository: EmailConfigRepository | None = None,
        usage_repository: EmailUsageLogRepository | None = None,
        audit_repository: EmailAuditLogRepository | None = None,
    ) -> None:
        """Initialize service with dependencies.

        Args:
            session: Database session
            email_service: Infrastructure email service for sending
            config_repository: Optional config repository (uses singleton if None)
            usage_repository: Optional usage log repository
            audit_repository: Optional audit log repository
        """
        super().__init__()
        self._session = session
        self._email_service = email_service
        self._config_repo = config_repository or get_email_config_repository()
        self._usage_repo = usage_repository or get_email_usage_log_repository()
        self._audit_repo = audit_repository or get_email_audit_log_repository()

    async def create_or_update_config(
        self,
        tenant_id: str,
        config_data: EmailConfigCreate,
    ) -> EmailConfig:
        """Create or update email configuration for a tenant.

        Args:
            tenant_id: Tenant identifier
            config_data: Configuration data

        Returns:
            Created or updated EmailConfig
        """
        existing_config = await self._config_repo.get_by_tenant_id(
            self._session, tenant_id
        )

        if existing_config:
            # Update existing config
            updated = await self._config_repo.update_config(
                self._session,
                existing_config,
                config_data.model_dump(exclude_unset=True),
            )
            self.logger.info(
                "Email config updated",
                extra={
                    "tenant_id": tenant_id,
                    "provider_type": config_data.provider_type,
                    "operation": "service.update_config",
                },
            )
            config = updated
        else:
            # Create new config
            config = EmailConfig(
                tenant_id=tenant_id,
                **config_data.model_dump(exclude_unset=True),
            )
            config = await self._config_repo.create(self._session, config)
            self.logger.info(
                "Email config created",
                extra={
                    "tenant_id": tenant_id,
                    "provider_type": config_data.provider_type,
                    "operation": "service.create_config",
                },
            )

        await self._session.commit()

        # Invalidate cache so new config takes effect immediately
        self._email_service.invalidate_config_cache(tenant_id)

        return config

    async def get_config(self, tenant_id: str) -> EmailConfig | None:
        """Get email configuration for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            EmailConfig if found, None otherwise
        """
        config = await self._config_repo.get_by_tenant_id(self._session, tenant_id)
        self._lazy.debug(
            lambda: f"service.get_config({tenant_id}) -> {'found' if config else 'not found'}"
        )
        return config

    async def update_config(
        self,
        tenant_id: str,
        config_update: EmailConfigUpdate,
    ) -> EmailConfig | None:
        """Update email configuration for a tenant.

        Args:
            tenant_id: Tenant identifier
            config_update: Fields to update

        Returns:
            Updated EmailConfig or None if not found
        """
        config = await self._config_repo.get_by_tenant_id(self._session, tenant_id)
        if config is None:
            return None

        updated = await self._config_repo.update_config(
            self._session,
            config,
            config_update.model_dump(exclude_unset=True),
        )
        await self._session.commit()

        # Invalidate cache
        self._email_service.invalidate_config_cache(tenant_id)

        self.logger.info(
            "Email config updated",
            extra={
                "tenant_id": tenant_id,
                "operation": "service.update_config",
            },
        )
        return updated

    async def delete_config(self, tenant_id: str) -> bool:
        """Delete email configuration for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if deleted, False if not found
        """
        config = await self._config_repo.get_by_tenant_id(self._session, tenant_id)
        if config is None:
            return False

        await self._config_repo.delete(self._session, config)
        await self._session.commit()

        # Invalidate cache
        self._email_service.invalidate_config_cache(tenant_id)

        self.logger.info(
            "Email config deleted",
            extra={
                "tenant_id": tenant_id,
                "operation": "service.delete_config",
            },
        )
        return True

    async def test_config(
        self,
        tenant_id: str,
        to_email: str,
        *,
        use_tenant_config: bool = True,
    ) -> TestEmailResponse:
        """Send a test email to verify configuration.

        Args:
            tenant_id: Tenant identifier
            to_email: Recipient email address
            use_tenant_config: Whether to use tenant config or system defaults

        Returns:
            TestEmailResponse with result details
        """
        from example_service.features.email.schemas import TestEmailResponse

        start_time = time.perf_counter()

        try:
            result = await self._email_service.send(
                to=to_email,
                subject="Test Email - Configuration Validation",
                body="This is a test email to validate your email configuration.",
                body_html="""
                <html>
                <body>
                    <h2>Test Email</h2>
                    <p>This is a test email to validate your email configuration.</p>
                    <p>If you received this email, your configuration is working correctly.</p>
                    <hr>
                    <p><small>Sent by Email Configuration Test</small></p>
                </body>
                </html>
                """,
                tenant_id=tenant_id if use_tenant_config else None,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            return TestEmailResponse(
                success=result.success,
                message_id=result.message_id,
                provider=result.backend,
                duration_ms=duration_ms,
                error=result.error,
                error_code=result.error_code,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self.logger.exception(
                "Test email failed",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                    "operation": "service.test_config",
                },
            )

            return TestEmailResponse(
                success=False,
                message_id=None,
                provider="unknown",
                duration_ms=duration_ms,
                error=str(e),
                error_code="TEST_FAILED",
            )

    async def check_health(self, tenant_id: str) -> tuple[bool, int | None, str | None]:
        """Check email provider health for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Tuple of (is_healthy, response_time_ms, error_message)
        """
        start_time = time.perf_counter()

        try:
            is_healthy = await self._email_service.health_check(tenant_id)
            response_time_ms = int((time.perf_counter() - start_time) * 1000)
            return (is_healthy, response_time_ms, None if is_healthy else "Health check failed")

        except Exception as e:
            self.logger.exception(
                "Health check failed",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                    "operation": "service.check_health",
                },
            )
            return (False, None, str(e))

    async def get_usage_stats(
        self,
        tenant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> EmailUsageStats:
        """Get email usage statistics for a tenant.

        Args:
            tenant_id: Tenant identifier
            start_date: Start of date range (default: 30 days ago)
            end_date: End of date range (default: now)

        Returns:
            EmailUsageStats with aggregated statistics
        """
        from example_service.features.email.schemas import EmailUsageStats

        if end_date is None:
            end_date = datetime.now(UTC)
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        # Get aggregated stats
        stats = await self._usage_repo.get_usage_stats(
            self._session,
            tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Get provider breakdown
        provider_stats = await self._usage_repo.get_usage_by_provider(
            self._session,
            tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Extract counts and costs by provider
        emails_by_provider = {p: s["count"] for p, s in provider_stats.items()}
        cost_by_provider = {p: round(s["cost"], 4) for p, s in provider_stats.items()}

        # Get rate limit hits from Prometheus metrics
        rate_limit_hits = self._get_rate_limit_hits(tenant_id)

        return EmailUsageStats(
            tenant_id=tenant_id,
            period_start=start_date,
            period_end=end_date,
            total_emails=stats["total_emails"],
            successful_emails=stats["successful_emails"],
            failed_emails=stats["failed_emails"],
            success_rate=round(stats["success_rate"], 2),
            emails_by_provider=emails_by_provider,
            total_cost_usd=round(stats["total_cost_usd"], 4) if stats["total_cost_usd"] else None,
            cost_by_provider=cost_by_provider,
            rate_limit_hits=rate_limit_hits,
            total_recipients=stats["total_recipients"],
        )

    def _get_rate_limit_hits(self, tenant_id: str) -> int:
        """Get rate limit hit count from Prometheus metrics.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Count of rate limit hits
        """
        rate_limit_hits = 0
        try:
            collected = list(email_rate_limit_hits_total.collect())
            if collected:
                samples = list(collected[0].samples)
                for sample in samples:
                    if sample.labels.get("tenant_id") == tenant_id:
                        rate_limit_hits += int(sample.value)
        except Exception as e:
            self.logger.warning(
                "Failed to query rate limit metrics",
                extra={"error": str(e), "tenant_id": tenant_id},
            )
        return rate_limit_hits

    async def get_audit_logs(
        self,
        tenant_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> SearchResult[EmailAuditLog]:
        """Get paginated audit logs for a tenant.

        Args:
            tenant_id: Tenant identifier
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            SearchResult with audit logs and pagination info
        """
        offset = (page - 1) * page_size
        return await self._audit_repo.get_audit_logs(
            self._session,
            tenant_id,
            limit=page_size,
            offset=offset,
        )

    def get_available_providers(self) -> list[dict]:
        """Get list of available email providers with their requirements.

        Returns:
            List of provider information dictionaries
        """
        return [
            {
                "provider_type": EmailProviderType.SMTP,
                "name": "SMTP",
                "description": "Standard SMTP/SMTPS email delivery",
                "required_fields": ["smtp_host", "smtp_port"],
                "optional_fields": [
                    "smtp_username",
                    "smtp_password",
                    "smtp_use_tls",
                    "smtp_use_ssl",
                ],
                "supports_attachments": True,
                "supports_html": True,
                "supports_templates": False,
                "estimated_cost_per_1000": None,
            },
            {
                "provider_type": EmailProviderType.AWS_SES,
                "name": "Amazon SES",
                "description": "Amazon Simple Email Service",
                "required_fields": ["aws_access_key", "aws_secret_key", "aws_region"],
                "optional_fields": ["aws_configuration_set"],
                "supports_attachments": True,
                "supports_html": True,
                "supports_templates": True,
                "estimated_cost_per_1000": 0.10,
            },
            {
                "provider_type": EmailProviderType.SENDGRID,
                "name": "SendGrid",
                "description": "SendGrid API v3",
                "required_fields": ["api_key"],
                "optional_fields": [],
                "supports_attachments": True,
                "supports_html": True,
                "supports_templates": True,
                "estimated_cost_per_1000": 0.15,
            },
            {
                "provider_type": EmailProviderType.MAILGUN,
                "name": "Mailgun",
                "description": "Mailgun API",
                "required_fields": ["api_key"],
                "optional_fields": ["api_endpoint"],
                "supports_attachments": True,
                "supports_html": True,
                "supports_templates": True,
                "estimated_cost_per_1000": 0.80,
            },
            {
                "provider_type": EmailProviderType.CONSOLE,
                "name": "Console (Development)",
                "description": "Log emails to console for development",
                "required_fields": [],
                "optional_fields": [],
                "supports_attachments": False,
                "supports_html": True,
                "supports_templates": False,
                "estimated_cost_per_1000": None,
            },
            {
                "provider_type": EmailProviderType.FILE,
                "name": "File (Testing)",
                "description": "Write emails to files for testing",
                "required_fields": [],
                "optional_fields": [],
                "supports_attachments": True,
                "supports_html": True,
                "supports_templates": False,
                "estimated_cost_per_1000": None,
            },
        ]


__all__ = ["EmailConfigService"]
