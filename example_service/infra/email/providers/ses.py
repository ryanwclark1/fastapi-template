"""AWS SES email provider.

Production-ready AWS Simple Email Service provider with:
- Async boto3 (aioboto3) support
- IAM authentication
- Multi-region support
- Configuration set tracking
- Comprehensive error handling

Requires: pip install aioboto3

Usage:
    config = ResolvedEmailConfig(
        provider_type=EmailProviderType.AWS_SES,
        aws_region="us-east-1",
        aws_access_key="AKIA...",
        aws_secret_key="...",
    )
    provider = SESProvider(config)
    result = await provider.send(message)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
import uuid

from .base import BaseEmailProvider, EmailDeliveryResult, ProviderCapabilities

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)

# Check for aioboto3 at import time
try:
    import aioboto3  # type: ignore[import-not-found]

    AIOBOTO3_AVAILABLE = True
except ImportError:
    AIOBOTO3_AVAILABLE = False
    aioboto3 = None  # type: ignore[assignment, unused-ignore]


class SESProvider(BaseEmailProvider):
    """AWS SES email provider using aioboto3.

    Supports:
    - send_email API (simple emails)
    - Configuration sets for tracking
    - IAM authentication (access key + secret)
    - Multi-region deployment

    Note: For attachments, would need send_raw_email API (not implemented yet).

    Example:
        config = ResolvedEmailConfig(
            provider_type=EmailProviderType.AWS_SES,
            aws_region="us-east-1",
            aws_access_key="AKIA...",
            aws_secret_key="secret",
            aws_configuration_set="tracking-set",
        )
        provider = SESProvider(config)
        result = await provider.send(message)
    """

    DEFAULT_REGION = "us-east-1"

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize SES provider.

        Args:
            config: Resolved email configuration with AWS settings

        Raises:
            ImportError: If aioboto3 is not installed
            ValueError: If required AWS credentials missing
        """
        if not AIOBOTO3_AVAILABLE:
            msg = (
                "AWS SES provider requires aioboto3. "
                "Install with: pip install aioboto3"
            )
            raise ImportError(
                msg
            )

        super().__init__(config)

        # Validate AWS-specific config
        if not config.aws_access_key or not config.aws_secret_key:
            msg = "AWS SES provider requires aws_access_key and aws_secret_key"
            raise ValueError(
                msg
            )

        self._region = config.aws_region or self.DEFAULT_REGION
        self._access_key = config.aws_access_key
        self._secret_key = config.aws_secret_key
        self._configuration_set = config.aws_configuration_set

        logger.info(
            "SES provider initialized",
            extra={
                "region": self._region,
                "configuration_set": self._configuration_set,
                "tenant_id": config.tenant_id,
            },
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "aws_ses"

    def _default_capabilities(self) -> ProviderCapabilities:
        """SES capabilities."""
        return ProviderCapabilities(
            supports_attachments=False,  # Would need send_raw_email
            supports_html=True,
            supports_templates=True,  # SES has native templates
            supports_tracking=True,  # Via configuration sets
            supports_scheduling=False,
            supports_batch=True,
            max_recipients=50,  # SES limit per API call
            max_attachment_size_mb=10.0,  # SES limit
        )

    def _get_session(self) -> Any:
        """Get aioboto3 session with credentials.

        Returns:
            aioboto3.Session configured with AWS credentials
        """
        return aioboto3.Session(
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
        )

    async def _do_send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send email via AWS SES.

        Args:
            message: Email message to send

        Returns:
            EmailDeliveryResult with AWS message ID
        """
        # Get sender info
        from_email = message.from_email or self._config.from_email
        from_name = message.from_name or self._config.from_name
        source = f"{from_name} <{from_email}>" if from_name else from_email

        # Build destination
        destination: dict[str, list[str]] = {
            "ToAddresses": list(message.to),
        }
        if message.cc:
            destination["CcAddresses"] = list(message.cc)
        if message.bcc:
            destination["BccAddresses"] = list(message.bcc)

        # Build message body
        body: dict[str, dict[str, str]] = {}
        if message.body_text:
            body["Text"] = {"Data": message.body_text, "Charset": "UTF-8"}
        if message.body_html:
            body["Html"] = {"Data": message.body_html, "Charset": "UTF-8"}

        # Ensure we have at least one body type
        if not body:
            body["Text"] = {"Data": "", "Charset": "UTF-8"}

        # Build SES message
        ses_message: dict[str, Any] = {
            "Subject": {"Data": message.subject, "Charset": "UTF-8"},
            "Body": body,
        }

        try:
            session = self._get_session()
            async with session.client("ses") as ses:
                # Build send_email parameters
                params: dict[str, Any] = {
                    "Source": source,
                    "Destination": destination,
                    "Message": ses_message,
                }

                # Add reply-to if specified
                reply_to = message.reply_to or self._config.reply_to
                if reply_to:
                    params["ReplyToAddresses"] = [reply_to]

                # Add configuration set if specified
                if self._configuration_set:
                    params["ConfigurationSetName"] = self._configuration_set

                # Add tags if specified
                if message.tags:
                    params["Tags"] = [
                        {"Name": "tag", "Value": tag} for tag in message.tags[:10]
                    ]

                # Send email
                response = await ses.send_email(**params)

            message_id = response.get("MessageId", f"ses-{uuid.uuid4()}")

            return EmailDeliveryResult.success_result(
                message_id=message_id,
                provider=self.provider_name,
                recipients=message.all_recipients,
                metadata={
                    "region": self._region,
                    "configuration_set": self._configuration_set,
                    "aws_request_id": response.get("ResponseMetadata", {}).get(
                        "RequestId"
                    ),
                },
            )

        except Exception as e:
            error_code = self._classify_ses_error(e)
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=str(e),
                error_code=error_code,
                recipients_rejected=message.all_recipients,
                metadata={"region": self._region},
            )

    def _classify_ses_error(self, error: Exception) -> str:
        """Classify SES error into error code.

        Args:
            error: Exception from SES

        Returns:
            Error code string
        """
        error_str = str(error).lower()

        if "credentials" in error_str or "access" in error_str:
            return "AUTH_FAILED"
        if "throttl" in error_str or "rate" in error_str:
            return "RATE_LIMITED"
        if "invalid" in error_str and "address" in error_str:
            return "INVALID_RECIPIENT"
        if "not verified" in error_str:
            return "SENDER_NOT_VERIFIED"
        if "quota" in error_str:
            return "QUOTA_EXCEEDED"

        return "SES_ERROR"

    async def _do_health_check(self) -> bool:
        """Check SES connectivity and permissions.

        Returns:
            True if SES is accessible
        """
        try:
            session = self._get_session()
            async with session.client("ses") as ses:
                # Get send quota to verify connectivity
                await ses.get_send_quota()
            return True
        except Exception as e:
            logger.debug(f"SES health check failed: {e}")
            return False


__all__ = ["SESProvider"]
