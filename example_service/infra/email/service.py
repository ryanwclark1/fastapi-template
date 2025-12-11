"""High-level email service with template support and queue integration.

Provides a simple interface for sending emails with:
- Template rendering
- Queue-based async delivery
- Batch sending
- Rate limiting
"""

from __future__ import annotations

from functools import lru_cache
import logging
from typing import TYPE_CHECKING, Any

from .client import EmailClient, get_email_client, get_email_settings
from .schemas import (
    EmailAttachment,
    EmailMessage,
    EmailPriority,
    EmailResult,
)
from .templates import (
    EmailTemplateRenderer,
    TemplateNotFoundError,
    get_template_renderer,
)

if TYPE_CHECKING:
    from example_service.core.settings.email import EmailSettings

logger = logging.getLogger(__name__)


class EmailService:
    """High-level email service.

    Provides a simple interface for sending emails with template support
    and optional background delivery via task queue.

    Example:
        service = get_email_service()

        # Simple email
        await service.send(
            to="user@example.com",
            subject="Hello!",
            body="Welcome to our service.",
        )

        # Template email
        await service.send_template(
            to="user@example.com",
            template="welcome",
            context={"user_name": "John"},
        )

        # Queue for background delivery
        await service.send_async(
            to="user@example.com",
            subject="Hello!",
            body="Welcome to our service.",
        )
    """

    def __init__(
        self,
        client: EmailClient,
        renderer: EmailTemplateRenderer,
        settings: EmailSettings,
    ) -> None:
        """Initialize email service.

        Args:
            client: Email client for sending.
            renderer: Template renderer.
            settings: Email settings.
        """
        self.client = client
        self.renderer = renderer
        self.settings = settings

        logger.info(
            "Email service initialized",
            extra={
                "enabled": settings.enabled,
                "backend": settings.backend,
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
    ) -> EmailResult:
        """Send an email directly.

        Args:
            to: Recipient email(s).
            subject: Email subject.
            body: Plain text body.
            body_html: HTML body.
            cc: CC recipients.
            bcc: BCC recipients.
            reply_to: Reply-to address.
            from_email: Sender email.
            from_name: Sender name.
            attachments: File attachments.
            priority: Email priority.
            headers: Additional headers.
            tags: Tags for tracking.
            metadata: Custom metadata.

        Returns:
            EmailResult with delivery status.
        """
        # Normalize recipients to list
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

        return await self.client.send(message)

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
    ) -> EmailResult:
        """Send an email using a template.

        Args:
            to: Recipient email(s).
            template: Template name (without extension).
            context: Template context variables.
            subject: Email subject (uses template subject if not provided).
            cc: CC recipients.
            bcc: BCC recipients.
            reply_to: Reply-to address.
            from_email: Sender email.
            from_name: Sender name.
            attachments: File attachments.
            priority: Email priority.
            headers: Additional headers.
            tags: Tags for tracking.
            metadata: Custom metadata.

        Returns:
            EmailResult with delivery status.

        Raises:
            TemplateNotFoundError: If template doesn't exist.
        """
        # Merge context with recipient info
        full_context = context or {}
        recipients = [to] if isinstance(to, str) else list(to)
        if recipients:
            full_context.setdefault("user_email", recipients[0])

        # Render template
        try:
            html_content, text_content = self.renderer.render(template, **full_context)
        except TemplateNotFoundError:
            logger.exception(f"Email template not found: {template}")
            raise

        # Extract subject from context if not provided
        email_subject = subject or full_context.get("subject", f"Email: {template}")

        # Create message
        message = EmailMessage(
            to=recipients,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to,
            from_email=from_email,
            from_name=from_name,
            subject=email_subject,
            body_text=text_content,
            body_html=html_content,
            attachments=attachments or [],
            priority=priority,
            headers=headers or {},
            tags=tags or [f"template:{template}"],
            metadata=metadata or {},
            template_name=template,
        )

        return await self.client.send(message)

    async def send_async(
        self,
        to: str | list[str],
        subject: str,
        body: str | None = None,
        body_html: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Queue an email for background delivery.

        Args:
            to: Recipient email(s).
            subject: Email subject.
            body: Plain text body.
            body_html: HTML body.
            **kwargs: Additional email options.

        Returns:
            Task ID for tracking.
        """
        from example_service.workers.notifications.tasks import send_email_task

        # Normalize recipients
        recipients = [to] if isinstance(to, str) else list(to)

        # Queue the task
        task = await send_email_task.kiq(
            to=recipients,
            subject=subject,
            body=body,
            body_html=body_html,
            **kwargs,
        )

        logger.info(
            "Email queued for background delivery",
            extra={
                "task_id": task.task_id,
                "to": recipients,
                "subject": subject[:50],
            },
        )

        return task.task_id # type: ignore[no-any-return]

    async def send_template_async(
        self,
        to: str | list[str],
        template: str,
        context: dict[str, Any] | None = None,
        subject: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Queue a template email for background delivery.

        Args:
            to: Recipient email(s).
            template: Template name.
            context: Template context.
            subject: Email subject override.
            **kwargs: Additional email options.

        Returns:
            Task ID for tracking.
        """
        from example_service.workers.notifications.tasks import send_template_email_task

        # Normalize recipients
        recipients = [to] if isinstance(to, str) else list(to)

        # Queue the task
        task = await send_template_email_task.kiq(
            to=recipients,
            template=template,
            context=context or {},
            subject=subject,
            **kwargs,
        )

        logger.info(
            "Template email queued for background delivery",
            extra={
                "task_id": task.task_id,
                "to": recipients,
                "template": template,
            },
        )

        return task.task_id # type: ignore[no-any-return]

    async def send_batch(
        self,
        messages: list[EmailMessage],
    ) -> list[EmailResult]:
        """Send multiple emails.

        Args:
            messages: List of email messages to send.

        Returns:
            List of EmailResult for each message.
        """
        results = []
        for message in messages:
            result = await self.client.send(message)
            results.append(result)
        return results

    async def health_check(self) -> bool:
        """Check if email service is healthy.

        Returns:
            True if service is operational.
        """
        return await self.client.health_check()

    def template_exists(self, template_name: str) -> bool:
        """Check if a template exists.

        Args:
            template_name: Template name to check.

        Returns:
            True if template exists.
        """
        return self.renderer.template_exists(template_name)

    def list_templates(self) -> list[str]:
        """List available email templates.

        Returns:
            List of template names.
        """
        return self.renderer.list_templates()


@lru_cache(maxsize=1)
def get_email_service(settings: EmailSettings | None = None) -> EmailService:
    """Get cached email service instance.

    Args:
        settings: Optional settings override.

    Returns:
        Configured EmailService instance.
    """
    if settings is None:
        settings = get_email_settings()

    client = get_email_client(settings)
    renderer = get_template_renderer(settings)

    return EmailService(client, renderer, settings)


# Convenience function for simple sends
async def send_email(
    to: str | list[str],
    subject: str,
    body: str | None = None,
    body_html: str | None = None,
    **kwargs: Any,
) -> EmailResult:
    """Convenience function to send an email.

    Args:
        to: Recipient email(s).
        subject: Email subject.
        body: Plain text body.
        body_html: HTML body.
        **kwargs: Additional options.

    Returns:
        EmailResult with delivery status.

    Example:
        from example_service.infra.email import send_email

        result = await send_email(
            to="user@example.com",
            subject="Welcome!",
            body="Hello, welcome to our service.",
        )
    """
    service = get_email_service()
    return await service.send(to, subject, body, body_html, **kwargs)


async def send_template_email(
    to: str | list[str],
    template: str,
    context: dict[str, Any] | None = None,
    subject: str | None = None,
    **kwargs: Any,
) -> EmailResult:
    """Convenience function to send a template email.

    Args:
        to: Recipient email(s).
        template: Template name.
        context: Template context.
        subject: Subject override.
        **kwargs: Additional options.

    Returns:
        EmailResult with delivery status.

    Example:
        from example_service.infra.email import send_template_email

        result = await send_template_email(
            to="user@example.com",
            template="welcome",
            context={"user_name": "John"},
        )
    """
    service = get_email_service()
    return await service.send_template(to, template, context, subject, **kwargs)
