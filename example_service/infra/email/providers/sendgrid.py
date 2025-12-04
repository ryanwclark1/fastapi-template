"""SendGrid email provider.

Production-ready SendGrid API v3 provider with:
- Async HTTP using httpx (already in project)
- API key authentication
- Categories and custom arguments
- Scheduled sending
- Comprehensive error handling

Usage:
    config = ResolvedEmailConfig(
        provider_type=EmailProviderType.SENDGRID,
        api_key="SG.xxx...",
    )
    provider = SendGridProvider(config)
    result = await provider.send(message)
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

import httpx

from .base import BaseEmailProvider, EmailDeliveryResult, ProviderCapabilities

if TYPE_CHECKING:
    from example_service.infra.email.resolver import ResolvedEmailConfig
    from example_service.infra.email.schemas import EmailMessage

logger = logging.getLogger(__name__)


class SendGridProvider(BaseEmailProvider):
    """SendGrid email provider using API v3.

    Supports:
    - Simple and personalized emails
    - Attachments (base64 encoded)
    - Categories for analytics
    - Custom arguments (custom_args)
    - Scheduled sending (send_at)
    - Click/open tracking (via account settings)

    Example:
        config = ResolvedEmailConfig(
            provider_type=EmailProviderType.SENDGRID,
            api_key="SG.xxx...",
            from_email="sender@example.com",
        )
        provider = SendGridProvider(config)
        result = await provider.send(message)
    """

    API_BASE_URL = "https://api.sendgrid.com/v3"
    SEND_ENDPOINT = "/mail/send"

    def __init__(self, config: ResolvedEmailConfig) -> None:
        """Initialize SendGrid provider.

        Args:
            config: Resolved email configuration with API key

        Raises:
            ValueError: If API key is missing
        """
        super().__init__(config)

        if not config.api_key:
            raise ValueError("SendGrid provider requires api_key")

        self._api_key = config.api_key
        self._base_url = config.api_endpoint or self.API_BASE_URL

        logger.info(
            "SendGrid provider initialized",
            extra={
                "base_url": self._base_url,
                "tenant_id": config.tenant_id,
            },
        )

    @property
    def provider_name(self) -> str:
        """Get provider name."""
        return "sendgrid"

    def _default_capabilities(self) -> ProviderCapabilities:
        """SendGrid capabilities."""
        return ProviderCapabilities(
            supports_attachments=True,
            supports_html=True,
            supports_templates=True,  # Dynamic templates
            supports_tracking=True,  # Click/open tracking
            supports_scheduling=True,  # send_at
            supports_batch=True,
            max_recipients=1000,  # Per API call
            max_attachment_size_mb=30.0,
        )

    def _build_payload(self, message: EmailMessage) -> dict[str, Any]:
        """Build SendGrid API payload.

        Args:
            message: Email message

        Returns:
            Dict payload for SendGrid API
        """
        # Get sender info
        from_email = message.from_email or self._config.from_email
        from_name = message.from_name or self._config.from_name

        # Build personalizations (recipients)
        personalization: dict[str, Any] = {
            "to": [{"email": email} for email in message.to],
        }
        if message.cc:
            personalization["cc"] = [{"email": email} for email in message.cc]
        if message.bcc:
            personalization["bcc"] = [{"email": email} for email in message.bcc]

        # Build payload
        payload: dict[str, Any] = {
            "personalizations": [personalization],
            "from": {"email": from_email},
            "subject": message.subject,
        }

        # Add from name if provided
        if from_name:
            payload["from"]["name"] = from_name

        # Add reply-to
        reply_to = message.reply_to or self._config.reply_to
        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        # Add content
        content_parts: list[dict[str, str]] = []
        if message.body_text:
            content_parts.append({"type": "text/plain", "value": message.body_text})
        if message.body_html:
            content_parts.append({"type": "text/html", "value": message.body_html})
        if content_parts:
            payload["content"] = content_parts

        # Add categories (tags)
        if message.tags:
            payload["categories"] = message.tags[:10]  # SendGrid limit

        # Add custom args from metadata
        if message.metadata:
            payload["custom_args"] = {
                k: str(v) for k, v in message.metadata.items()
            }

        # Add attachments
        if message.attachments:
            attachments = []
            for attachment in message.attachments:
                att_content = attachment.content
                if att_content is None and attachment.path:
                    with open(attachment.path, "rb") as f:
                        att_content = f.read()

                if att_content:
                    att_data: dict[str, str] = {
                        "content": base64.b64encode(att_content).decode("utf-8"),
                        "filename": attachment.filename,
                    }
                    if attachment.content_type:
                        att_data["type"] = attachment.content_type
                    if attachment.content_id:
                        att_data["content_id"] = attachment.content_id
                        att_data["disposition"] = "inline"
                    else:
                        att_data["disposition"] = "attachment"

                    attachments.append(att_data)

            if attachments:
                payload["attachments"] = attachments

        # Add headers
        if message.headers:
            payload["headers"] = message.headers

        # Add priority via headers
        if message.priority.value == "high":
            payload.setdefault("headers", {})["X-Priority"] = "1"
        elif message.priority.value == "low":
            payload.setdefault("headers", {})["X-Priority"] = "5"

        return payload

    async def _do_send(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send email via SendGrid API.

        Args:
            message: Email message to send

        Returns:
            EmailDeliveryResult with SendGrid message ID
        """
        payload = self._build_payload(message)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}{self.SEND_ENDPOINT}",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

            # SendGrid returns 202 Accepted on success
            if response.status_code == 202:
                # Get message ID from header
                message_id = response.headers.get(
                    "X-Message-Id", f"sg-{response.headers.get('X-Request-Id', 'unknown')}"
                )

                return EmailDeliveryResult.success_result(
                    message_id=message_id,
                    provider=self.provider_name,
                    recipients=message.all_recipients,
                    metadata={
                        "request_id": response.headers.get("X-Request-Id"),
                    },
                )

            # Handle errors
            error_body = response.text
            try:
                error_json = response.json()
                if "errors" in error_json:
                    error_body = "; ".join(
                        e.get("message", str(e)) for e in error_json["errors"]
                    )
            except Exception:  # noqa: S110
                # Ignore JSON parsing errors, use default error_body
                pass

            error_code = self._classify_http_error(response.status_code)

            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"SendGrid API error ({response.status_code}): {error_body}",
                error_code=error_code,
                recipients_rejected=message.all_recipients,
                metadata={"status_code": response.status_code},
            )

        except httpx.TimeoutException:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error="SendGrid API timeout",
                error_code="TIMEOUT",
            )
        except httpx.HTTPError as e:
            return EmailDeliveryResult.failure_result(
                provider=self.provider_name,
                error=f"SendGrid HTTP error: {e}",
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
        if status_code >= 500:
            return "SERVER_ERROR"
        return "API_ERROR"

    async def _do_health_check(self) -> bool:
        """Check SendGrid API connectivity.

        Returns:
            True if API is accessible
        """
        try:
            async with httpx.AsyncClient() as client:
                # Check API key validity via user profile endpoint
                response = await client.get(
                    f"{self._base_url}/user/profile",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"SendGrid health check failed: {e}")
            return False


__all__ = ["SendGridProvider"]
