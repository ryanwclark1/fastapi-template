"""Email configuration management API endpoints.

This module provides REST API endpoints for managing tenant email configurations:
- POST /configs - Create email configuration
- GET /configs - Get current configuration
- PUT /configs - Update configuration
- DELETE /configs - Delete configuration
- POST /configs/test - Test configuration
- GET /configs/usage - Get usage statistics
- GET /configs/audit-logs - Get audit trail
- GET /providers - List available providers
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from example_service.core.dependencies.database import get_async_session
from example_service.core.models.email_config import (
    EmailAuditLog,
    EmailConfig,
    EmailProviderType,
    EmailUsageLog,
)
from example_service.infra.email import get_enhanced_email_service
from example_service.infra.email.metrics import email_rate_limit_hits_total

from .schemas import (
    EmailAuditLogResponse,
    EmailAuditLogsResponse,
    EmailConfigCreate,
    EmailConfigResponse,
    EmailConfigUpdate,
    EmailHealthResponse,
    EmailUsageStats,
    ProviderInfo,
    ProvidersListResponse,
    TestEmailRequest,
    TestEmailResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.email.enhanced_service import EnhancedEmailService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email-configuration"])


# =============================================================================
# CRUD Endpoints
# =============================================================================


@router.post(
    "/configs/{tenant_id}",
    response_model=EmailConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update email configuration",
    description="Create or update email configuration for a tenant. Credentials are encrypted at rest.",
)
async def create_or_update_config(
    tenant_id: str,
    config_data: EmailConfigCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
) -> EmailConfigResponse:
    """Create or update email configuration for a tenant."""
    # Check if config already exists
    stmt = select(EmailConfig).where(EmailConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    existing_config = result.scalar_one_or_none()

    if existing_config:
        # Update existing config
        for field, value in config_data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(existing_config, field, value)

        config = existing_config
        logger.info("Updated email config for tenant: %s", tenant_id)
    else:
        # Create new config
        config = EmailConfig(
            tenant_id=tenant_id,
            **config_data.model_dump(exclude_unset=True),
        )
        session.add(config)
        logger.info("Created email config for tenant: %s", tenant_id)

    await session.commit()
    await session.refresh(config)

    # Invalidate cache so new config takes effect immediately
    email_service.invalidate_config_cache(tenant_id)

    # Convert to response (mask credentials)
    return _to_response(config)


@router.get(
    "/configs/{tenant_id}",
    response_model=EmailConfigResponse,
    summary="Get email configuration",
    description="Retrieve email configuration for a tenant. Credentials are masked.",
)
async def get_config(
    tenant_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> EmailConfigResponse:
    """Get email configuration for a tenant."""
    stmt = select(EmailConfig).where(EmailConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email configuration not found for tenant: {tenant_id}",
        )

    return _to_response(config)


@router.put(
    "/configs/{tenant_id}",
    response_model=EmailConfigResponse,
    summary="Update email configuration",
    description="Update specific fields of email configuration. Only provided fields are updated.",
)
async def update_config(
    tenant_id: str,
    config_update: EmailConfigUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
) -> EmailConfigResponse:
    """Update email configuration for a tenant."""
    stmt = select(EmailConfig).where(EmailConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email configuration not found for tenant: {tenant_id}",
        )

    # Update only provided fields
    for field, value in config_update.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(config, field, value)

    await session.commit()
    await session.refresh(config)

    # Invalidate cache
    email_service.invalidate_config_cache(tenant_id)

    logger.info("Updated email config for tenant: %s", tenant_id)

    return _to_response(config)


@router.delete(
    "/configs/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete email configuration",
    description="Delete email configuration for a tenant. Tenant will fall back to system defaults.",
)
async def delete_config(
    tenant_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
) -> None:
    """Delete email configuration for a tenant."""
    stmt = select(EmailConfig).where(EmailConfig.tenant_id == tenant_id)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email configuration not found for tenant: {tenant_id}",
        )

    await session.delete(config)
    await session.commit()

    # Invalidate cache
    email_service.invalidate_config_cache(tenant_id)

    logger.info("Deleted email config for tenant: %s", tenant_id)


# =============================================================================
# Testing & Validation
# =============================================================================


@router.post(
    "/configs/{tenant_id}/test",
    response_model=TestEmailResponse,
    summary="Send test email",
    description="Send a test email using tenant configuration to validate settings.",
)
async def test_config(
    tenant_id: str,
    test_request: TestEmailRequest,
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
) -> TestEmailResponse:
    """Send a test email to verify configuration."""
    import time

    start_time = time.perf_counter()

    try:
        result = await email_service.send(
            to=str(test_request.to),
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
            tenant_id=tenant_id if test_request.use_tenant_config else None,
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
        logger.exception("Test email failed for tenant %s: %s", tenant_id, e)

        return TestEmailResponse(
            success=False,
            message_id=None,
            provider="unknown",
            duration_ms=duration_ms,
            error=str(e),
            error_code="TEST_FAILED",
        )


@router.get(
    "/configs/{tenant_id}/health",
    response_model=EmailHealthResponse,
    summary="Check email provider health",
    description="Check if the email provider is healthy and can send emails.",
)
async def check_health(
    tenant_id: str,
    email_service: Annotated[EnhancedEmailService, Depends(get_enhanced_email_service)],
) -> EmailHealthResponse:
    """Check email provider health for a tenant."""
    import time

    start_time = time.perf_counter()

    try:
        is_healthy = await email_service.health_check(tenant_id)
        response_time_ms = int((time.perf_counter() - start_time) * 1000)

        from .schemas import EmailHealthCheck

        return EmailHealthResponse(
            overall_healthy=is_healthy,
            checks=[
                EmailHealthCheck(
                    provider="configured",
                    tenant_id=tenant_id,
                    healthy=is_healthy,
                    last_checked=datetime.now(UTC),
                    response_time_ms=response_time_ms,
                    error=None if is_healthy else "Health check failed",
                )
            ],
            timestamp=datetime.now(UTC),
        )

    except Exception as e:
        logger.exception("Health check failed for tenant %s: %s", tenant_id, e)

        from .schemas import EmailHealthCheck

        return EmailHealthResponse(
            overall_healthy=False,
            checks=[
                EmailHealthCheck(
                    provider="unknown",
                    tenant_id=tenant_id,
                    healthy=False,
                    last_checked=datetime.now(UTC),
                    response_time_ms=None,
                    error=str(e),
                )
            ],
            timestamp=datetime.now(UTC),
        )


# =============================================================================
# Usage Statistics
# =============================================================================


@router.get(
    "/configs/{tenant_id}/usage",
    response_model=EmailUsageStats,
    summary="Get usage statistics",
    description="Retrieve email usage statistics for billing and analytics.",
)
async def get_usage_stats(
    tenant_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    start_date: Annotated[
        datetime | None, Query(description="Start date (default: 30 days ago)")
    ] = None,
    end_date: Annotated[
        datetime | None, Query(description="End date (default: now)")
    ] = None,
) -> EmailUsageStats:
    """Get email usage statistics for a tenant."""
    # Default date range: last 30 days
    if end_date is None:
        end_date = datetime.now(UTC)
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    # Query usage logs
    stmt = (
        select(EmailUsageLog)
        .where(
            EmailUsageLog.tenant_id == tenant_id,
            EmailUsageLog.created_at >= start_date,
            EmailUsageLog.created_at <= end_date,
        )
        .order_by(EmailUsageLog.created_at.desc())
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()

    # Calculate statistics
    total_emails = len(logs)
    successful_emails = sum(1 for log in logs if log.success)
    failed_emails = total_emails - successful_emails
    success_rate = (successful_emails / total_emails * 100) if total_emails > 0 else 0.0

    # Group by provider
    emails_by_provider: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
    total_recipients = 0

    for log in logs:
        provider = log.provider
        emails_by_provider[provider] = emails_by_provider.get(provider, 0) + 1

        if log.cost_usd:
            cost_by_provider[provider] = (
                cost_by_provider.get(provider, 0.0) + log.cost_usd
            )

        total_recipients += log.recipients_count

    total_cost = sum(cost_by_provider.values())

    # Query rate limit hits from Prometheus metrics
    # Sum all rate limit hits for this tenant across all limit types
    rate_limit_hits = 0
    try:
        # Get all samples from the metric for this tenant
        # The metric is a Counter with labels: tenant_id, limit_type
        collected = list(email_rate_limit_hits_total.collect())
        if collected:
            samples = list(collected[0].samples)
            for sample in samples:
                # Sample format: ('email_rate_limit_hits_total', {'tenant_id': '...', 'limit_type': '...'}, value)
                if sample.labels.get("tenant_id") == tenant_id:
                    rate_limit_hits += int(sample.value)
    except Exception as e:
        logger.warning("Failed to query rate limit metrics: %s", e)
        # Continue with 0 if metrics query fails

    return EmailUsageStats(
        tenant_id=tenant_id,
        period_start=start_date,
        period_end=end_date,
        total_emails=total_emails,
        successful_emails=successful_emails,
        failed_emails=failed_emails,
        success_rate=round(success_rate, 2),
        emails_by_provider=emails_by_provider,
        total_cost_usd=round(total_cost, 4) if total_cost > 0 else None,
        cost_by_provider={k: round(v, 4) for k, v in cost_by_provider.items()},
        rate_limit_hits=rate_limit_hits,
        total_recipients=total_recipients,
    )


# =============================================================================
# Audit Logs
# =============================================================================


@router.get(
    "/configs/{tenant_id}/audit-logs",
    response_model=EmailAuditLogsResponse,
    summary="Get audit logs",
    description="Retrieve audit trail for sent emails (privacy-compliant with hashed recipients).",
)
async def get_audit_logs(
    tenant_id: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
) -> EmailAuditLogsResponse:
    """Get audit logs for a tenant."""
    # Count total logs
    count_stmt = (
        select(func.count())
        .select_from(EmailAuditLog)
        .where(EmailAuditLog.tenant_id == tenant_id)
    )
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Query paginated logs
    offset = (page - 1) * page_size
    stmt = (
        select(EmailAuditLog)
        .where(EmailAuditLog.tenant_id == tenant_id)
        .order_by(EmailAuditLog.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()

    return EmailAuditLogsResponse(
        logs=[EmailAuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


# =============================================================================
# Provider Information
# =============================================================================


@router.get(
    "/providers",
    response_model=ProvidersListResponse,
    summary="List available providers",
    description="Get information about all available email providers and their requirements.",
)
async def list_providers(
    _email_service: Annotated[
        EnhancedEmailService, Depends(get_enhanced_email_service)
    ],
) -> ProvidersListResponse:
    """List all available email providers."""
    providers_info = [
        ProviderInfo(
            provider_type=EmailProviderType.SMTP,
            name="SMTP",
            description="Standard SMTP/SMTPS email delivery",
            required_fields=["smtp_host", "smtp_port"],
            optional_fields=[
                "smtp_username",
                "smtp_password",
                "smtp_use_tls",
                "smtp_use_ssl",
            ],
            supports_attachments=True,
            supports_html=True,
            supports_templates=False,
            estimated_cost_per_1000=None,
        ),
        ProviderInfo(
            provider_type=EmailProviderType.AWS_SES,
            name="Amazon SES",
            description="Amazon Simple Email Service",
            required_fields=["aws_access_key", "aws_secret_key", "aws_region"],
            optional_fields=["aws_configuration_set"],
            supports_attachments=True,
            supports_html=True,
            supports_templates=True,
            estimated_cost_per_1000=0.10,
        ),
        ProviderInfo(
            provider_type=EmailProviderType.SENDGRID,
            name="SendGrid",
            description="SendGrid API v3",
            required_fields=["api_key"],
            optional_fields=[],
            supports_attachments=True,
            supports_html=True,
            supports_templates=True,
            estimated_cost_per_1000=0.15,
        ),
        ProviderInfo(
            provider_type=EmailProviderType.MAILGUN,
            name="Mailgun",
            description="Mailgun API",
            required_fields=["api_key"],
            optional_fields=["aws_region"],  # For EU vs US regions
            supports_attachments=True,
            supports_html=True,
            supports_templates=True,
            estimated_cost_per_1000=0.80,
        ),
        ProviderInfo(
            provider_type=EmailProviderType.CONSOLE,
            name="Console (Development)",
            description="Log emails to console for development",
            required_fields=[],
            optional_fields=[],
            supports_attachments=False,
            supports_html=True,
            supports_templates=False,
            estimated_cost_per_1000=None,
        ),
        ProviderInfo(
            provider_type=EmailProviderType.FILE,
            name="File (Testing)",
            description="Write emails to files for testing",
            required_fields=[],
            optional_fields=[],
            supports_attachments=True,
            supports_html=True,
            supports_templates=False,
            estimated_cost_per_1000=None,
        ),
    ]

    return ProvidersListResponse(providers=providers_info)


# =============================================================================
# Helper Functions
# =============================================================================


def _to_response(config: EmailConfig) -> EmailConfigResponse:
    """Convert EmailConfig model to response schema (mask credentials)."""
    return EmailConfigResponse(
        id=str(config.id),
        tenant_id=config.tenant_id,
        provider_type=config.provider_type,
        is_active=config.is_active,
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_username=config.smtp_username,
        smtp_use_tls=config.smtp_use_tls,
        smtp_use_ssl=config.smtp_use_ssl,
        aws_region=config.aws_region,
        aws_configuration_set=config.aws_configuration_set,
        from_email=config.from_email,
        from_name=config.from_name,
        reply_to=config.reply_to,
        rate_limit_per_minute=config.rate_limit_per_minute,
        daily_quota=config.daily_quota,
        created_at=config.created_at,
        updated_at=config.updated_at,
        encryption_version=config.encryption_version,
        # Masked credentials
        has_smtp_password=config.smtp_password is not None,
        has_aws_credentials=(
            config.aws_access_key is not None and config.aws_secret_key is not None
        ),
        has_api_key=config.api_key is not None,
    )
