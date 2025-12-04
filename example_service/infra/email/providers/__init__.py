"""Email provider implementations.

This package contains all email provider implementations:
- SMTP: Standard SMTP/SMTPS delivery (aiosmtplib)
- Console: Log emails to console (development)
- File: Write emails to files (testing)
- AWS SES: Amazon Simple Email Service
- SendGrid: SendGrid API
- Mailgun: Mailgun API

Usage:
    from example_service.infra.email.providers import (
        EmailProviderFactory,
        get_provider_factory,
    )

    factory = get_provider_factory()
    provider = factory.get_provider("smtp", config)
    result = await provider.send(message)

Direct provider access:
    from example_service.infra.email.providers import SMTPProvider, SendGridProvider
"""

from .base import (
    BaseEmailProvider,
    EmailDeliveryResult,
    EmailProvider,
    ProviderCapabilities,
)
from .console import ConsoleProvider
from .factory import EmailProviderFactory, get_provider_factory, initialize_provider_factory
from .file import FileProvider
from .mailgun import MailgunProvider
from .sendgrid import SendGridProvider
from .smtp import SMTPProvider

# Optional providers (may not be installed)
try:
    from .ses import SESProvider

    _SES_AVAILABLE = True
except ImportError:
    SESProvider = None  # type: ignore[assignment, misc]
    _SES_AVAILABLE = False

__all__ = [
    "BaseEmailProvider",
    "ConsoleProvider",
    "EmailDeliveryResult",
    # Protocol and base class
    "EmailProvider",
    # Factory
    "EmailProviderFactory",
    "FileProvider",
    "MailgunProvider",
    "ProviderCapabilities",
    "SESProvider",
    # Providers
    "SMTPProvider",
    "SendGridProvider",
    "get_provider_factory",
    "initialize_provider_factory",
]
