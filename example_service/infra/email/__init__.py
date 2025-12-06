"""Email service infrastructure.

This package provides email sending capabilities with:
- Multiple backends (SMTP, Console, File, AWS SES, SendGrid, Mailgun)
- Multi-tenant configuration with per-tenant provider settings
- Jinja2 template rendering
- HTML and plaintext support
- Async delivery with all providers
- Retry logic with exponential backoff
- Queue integration via Taskiq
- Configuration caching with TTL

Basic Usage:
    from example_service.infra.email import get_email_service, EmailMessage

    # Get the basic email service (system-level config)
    email_service = get_email_service()

    # Send a simple email
    await email_service.send(
        to="user@example.com",
        subject="Welcome!",
        body="Welcome to our service.",
    )

Multi-Tenant Usage:
    from example_service.infra.email import (
        get_enhanced_email_service,
        initialize_enhanced_email_service,
    )

    # Initialize during app startup
    service = initialize_enhanced_email_service(session_factory, settings)

    # Send with tenant-specific provider config
    result = await service.send(
        to="user@example.com",
        subject="Hello!",
        body="Welcome!",
        tenant_id="tenant-123",  # Uses tenant's email provider
    )
"""

from __future__ import annotations

from . import metrics
from .client import EmailClient, get_email_client
from .enhanced_service import (
    EnhancedEmailService,
    get_enhanced_email_service,
    initialize_enhanced_email_service,
)
from .providers import (
    BaseEmailProvider,
    EmailDeliveryResult,
    EmailProvider,
    EmailProviderFactory,
    ProviderCapabilities,
    get_provider_factory,
    initialize_provider_factory,
)
from .resolver import (
    EmailConfigResolver,
    ResolvedEmailConfig,
    get_email_config_resolver,
    initialize_email_config_resolver,
)
from .schemas import (
    EmailAttachment,
    EmailMessage,
    EmailPriority,
    EmailResult,
    EmailStatus,
)
from .service import EmailService, get_email_service
from .templates import (
    EmailTemplateRenderer,
    TemplateNotFoundError,
    get_template_renderer,
)

__all__ = [
    # Provider System
    "BaseEmailProvider",
    # Schemas
    "EmailAttachment",
    # Basic Client
    "EmailClient",
    # Configuration Resolver
    "EmailConfigResolver",
    "EmailDeliveryResult",
    "EmailMessage",
    "EmailPriority",
    "EmailProvider",
    "EmailProviderFactory",
    "EmailResult",
    # Basic Service
    "EmailService",
    "EmailStatus",
    # Templates
    "EmailTemplateRenderer",
    # Enhanced Service (Multi-tenant)
    "EnhancedEmailService",
    "ProviderCapabilities",
    "ResolvedEmailConfig",
    "TemplateNotFoundError",
    "get_email_client",
    "get_email_config_resolver",
    "get_email_service",
    "get_enhanced_email_service",
    "get_provider_factory",
    "get_template_renderer",
    "initialize_email_config_resolver",
    "initialize_enhanced_email_service",
    "initialize_provider_factory",
    # Metrics (Phase 3)
    "metrics",
]
