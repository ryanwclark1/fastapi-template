"""SMTP email provider using aiosmtplib.

Production-ready SMTP provider with:
- Native async support (aiosmtplib)
- TLS/SSL support
- Authentication support
- Automatic retry with exponential backoff
- Comprehensive error handling

Usage:
    from example_service.infra.email.providers import get_provider_factory

    factory = get_provider_factory()
    provider = factory.get_provider(config)  # config.provider_type == SMTP
    result = await provider.send(message)
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import ssl
from typing import TYPE_CHECKING
import uuid

from example_service.utils.retry import retry

from .base import BaseEmailProvider, EmailDeliveryResult, ProviderCapabilities

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


class SMTPProvider(BaseEmailProvider):
    """SMTP email provider using native async aiosmtplib.

    Supports:
    - STARTTLS (port 587)
    - Implicit SSL/TLS (port 465)
    - Plain text (port 25, not recommended)
    - Authentication (LOGIN, PLAIN)
    - Full MIME attachments
    - Priority headers

    Example:
        config = ResolvedEmailConfig(
            provider_type=EmailProviderType.SMTP,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user",
            smtp_password="pass",
            smtp_use_tls=True,
        )
        provider = SMTPProvider(config)
        result = await provider.send(message)
    """

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize SMTP provider.

        Args:
            config: Resolved email configuration with SMTP settings
        """
        super().__init__(config)

        # Validate SMTP-specific config
        if not config.smtp_host:
            msg = "SMTP host is required for SMTP provider"
            raise ValueError(msg)

        self._host = config.smtp_host
        self._port = config.smtp_port or 587
        self._username = config.smtp_username
        self._password = config.smtp_password
        self._use_tls = config.smtp_use_tls if config.smtp_use_tls is not None else True
        self._use_ssl = config.smtp_use_ssl if config.smtp_use_ssl is not None else False

        logger.info(
            "SMTP provider initialized",
            extra={
                "host": self._host,
                "port": self._port,
                "use_tls": self._use_tls,
                "use_ssl": self._use_ssl,
                "tenant_id": config.tenant_id,
            },
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "smtp"

    def _default_capabilities(self) -> ProviderCapabilities:
        """SMTP capabilities."""
        return ProviderCapabilities(
            supports_attachments=True,
            supports_html=True,
            supports_templates=False,  # No native templates
            supports_tracking=False,  # No native tracking
            supports_scheduling=False,
            supports_batch=True,
            max_recipients=100,  # Reasonable default
            max_attachment_size_mb=25.0,
        )

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create SSL context for TLS/SSL connections.

        Returns:
            SSLContext or None if no TLS/SSL
        """
        if not (self._use_tls or self._use_ssl):
            return None

        context = ssl.create_default_context()
        # Allow customization via config_json if needed
        if self._config.config_json and self._config.config_json.get("validate_certs") is False:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        return context

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(OSError, ConnectionError, TimeoutError),
    )
    async def _do_send(  # type: ignore[override]  # @retry changes return type
        self, message: EmailMessage
    ) -> EmailDeliveryResult:
        """Send email via SMTP.

        Args:
            message: Email message to send

        Returns:
            EmailDeliveryResult with delivery status
        """
        import aiosmtplib

        try:
            # Build MIME message
            mime_message = self._build_mime_message(message)
            message_id = mime_message["Message-ID"]

            # Create SMTP client
            smtp = aiosmtplib.SMTP(
                hostname=self._host,
                port=self._port,
                use_tls=self._use_ssl,  # Implicit TLS
                start_tls=self._use_tls,  # STARTTLS
                tls_context=self._create_ssl_context(),
                timeout=30.0,
            )

            async with smtp:
                # Authenticate if credentials provided
                if self._username and self._password:
                    await smtp.login(self._username, self._password)

                # Send the message
                errors, _response = await smtp.send_message(mime_message)

            # Process response
            recipients_accepted = [r for r in message.all_recipients if r not in errors]
            recipients_rejected = list(errors.keys()) if errors else []

            if recipients_rejected:
                logger.warning(
                    "Some SMTP recipients rejected",
                    extra={
                        "message_id": message_id,
                        "rejected": recipients_rejected,
                        "errors": {k: str(v) for k, v in errors.items()},
                    },
                )

            return EmailDeliveryResult(
                success=len(recipients_accepted) > 0,
                message_id=message_id,
                provider=self.provider_name,
                recipients_accepted=recipients_accepted,
                recipients_rejected=recipients_rejected,
                metadata={
                    "host": self._host,
                    "port": self._port,
                },
            )

        except aiosmtplib.SMTPAuthenticationError as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"SMTP authentication failed: {e}",
                error_code="AUTH_FAILED",
                recipients_rejected=message.all_recipients,
            )
        except aiosmtplib.SMTPRecipientsRefused as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"All recipients refused: {e}",
                error_code="RECIPIENTS_REFUSED",
                recipients_rejected=message.all_recipients,
            )
        except aiosmtplib.SMTPConnectError as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"SMTP connection failed: {e}",
                error_code="CONNECTION_ERROR",
            )
        except aiosmtplib.SMTPException as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"SMTP error: {e}",
                error_code="SMTP_ERROR",
            )

    async def _do_health_check(self) -> bool:
        """Check SMTP server connectivity.

        Returns:
            True if connection successful
        """
        import aiosmtplib

        try:
            smtp = aiosmtplib.SMTP(
                hostname=self._host,
                port=self._port,
                use_tls=self._use_ssl,
                start_tls=self._use_tls,
                tls_context=self._create_ssl_context(),
                timeout=5.0,
            )
            await smtp.connect()
            await smtp.quit()
            return True
        except Exception as e:
            logger.debug(f"SMTP health check failed: {e}")
            return False

    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Build MIME message from EmailMessage.

        Args:
            message: Email message

        Returns:
            MIMEMultipart ready for sending
        """
        # Create multipart message
        mime_msg = MIMEMultipart("mixed")

        # Set headers
        from_email = message.from_email or self._config.from_email or "noreply@example.com"
        from_name = message.from_name or self._config.from_name
        mime_msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        mime_msg["To"] = ", ".join(message.to)

        if message.cc:
            mime_msg["Cc"] = ", ".join(message.cc)

        mime_msg["Subject"] = message.subject
        mime_msg["Message-ID"] = f"<{uuid.uuid4()}@{self._host}>"
        mime_msg["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")

        if message.reply_to:
            mime_msg["Reply-To"] = message.reply_to
        elif self._config.reply_to:
            mime_msg["Reply-To"] = self._config.reply_to

        # Set priority
        if message.priority.value == "high":
            mime_msg["X-Priority"] = "1"
            mime_msg["X-MSMail-Priority"] = "High"
        elif message.priority.value == "low":
            mime_msg["X-Priority"] = "5"
            mime_msg["X-MSMail-Priority"] = "Low"

        # Add custom headers
        for key, value in message.headers.items():
            mime_msg[key] = value

        # Create alternative part for text/html
        if message.body_text and message.body_html:
            alt_part = MIMEMultipart("alternative")
            alt_part.attach(MIMEText(message.body_text, "plain", "utf-8"))
            alt_part.attach(MIMEText(message.body_html, "html", "utf-8"))
            mime_msg.attach(alt_part)
        elif message.body_html:
            mime_msg.attach(MIMEText(message.body_html, "html", "utf-8"))
        elif message.body_text:
            mime_msg.attach(MIMEText(message.body_text, "plain", "utf-8"))

        # Add attachments
        for attachment in message.attachments:
            content = attachment.content
            if content is None and attachment.path:
                with open(attachment.path, "rb") as f:
                    content = f.read()

            if content is None:
                logger.warning(f"Skipping attachment {attachment.filename}: no content")
                continue

            part = MIMEApplication(content, Name=attachment.filename)
            part["Content-Disposition"] = f'attachment; filename="{attachment.filename}"'
            if attachment.content_id:
                part["Content-ID"] = f"<{attachment.content_id}>"
            mime_msg.attach(part)

        return mime_msg


__all__ = ["SMTPProvider"]
