"""Email configuration management API endpoints.

This module provides REST API endpoints for managing tenant email configurations:
- POST /configs/{tenant_id} - Create or update email configuration
- GET /configs/{tenant_id} - Get current configuration
- PUT /configs/{tenant_id} - Update configuration
- DELETE /configs/{tenant_id} - Delete configuration
- POST /configs/{tenant_id}/test - Test configuration
- GET /configs/{tenant_id}/health - Check provider health
- GET /configs/{tenant_id}/usage - Get usage statistics
- GET /configs/{tenant_id}/audit-logs - Get audit trail
- GET /providers - List available providers
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from example_service.features.email.dependencies import (
    EmailConfigServiceDep,
    EnhancedEmailServiceDep,
)
from example_service.features.email.models import EmailConfig

from .schemas import (
    EmailAuditLogResponse,
    EmailAuditLogsResponse,
    EmailConfigCreate,
    EmailConfigResponse,
    EmailConfigUpdate,
    EmailHealthCheck,
    EmailHealthResponse,
    EmailUsageStats,
    ProviderInfo,
    ProvidersListResponse,
    TestEmailRequest,
    TestEmailResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email-configuration"])


# Type alias for tenant_id path parameter with description
TenantIdPath = Annotated[str, "Tenant identifier"]


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
    tenant_id: TenantIdPath,
    config_data: EmailConfigCreate,
    service: EmailConfigServiceDep,
) -> EmailConfigResponse:
    """Create or update email configuration for a tenant."""
    config = await service.create_or_update_config(tenant_id, config_data)
    return _to_response(config)


@router.get(
    "/configs/{tenant_id}",
    response_model=EmailConfigResponse,
    summary="Get email configuration",
    description="Retrieve email configuration for a tenant. Credentials are masked.",
)
async def get_config(
    tenant_id: TenantIdPath,
    service: EmailConfigServiceDep,
) -> EmailConfigResponse:
    """Get email configuration for a tenant."""
    config = await service.get_config(tenant_id)

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
    tenant_id: TenantIdPath,
    config_update: EmailConfigUpdate,
    service: EmailConfigServiceDep,
) -> EmailConfigResponse:
    """Update email configuration for a tenant."""
    config = await service.update_config(tenant_id, config_update)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email configuration not found for tenant: {tenant_id}",
        )

    return _to_response(config)


@router.delete(
    "/configs/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete email configuration",
    description="Delete email configuration for a tenant. Tenant will fall back to system defaults.",
)
async def delete_config(
    tenant_id: TenantIdPath,
    service: EmailConfigServiceDep,
) -> None:
    """Delete email configuration for a tenant."""
    deleted = await service.delete_config(tenant_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email configuration not found for tenant: {tenant_id}",
        )


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
    tenant_id: TenantIdPath,
    test_request: TestEmailRequest,
    service: EmailConfigServiceDep,
) -> TestEmailResponse:
    """Send a test email to verify configuration."""
    return await service.test_config(
        tenant_id=tenant_id,
        to_email=str(test_request.to),
        use_tenant_config=test_request.use_tenant_config,
    )


@router.get(
    "/configs/{tenant_id}/health",
    response_model=EmailHealthResponse,
    summary="Check email provider health",
    description="Check if the email provider is healthy and can send emails.",
)
async def check_health(
    tenant_id: TenantIdPath,
    service: EmailConfigServiceDep,
) -> EmailHealthResponse:
    """Check email provider health for a tenant."""
    is_healthy, response_time_ms, error = await service.check_health(tenant_id)

    return EmailHealthResponse(
        overall_healthy=is_healthy,
        checks=[
            EmailHealthCheck(
                provider="configured",
                tenant_id=tenant_id,
                healthy=is_healthy,
                last_checked=datetime.now(UTC),
                response_time_ms=response_time_ms,
                error=error,
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
    tenant_id: TenantIdPath,
    service: EmailConfigServiceDep,
    start_date: Annotated[
        datetime | None, Query(description="Start date (default: 30 days ago)")
    ] = None,
    end_date: Annotated[
        datetime | None, Query(description="End date (default: now)")
    ] = None,
) -> EmailUsageStats:
    """Get email usage statistics for a tenant."""
    return await service.get_usage_stats(
        tenant_id,
        start_date=start_date,
        end_date=end_date,
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
    tenant_id: TenantIdPath,
    service: EmailConfigServiceDep,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=200, description="Items per page")] = 50,
) -> EmailAuditLogsResponse:
    """Get audit logs for a tenant."""
    result = await service.get_audit_logs(tenant_id, page=page, page_size=page_size)

    return EmailAuditLogsResponse(
        logs=[EmailAuditLogResponse.model_validate(log) for log in result.items],
        total=result.total,
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
    _email_service: EnhancedEmailServiceDep,
) -> ProvidersListResponse:
    """List all available email providers."""
    from example_service.features.email.models import EmailProviderType

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
            optional_fields=["api_endpoint"],
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
