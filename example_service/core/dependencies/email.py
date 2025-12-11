"""Email service dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing the
email infrastructure, including the basic email service, enhanced
multi-tenant service, and template renderer.

Usage:
    from example_service.core.dependencies.email import (
        EmailServiceDep,
        EnhancedEmailServiceDep,
        TemplateRendererDep,
    )

    @router.post("/send-welcome")
    async def send_welcome_email(
        user: UserCreate,
        email: EmailServiceDep,
    ):
        await email.send(
            to=user.email,
            subject="Welcome!",
            body="Welcome to our service.",
        )
        return {"status": "sent"}

    @router.post("/send-notification")
    async def send_notification(
        data: NotificationData,
        email: EnhancedEmailServiceDep,
        tenant_id: str = Header(...),
    ):
        # Uses tenant-specific email provider configuration
        result = await email.send(
            to=data.recipient,
            subject=data.subject,
            body=data.body,
            tenant_id=tenant_id,
        )
        return {"status": result.status}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, status

if TYPE_CHECKING:
    from example_service.infra.email import (
        EmailService,
        EmailTemplateRenderer,
        EnhancedEmailService,
    )


def get_email_service_dep() -> EmailService:
    """Get the basic email service instance.

    This is a thin wrapper that retrieves the email service singleton.
    The import is deferred to runtime to avoid circular dependencies.

    Returns:
        EmailService: The basic email service instance.
    """
    from example_service.infra.email import get_email_service

    return get_email_service()


def get_enhanced_email_service_dep() -> EnhancedEmailService | None:
    """Get the enhanced multi-tenant email service instance.

    The enhanced service supports per-tenant email provider configuration.
    Returns None if not initialized (requires database session factory).

    Note: The infra.email.get_enhanced_email_service() raises RuntimeError
    if the service hasn't been initialized. This dependency catches that
    exception and returns None to allow graceful degradation.

    Returns:
        EnhancedEmailService | None: The enhanced service, or None if not initialized.
    """
    from example_service.infra.email import get_enhanced_email_service

    try:
        return get_enhanced_email_service()
    except RuntimeError:
        return None


def get_template_renderer_dep() -> EmailTemplateRenderer:
    """Get the email template renderer instance.

    Returns:
        EmailTemplateRenderer: The Jinja2 template renderer for emails.
    """
    from example_service.infra.email import get_template_renderer

    return get_template_renderer()


async def require_email_service(
    service: Annotated[EmailService, Depends(get_email_service_dep)],
) -> EmailService:
    """Dependency that provides the basic email service.

    The basic email service is always available (uses system-level config).

    Args:
        service: Injected service from get_email_service_dep

    Returns:
        EmailService: The email service instance
    """
    return service


async def require_enhanced_email_service(
    service: Annotated[
        EnhancedEmailService | None, Depends(get_enhanced_email_service_dep),
    ],
) -> EnhancedEmailService:
    """Dependency that requires enhanced email service to be available.

    Use this when you need multi-tenant email provider support.
    Raises HTTP 503 if the enhanced service is not initialized.

    Args:
        service: Injected service from get_enhanced_email_service_dep

    Returns:
        EnhancedEmailService: The enhanced email service instance

    Raises:
        HTTPException: 503 Service Unavailable if service is not initialized
    """
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enhanced_email_unavailable",
                "message": "Enhanced email service is not initialized",
            },
        )
    return service


async def optional_enhanced_email_service(
    service: Annotated[
        EnhancedEmailService | None, Depends(get_enhanced_email_service_dep),
    ],
) -> EnhancedEmailService | None:
    """Dependency that optionally provides enhanced email service.

    Use this when multi-tenant email is optional. Falls back to basic
    email service if enhanced is not available.

    Args:
        service: Injected service from get_enhanced_email_service_dep

    Returns:
        EnhancedEmailService | None: The service if available, None otherwise
    """
    return service


async def require_template_renderer(
    renderer: Annotated[EmailTemplateRenderer, Depends(get_template_renderer_dep)],
) -> EmailTemplateRenderer:
    """Dependency that provides the email template renderer.

    Args:
        renderer: Injected renderer from get_template_renderer_dep

    Returns:
        EmailTemplateRenderer: The template renderer instance
    """
    return renderer


# Type aliases for cleaner route signatures
# Use lazy import to avoid circular dependencies
def _get_email_types() -> tuple[type, type, type]:
    """Lazy import of email service types to avoid circular imports."""
    from example_service.infra.email import (
        EmailService,
        EmailTemplateRenderer,
        EnhancedEmailService,
    )

    return EmailService, EmailTemplateRenderer, EnhancedEmailService


_EmailService, _EmailTemplateRenderer, _EnhancedEmailService = _get_email_types()

EmailServiceDep = Annotated[_EmailService, Depends(require_email_service)]
"""Basic email service dependency.

Uses system-level email configuration. Always available.

Example:
    @router.post("/send")
    async def send(data: EmailData, email: EmailServiceDep):
        await email.send(to=data.to, subject=data.subject, body=data.body)
"""

EnhancedEmailServiceDep = Annotated[
    _EnhancedEmailService, Depends(require_enhanced_email_service),
]
"""Enhanced multi-tenant email service dependency.

Uses per-tenant email provider configuration. Raises 503 if not initialized.

Example:
    @router.post("/send")
    async def send(data: EmailData, email: EnhancedEmailServiceDep, tenant_id: str):
        result = await email.send(
            to=data.to,
            subject=data.subject,
            body=data.body,
            tenant_id=tenant_id,
        )
"""

OptionalEnhancedEmailService = Annotated[
    _EnhancedEmailService | None, Depends(optional_enhanced_email_service),
]
"""Optional enhanced email service dependency.

Returns None if enhanced email is not initialized.

Example:
    @router.post("/send")
    async def send(
        data: EmailData,
        email: EmailServiceDep,
        enhanced: OptionalEnhancedEmailService,
        tenant_id: str | None = None,
    ):
        if enhanced and tenant_id:
            await enhanced.send(..., tenant_id=tenant_id)
        else:
            await email.send(...)
"""

TemplateRendererDep = Annotated[
    _EmailTemplateRenderer, Depends(require_template_renderer),
]
"""Email template renderer dependency.

Example:
    @router.post("/send-templated")
    async def send_templated(
        data: dict,
        renderer: TemplateRendererDep,
        email: EmailServiceDep,
    ):
        html = await renderer.render("welcome.html", data)
        await email.send(to=data["email"], subject="Welcome", html_body=html)
"""


__all__ = [
    "EmailServiceDep",
    "EnhancedEmailServiceDep",
    "OptionalEnhancedEmailService",
    "TemplateRendererDep",
    "get_email_service_dep",
    "get_enhanced_email_service_dep",
    "get_template_renderer_dep",
    "optional_enhanced_email_service",
    "require_email_service",
    "require_enhanced_email_service",
    "require_template_renderer",
]
