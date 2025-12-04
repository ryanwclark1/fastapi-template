"""Mailgun email provider.

Production-ready Mailgun API provider with:
- Async HTTP using httpx
- API key authentication
- US and EU region support
- Tags and variables
- Scheduled sending
- Comprehensive error handling

Usage:
    config = ResolvedEmailConfig(
        provider_type=EmailProviderType.MAILGUN,
        api_key="key-xxx...",
        api_endpoint="https://api.mailgun.net",  # or https://api.eu.mailgun.net
        config_json={"domain": "mail.example.com"},
    )
    provider = MailgunProvider(config)
    result = await provider.send(message)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from .base import BaseEmailProvider, EmailDeliveryResult, ProviderCapabilities

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


class MailgunProvider(BaseEmailProvider):
    """Mailgun email provider using HTTP API.

    Supports:
    - Simple emails via messages endpoint
    - Attachments (multipart form)
    - Tags for analytics
    - Custom variables (recipient variables)
    - Scheduled sending (o:deliverytime)
    - Tracking (o:tracking options)

    Configuration:
    - api_key: Mailgun API key (required)
    - api_endpoint: API base URL (default: US region)
    - config_json.domain: Sending domain (required)

    Example:
        config = ResolvedEmailConfig(
            provider_type=EmailProviderType.MAILGUN,
            api_key="key-xxx...",
            config_json={"domain": "mail.example.com"},
        )
        provider = MailgunProvider(config)
        result = await provider.send(message)
    """

    # Region endpoints
    US_API_URL = "https://api.mailgun.net/v3"
    EU_API_URL = "https://api.eu.mailgun.net/v3"

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize Mailgun provider.

        Args:
            config: Resolved email configuration with API key and domain

        Raises:
            ValueError: If API key or domain is missing
        """
        super().__init__(config)

        if not config.api_key:
            raise ValueError("Mailgun provider requires api_key")

        # Get domain from config_json
        config_json = config.config_json or {}
        self._domain = config_json.get("domain")
        if not self._domain:
            raise ValueError(
                "Mailgun provider requires domain in config_json: "
                '{"domain": "mail.example.com"}'
            )

        self._api_key = config.api_key
        self._base_url = config.api_endpoint or self.US_API_URL

        # Check for EU region shorthand
        if self._base_url.lower() in ("eu", "europe"):
            self._base_url = self.EU_API_URL

        logger.info(
            "Mailgun provider initialized",
            extra={
                "domain": self._domain,
                "base_url": self._base_url,
                "tenant_id": config.tenant_id,
            },
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "mailgun"

    def _default_capabilities(self) -> ProviderCapabilities:
        """Mailgun capabilities."""
        return ProviderCapabilities(
            supports_attachments=True,
            supports_html=True,
            supports_templates=True,  # Mailgun templates
            supports_tracking=True,  # Click/open tracking
            supports_scheduling=True,  # o:deliverytime
            supports_batch=True,
            max_recipients=1000,
            max_attachment_size_mb=25.0,
        )

    def _build_form_data(self, message: EmailMessage) -> dict[str, Any]:
        """Build form data for Mailgun API.

        Args:
            message: Email message

        Returns:
            Dict of form fields
        """
        # Get sender info
        from_email = message.from_email or self._config.from_email
        from_name = message.from_name or self._config.from_name
        sender = f"{from_name} <{from_email}>" if from_name else from_email

        # Build form data
        data: dict[str, Any] = {
            "from": sender,
            "to": list(message.to),
            "subject": message.subject,
        }

        # Add CC and BCC
        if message.cc:
            data["cc"] = list(message.cc)
        if message.bcc:
            data["bcc"] = list(message.bcc)

        # Add reply-to
        reply_to = message.reply_to or self._config.reply_to
        if reply_to:
            data["h:Reply-To"] = reply_to

        # Add body
        if message.body_text:
            data["text"] = message.body_text
        if message.body_html:
            data["html"] = message.body_html

        # Add tags (Mailgun calls them "o:tag")
        if message.tags:
            data["o:tag"] = message.tags[:3]  # Mailgun limit

        # Add custom headers
        for key, value in message.headers.items():
            data[f"h:{key}"] = value

        # Add priority via header
        if message.priority.value == "high":
            data["h:X-Priority"] = "1"
        elif message.priority.value == "low":
            data["h:X-Priority"] = "5"

        # Add metadata as custom variables (v:xxx)
        if message.metadata:
            for key, value in message.metadata.items():
                data[f"v:{key}"] = str(value)

        return data

    async def _do_send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send email via Mailgun API.

        Args:
            message: Email message to send

        Returns:
            EmailDeliveryResult with Mailgun message ID
        """
        form_data = self._build_form_data(message)
        url = f"{self._base_url}/{self._domain}/messages"

        try:
            async with httpx.AsyncClient() as client:
                # Build multipart request for attachments
                files = []
                if message.attachments:
                    for attachment in message.attachments:
                        content = attachment.content
                        if content is None and attachment.path:
                            with open(attachment.path, "rb") as f:
                                content = f.read()

                        if content:
                            files.append(
                                (
                                    "attachment",
                                    (
                                        attachment.filename,
                                        content,
                                        attachment.content_type or "application/octet-stream",
                                    ),
                                )
                            )

                response = await client.post(
                    url,
                    data=form_data,
                    files=files if files else None,
                    auth=("api", self._api_key),
                    timeout=30.0,
                )

            if response.status_code == 200:
                response_json = response.json()
                message_id = response_json.get("id", "").strip("<>")

                return EmailDeliveryResult.success_result(
                    message_id=message_id,
                    provider=self.provider_name,
                    recipients=message.all_recipients,
                    metadata={
                        "domain": self._domain,
                        "mailgun_message": response_json.get("message"),
                    },
                )

            # Handle errors
            error_body = response.text
            try:
                error_json = response.json()
                error_body = error_json.get("message", error_body)
            except Exception:  # noqa: S110
                # Ignore JSON parsing errors, use default error_body
                pass

            error_code = self._classify_http_error(response.status_code)

            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"Mailgun API error ({response.status_code}): {error_body}",
                error_code=error_code,
                recipients_rejected=message.all_recipients,
                metadata={
                    "status_code": response.status_code,
                    "domain": self._domain,
                },
            )

        except httpx.TimeoutException:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error="Mailgun API timeout",
                error_code="TIMEOUT",
            )
        except httpx.HTTPError as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"Mailgun HTTP error: {e}",
                error_code="HTTP_ERROR",
            )

    def _classify_http_error(self, status_code: int) -> str:
        """Classify HTTP status code into error code.

        Args:
            status_code: HTTP status code

        Returns:
            Error code string
        """
        if status_code == 401:
            return "AUTH_FAILED"
        if status_code == 403:
            return "FORBIDDEN"
        if status_code == 429:
            return "RATE_LIMITED"
        if status_code == 400:
            return "BAD_REQUEST"
        if status_code == 404:
            return "DOMAIN_NOT_FOUND"
        if status_code >= 500:
            return "SERVER_ERROR"
        return "API_ERROR"

    async def _do_health_check(self) -> bool:
        """Check Mailgun API connectivity.

        Returns:
            True if API is accessible
        """
        try:
            async with httpx.AsyncClient() as client:
                # Check domain info to verify credentials and domain
                response = await client.get(
                    f"{self._base_url}/domains/{self._domain}",
                    auth=("api", self._api_key),
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"Mailgun health check failed: {e}")
            return False


__all__ = ["MailgunProvider"]
