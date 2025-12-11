"""Console email provider for development.

Logs emails to the console instead of sending them.
Useful for local development and debugging.

Usage:
    config = ResolvedEmailConfig(provider_type=EmailProviderType.CONSOLE, ...)
    provider = ConsoleProvider(config)
    result = await provider.send(message)  # Logs to console
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
import uuid

from .base import BaseEmailProvider, EmailDeliveryResult, ProviderCapabilities

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


class ConsoleProvider(BaseEmailProvider):
    """Console email provider for development.

    Instead of sending emails, this provider logs them to the console
    with formatted output. Always succeeds (no real delivery).

    Example:
        provider = ConsoleProvider(config)
        result = await provider.send(message)
        # Email details printed to console
        assert result.success  # Always true
    """

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize console provider.

        Args:
            config: Resolved email configuration
        """
        super().__init__(config)
        logger.info(
            "Console email provider initialized (development mode)",
            extra={"tenant_id": config.tenant_id},
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "console"

    def _default_capabilities(self) -> ProviderCapabilities:
        """Console supports everything (for testing purposes)."""
        return ProviderCapabilities(
            supports_attachments=True,
            supports_html=True,
            supports_templates=False,
            supports_tracking=False,
            supports_scheduling=False,
            supports_batch=True,
            max_recipients=0,  # Unlimited
            max_attachment_size_mb=100.0,
        )

    async def _do_send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Log email to console.

        Args:
            message: Email message to log

        Returns:
            EmailDeliveryResult (always success)
        """
        message_id = f"console-{uuid.uuid4()}"

        # Get sender info
        from_email = message.from_email or self._config.from_email
        from_name = message.from_name or self._config.from_name

        # Pretty print the email
        separator = "=" * 60
        output_lines = [
            "",
            separator,
            "EMAIL (Console Backend - Development Mode)",
            separator,
            f"Message-ID: {message_id}",
            f"From: {from_name} <{from_email}>" if from_name else f"From: {from_email}",
            f"To: {', '.join(message.to)}",
        ]

        if message.cc:
            output_lines.append(f"Cc: {', '.join(message.cc)}")
        if message.bcc:
            output_lines.append(f"Bcc: {', '.join(message.bcc)}")
        if message.reply_to:
            output_lines.append(f"Reply-To: {message.reply_to}")

        output_lines.extend([
            f"Subject: {message.subject}",
            f"Priority: {message.priority.value}",
        ])

        if message.tags:
            output_lines.append(f"Tags: {', '.join(message.tags)}")

        if message.attachments:
            attachment_names = [a.filename for a in message.attachments]
            output_lines.append(f"Attachments: {', '.join(attachment_names)}")

        output_lines.append(separator)

        # Body content
        if message.body_text:
            output_lines.append("TEXT BODY:")
            text_preview = message.body_text[:500]
            output_lines.append(text_preview)
            if len(message.body_text) > 500:
                output_lines.append(f"... ({len(message.body_text) - 500} more characters)")

        if message.body_html:
            output_lines.append("")
            output_lines.append("HTML BODY:")
            html_preview = message.body_html[:500]
            output_lines.append(html_preview)
            if len(message.body_html) > 500:
                output_lines.append(f"... ({len(message.body_html) - 500} more characters)")

        output_lines.extend([separator, ""])

        # Print to console

        return EmailDeliveryResult.success_result(
            message_id=message_id,
            provider=self.provider_name,
            recipients=message.all_recipients,
            metadata={
                "mode": "development",
                "tenant_id": self._config.tenant_id,
            },
        )

    async def _do_health_check(self) -> bool:
        """Console is always healthy.

        Returns:
            Always True
        """
        return True


__all__ = ["ConsoleProvider"]
