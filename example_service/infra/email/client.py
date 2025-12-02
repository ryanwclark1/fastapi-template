"""Email client for SMTP and alternative backends.

Provides low-level email sending with support for multiple backends:
- SMTP: Production email delivery via aiosmtplib
- Console: Log emails to console (development)
- File: Write emails to files (testing)
"""

from __future__ import annotations

import json
import logging
import ssl
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from pathlib import Path

from example_service.core.settings.email import EmailSettings
from example_service.utils.retry import retry

from .schemas import EmailMessage, EmailResult, EmailStatus

logger = logging.getLogger(__name__)


class BaseEmailClient(ABC):
    """Abstract base class for email clients."""

    @abstractmethod
    async def send(self, message: EmailMessage) -> EmailResult:
        """Send an email message.

        Args:
            message: The email message to send.

        Returns:
            EmailResult with delivery status.
        """
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the email backend."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the email backend."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the email backend is healthy."""
        ...


class SMTPClient(BaseEmailClient):
    """SMTP email client using aiosmtplib.

    Supports TLS, SSL, and authentication.

    Example:
        client = SMTPClient(settings)
        await client.connect()
        result = await client.send(message)
        await client.disconnect()
    """

    def __init__(self, settings: EmailSettings) -> None:
        """Initialize SMTP client.

        Args:
            settings: Email settings with SMTP configuration.
        """
        self.settings = settings
        self._client = None

        logger.info(
            "SMTP client initialized",
            extra={
                "host": settings.smtp_host,
                "port": settings.smtp_port,
                "use_tls": settings.use_tls,
                "use_ssl": settings.use_ssl,
            },
        )

    async def connect(self) -> None:
        """Establish SMTP connection."""
        # aiosmtplib creates connections per-send, so we don't maintain persistent connection
        pass

    async def disconnect(self) -> None:
        """Close SMTP connection."""
        # Cleanup if needed
        self._client = None

    async def health_check(self) -> bool:
        """Check SMTP server connectivity."""
        try:
            import aiosmtplib

            # Create SSL context if needed
            tls_context = None
            if self.settings.use_tls or self.settings.use_ssl:
                tls_context = ssl.create_default_context()
                if not self.settings.validate_certs:
                    tls_context.check_hostname = False
                    tls_context.verify_mode = ssl.CERT_NONE

            # Try to connect and immediately disconnect
            smtp = aiosmtplib.SMTP(
                hostname=self.settings.smtp_host,
                port=self.settings.smtp_port,
                use_tls=self.settings.use_ssl,  # Implicit TLS
                start_tls=self.settings.use_tls,  # STARTTLS
                tls_context=tls_context,
                timeout=5.0,
            )
            await smtp.connect()
            await smtp.quit()
            return True
        except Exception as e:
            logger.warning(f"SMTP health check failed: {e}")
            return False

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(OSError, ConnectionError, TimeoutError),
    )
    async def send(self, message: EmailMessage) -> EmailResult:
        """Send email via SMTP.

        Args:
            message: The email message to send.

        Returns:
            EmailResult with delivery status.
        """
        import aiosmtplib

        try:
            # Build MIME message
            mime_message = self._build_mime_message(message)

            # Create SSL context if needed
            tls_context = None
            if self.settings.use_tls or self.settings.use_ssl:
                tls_context = ssl.create_default_context()
                if not self.settings.validate_certs:
                    tls_context.check_hostname = False
                    tls_context.verify_mode = ssl.CERT_NONE

            # Create SMTP client
            smtp = aiosmtplib.SMTP(
                hostname=self.settings.smtp_host,
                port=self.settings.smtp_port,
                use_tls=self.settings.use_ssl,  # Implicit TLS
                start_tls=self.settings.use_tls,  # STARTTLS
                tls_context=tls_context,
                timeout=self.settings.timeout,
            )

            async with smtp:
                # Authenticate if credentials provided
                if self.settings.requires_auth:
                    await smtp.login(
                        self.settings.smtp_username,
                        self.settings.smtp_password.get_secret_value(),
                    )

                # Send the message
                errors, response = await smtp.send_message(mime_message)

            # Process response
            message_id = mime_message["Message-ID"]
            recipients_accepted = [r for r in message.all_recipients if r not in errors]
            recipients_rejected = list(errors.keys()) if errors else []

            if recipients_rejected:
                logger.warning(
                    "Some recipients rejected",
                    extra={
                        "message_id": message_id,
                        "rejected": recipients_rejected,
                        "errors": errors,
                    },
                )

            logger.info(
                "Email sent successfully",
                extra={
                    "message_id": message_id,
                    "recipients": len(recipients_accepted),
                    "subject": message.subject[:50],
                },
            )

            return EmailResult(
                success=len(recipients_accepted) > 0,
                message_id=message_id,
                status=EmailStatus.SENT,
                recipients_accepted=recipients_accepted,
                recipients_rejected=recipients_rejected,
                backend="smtp",
            )

        except aiosmtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return EmailResult.failure_result(
                error=str(e),
                error_code="AUTH_FAILED",
                backend="smtp",
            )
        except aiosmtplib.SMTPRecipientsRefused as e:
            logger.error(f"All recipients refused: {e}")
            return EmailResult.failure_result(
                error=str(e),
                error_code="RECIPIENTS_REFUSED",
                backend="smtp",
            )
        except aiosmtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return EmailResult.failure_result(
                error=str(e),
                error_code="SMTP_ERROR",
                backend="smtp",
            )
        except Exception as e:
            logger.exception(f"Unexpected error sending email: {e}")
            return EmailResult.failure_result(
                error=str(e),
                error_code="UNEXPECTED_ERROR",
                backend="smtp",
            )

    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Build MIME message from EmailMessage.

        Args:
            message: The email message.

        Returns:
            MIMEMultipart message ready for sending.
        """
        # Create multipart message
        mime_msg = MIMEMultipart("mixed")

        # Set headers
        from_email = message.from_email or self.settings.default_from_email
        from_name = message.from_name or self.settings.default_from_name
        mime_msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        mime_msg["To"] = ", ".join(message.to)
        if message.cc:
            mime_msg["Cc"] = ", ".join(message.cc)
        mime_msg["Subject"] = message.subject
        mime_msg["Message-ID"] = f"<{uuid.uuid4()}@{self.settings.smtp_host}>"
        mime_msg["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")

        if message.reply_to:
            mime_msg["Reply-To"] = message.reply_to

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

            part = MIMEApplication(content, Name=attachment.filename)
            part["Content-Disposition"] = f'attachment; filename="{attachment.filename}"'
            if attachment.content_id:
                part["Content-ID"] = f"<{attachment.content_id}>"
            mime_msg.attach(part)

        return mime_msg


class ConsoleClient(BaseEmailClient):
    """Console email client for development.

    Logs emails to the console instead of sending them.
    """

    def __init__(self, settings: EmailSettings) -> None:
        """Initialize console client."""
        self.settings = settings
        logger.info("Console email client initialized (development mode)")

    async def connect(self) -> None:
        """No connection needed."""
        pass

    async def disconnect(self) -> None:
        """No disconnection needed."""
        pass

    async def health_check(self) -> bool:
        """Console is always healthy."""
        return True

    async def send(self, message: EmailMessage) -> EmailResult:
        """Log email to console.

        Args:
            message: The email message to log.

        Returns:
            EmailResult indicating success.
        """
        message_id = f"console-{uuid.uuid4()}"

        # Pretty print the email
        separator = "=" * 60
        print(f"\n{separator}")
        print("EMAIL (Console Backend)")
        print(separator)
        print(f"From: {message.from_name or self.settings.default_from_name} <{message.from_email or self.settings.default_from_email}>")
        print(f"To: {', '.join(message.to)}")
        if message.cc:
            print(f"Cc: {', '.join(message.cc)}")
        if message.bcc:
            print(f"Bcc: {', '.join(message.bcc)}")
        print(f"Subject: {message.subject}")
        print(f"Priority: {message.priority.value}")
        if message.attachments:
            print(f"Attachments: {', '.join(a.filename for a in message.attachments)}")
        print(separator)
        if message.body_text:
            print("TEXT BODY:")
            print(message.body_text[:500])
            if len(message.body_text) > 500:
                print(f"... ({len(message.body_text) - 500} more characters)")
        if message.body_html:
            print("\nHTML BODY:")
            print(message.body_html[:500])
            if len(message.body_html) > 500:
                print(f"... ({len(message.body_html) - 500} more characters)")
        print(f"{separator}\n")

        logger.info(
            "Email logged to console",
            extra={
                "message_id": message_id,
                "to": message.to,
                "subject": message.subject,
            },
        )

        return EmailResult.success_result(
            message_id=message_id,
            recipients=message.all_recipients,
            backend="console",
        )


class FileClient(BaseEmailClient):
    """File email client for testing.

    Writes emails to files in a specified directory.
    """

    def __init__(self, settings: EmailSettings) -> None:
        """Initialize file client."""
        self.settings = settings
        self.output_dir = Path(settings.file_path)
        logger.info(f"File email client initialized (output: {self.output_dir})")

    async def connect(self) -> None:
        """Ensure output directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def disconnect(self) -> None:
        """No disconnection needed."""
        pass

    async def health_check(self) -> bool:
        """Check if output directory is writable."""
        try:
            test_file = self.output_dir / ".health_check"
            test_file.touch()
            test_file.unlink()
            return True
        except Exception:
            return False

    async def send(self, message: EmailMessage) -> EmailResult:
        """Write email to file.

        Args:
            message: The email message to write.

        Returns:
            EmailResult indicating success.
        """
        message_id = f"file-{uuid.uuid4()}"
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{message_id}.json"
        filepath = self.output_dir / filename

        # Serialize message to JSON
        email_data = {
            "message_id": message_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "from_email": message.from_email or self.settings.default_from_email,
            "from_name": message.from_name or self.settings.default_from_name,
            "to": list(message.to),
            "cc": list(message.cc),
            "bcc": list(message.bcc),
            "reply_to": message.reply_to,
            "subject": message.subject,
            "body_text": message.body_text,
            "body_html": message.body_html,
            "priority": message.priority.value,
            "headers": message.headers,
            "tags": message.tags,
            "metadata": message.metadata,
            "attachments": [
                {
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "size": len(a.content) if a.content else None,
                    "path": a.path,
                }
                for a in message.attachments
            ],
        }

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(email_data, f, indent=2, default=str)

            logger.info(
                "Email written to file",
                extra={
                    "message_id": message_id,
                    "filepath": str(filepath),
                    "to": message.to,
                    "subject": message.subject,
                },
            )

            return EmailResult.success_result(
                message_id=message_id,
                recipients=message.all_recipients,
                backend="file",
            )
        except Exception as e:
            logger.error(f"Failed to write email to file: {e}")
            return EmailResult.failure_result(
                error=str(e),
                error_code="FILE_WRITE_ERROR",
                backend="file",
            )


class EmailClient:
    """Email client factory that delegates to the appropriate backend.

    Example:
        client = EmailClient(settings)
        await client.connect()
        result = await client.send(message)
        await client.disconnect()
    """

    def __init__(self, settings: EmailSettings) -> None:
        """Initialize email client with appropriate backend.

        Args:
            settings: Email settings.
        """
        self.settings = settings
        self._backend: BaseEmailClient

        if settings.backend == "smtp":
            self._backend = SMTPClient(settings)
        elif settings.backend == "console":
            self._backend = ConsoleClient(settings)
        elif settings.backend == "file":
            self._backend = FileClient(settings)
        else:
            raise ValueError(f"Unknown email backend: {settings.backend}")

    async def connect(self) -> None:
        """Establish connection to the email backend."""
        await self._backend.connect()

    async def disconnect(self) -> None:
        """Close connection to the email backend."""
        await self._backend.disconnect()

    async def send(self, message: EmailMessage) -> EmailResult:
        """Send an email message.

        Args:
            message: The email message to send.

        Returns:
            EmailResult with delivery status.
        """
        if not self.settings.enabled:
            logger.warning("Email sending is disabled")
            return EmailResult.failure_result(
                error="Email sending is disabled",
                error_code="EMAIL_DISABLED",
                backend=self.settings.backend,
            )

        return await self._backend.send(message)

    async def health_check(self) -> bool:
        """Check if the email backend is healthy."""
        return await self._backend.health_check()


@lru_cache(maxsize=1)
def get_email_settings() -> EmailSettings:
    """Get cached email settings."""
    return EmailSettings()


def get_email_client(settings: EmailSettings | None = None) -> EmailClient:
    """Get an email client instance.

    Args:
        settings: Optional settings override.

    Returns:
        Configured EmailClient instance.
    """
    if settings is None:
        settings = get_email_settings()
    return EmailClient(settings)
