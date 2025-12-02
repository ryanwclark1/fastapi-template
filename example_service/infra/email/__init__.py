"""Email service infrastructure.

This package provides email sending capabilities with:
- Multiple backends (SMTP, console, file)
- Jinja2 template rendering
- HTML and plaintext support
- Async SMTP delivery
- Retry logic with exponential backoff
- Queue integration via Taskiq

Usage:
    from example_service.infra.email import get_email_service, EmailMessage

    # Get the email service
    email_service = get_email_service()

    # Send a simple email
    await email_service.send(
        to="user@example.com",
        subject="Welcome!",
        body="Welcome to our service.",
    )

    # Send with template
    await email_service.send_template(
        to="user@example.com",
        template="welcome",
        context={"user_name": "John"},
    )
"""

from __future__ import annotations

from .client import EmailClient, get_email_client
from .schemas import EmailAttachment, EmailMessage, EmailResult
from .service import EmailService, get_email_service
from .templates import EmailTemplateRenderer, get_template_renderer

__all__ = [
    # Client
    "EmailClient",
    "get_email_client",
    # Service
    "EmailService",
    "get_email_service",
    # Templates
    "EmailTemplateRenderer",
    "get_template_renderer",
    # Schemas
    "EmailMessage",
    "EmailAttachment",
    "EmailResult",
]
