"""File email provider for testing.

Writes emails to JSON files in a specified directory.
Useful for integration testing and debugging.

Usage:
    config = ResolvedEmailConfig(
        provider_type=EmailProviderType.FILE,
        config_json={"file_path": "/tmp/emails"}
    )
    provider = FileProvider(config)
    result = await provider.send(message)  # Writes to /tmp/emails/
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

from .base import BaseEmailProvider, EmailDeliveryResult, ProviderCapabilities

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


class FileProvider(BaseEmailProvider):
    """File email provider for testing.

    Writes emails as JSON files to a specified directory.
    Each email creates a timestamped JSON file with full message details.

    File format: {timestamp}_{message_id}.json

    Example:
        provider = FileProvider(config)
        result = await provider.send(message)
        # File created: /tmp/emails/20241202_120000_file-abc123.json
    """

    DEFAULT_OUTPUT_DIR = "/tmp/emails"  # noqa: S108

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize file provider.

        Args:
            config: Resolved email configuration
                   config_json may contain {"file_path": "/path/to/output"}
        """
        super().__init__(config)

        # Get output directory from config or use default
        self._output_dir = Path(
            (config.config_json or {}).get("file_path", self.DEFAULT_OUTPUT_DIR)
        )

        logger.info(
            "File email provider initialized",
            extra={
                "output_dir": str(self._output_dir),
                "tenant_id": config.tenant_id,
            },
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "file"

    def _default_capabilities(self) -> ProviderCapabilities:
        """File provider supports everything (for testing)."""
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
        """Write email to file.

        Args:
            message: Email message to write

        Returns:
            EmailDeliveryResult with file path in metadata
        """
        message_id = f"file-{uuid.uuid4()}"
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{message_id}.json"
        filepath = self._output_dir / filename

        # Get sender info
        from_email = message.from_email or self._config.from_email
        from_name = message.from_name or self._config.from_name

        # Serialize message to JSON
        email_data = {
            "message_id": message_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "provider": self.provider_name,
            "tenant_id": self._config.tenant_id,
            # Sender
            "from_email": from_email,
            "from_name": from_name,
            # Recipients
            "to": list(message.to),
            "cc": list(message.cc),
            "bcc": list(message.bcc),
            "reply_to": message.reply_to or self._config.reply_to,
            # Content
            "subject": message.subject,
            "body_text": message.body_text,
            "body_html": message.body_html,
            # Metadata
            "priority": message.priority.value,
            "headers": message.headers,
            "tags": message.tags,
            "metadata": message.metadata,
            "template_name": message.template_name,
            # Attachments (metadata only, not content)
            "attachments": [
                {
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "size_bytes": len(a.content) if a.content else None,
                    "path": a.path,
                    "content_id": a.content_id,
                }
                for a in message.attachments
            ],
        }

        try:
            # Ensure directory exists
            self._output_dir.mkdir(parents=True, exist_ok=True)

            # Write JSON file
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(email_data, f, indent=2, default=str)

            logger.debug(
                "Email written to file",
                extra={
                    "message_id": message_id,
                    "filepath": str(filepath),
                    "recipients": len(message.all_recipients),
                },
            )

            return EmailDeliveryResult.success_result(
                message_id=message_id,
                provider=self.provider_name,
                recipients=message.all_recipients,
                metadata={
                    "filepath": str(filepath),
                    "filename": filename,
                },
            )

        except PermissionError as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"Permission denied writing to {filepath}: {e}",
                error_code="PERMISSION_DENIED",
            )
        except OSError as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"Failed to write email to file: {e}",
                error_code="FILE_WRITE_ERROR",
            )

    async def _do_health_check(self) -> bool:
        """Check if output directory is writable.

        Returns:
            True if directory is writable
        """
        try:
            # Ensure directory exists
            self._output_dir.mkdir(parents=True, exist_ok=True)

            # Try to create and delete a test file
            test_file = self._output_dir / ".health_check"
            test_file.touch()
            test_file.unlink()
            return True
        except Exception as e:
            logger.debug(f"File provider health check failed: {e}")
            return False

    def list_emails(self, limit: int = 100) -> list[dict]:
        """List emails in the output directory.

        Useful for testing to verify emails were "sent".

        Args:
            limit: Maximum number of emails to return

        Returns:
            List of email data dicts, newest first
        """
        if not self._output_dir.exists():
            return []

        emails = []
        for filepath in sorted(self._output_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                with open(filepath, encoding="utf-8") as f:
                    emails.append(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to read email file {filepath}: {e}")

        return emails

    def clear_emails(self) -> int:
        """Clear all emails in the output directory.

        Useful for test cleanup.

        Returns:
            Number of files deleted
        """
        if not self._output_dir.exists():
            return 0

        count = 0
        for filepath in self._output_dir.glob("*.json"):
            try:
                filepath.unlink()
                count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {filepath}: {e}")

        return count


__all__ = ["FileProvider"]
