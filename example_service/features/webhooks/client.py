"""HTTP client for webhook delivery."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from example_service.infra.logging import get_lazy_logger

if TYPE_CHECKING:
    from example_service.features.webhooks.models import Webhook

logger = logging.getLogger(__name__)
lazy_logger = get_lazy_logger(__name__)


@dataclass
class WebhookDeliveryResult:
    """Result of a webhook delivery attempt."""

    success: bool
    status_code: int | None
    response_body: str | None
    response_time_ms: int | None
    error_message: str | None


class WebhookClient:
    """HTTP client for delivering webhook events.

    Handles:
    - HMAC-SHA256 signature generation
    - Custom headers and authentication
    - Timeout and error handling
    - Response capture
    """

    def __init__(self, timeout_seconds: int = 30) -> None:
        """Initialize webhook client.

        Args:
            timeout_seconds: Default timeout for HTTP requests
        """
        self.timeout_seconds = timeout_seconds

    def _generate_signature(
        self,
        secret: str,
        timestamp: str,
        payload: str,
    ) -> str:
        """Generate HMAC-SHA256 signature for webhook payload.

        Args:
            secret: HMAC secret key
            timestamp: ISO format timestamp
            payload: JSON payload string

        Returns:
            Hex-encoded HMAC signature
        """
        # Construct message to sign: timestamp + payload
        message = f"{timestamp}.{payload}"

        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return signature

    async def deliver(
        self,
        webhook: Webhook,
        event_type: str,
        event_id: str,
        payload: dict,
    ) -> WebhookDeliveryResult:
        """Deliver webhook event to configured URL.

        Args:
            webhook: Webhook configuration
            event_type: Type of event
            event_id: Unique event identifier
            payload: Event payload data

        Returns:
            WebhookDeliveryResult with delivery status and response
        """
        start_time = time.time()

        try:
            # Prepare payload
            import json
            payload_str = json.dumps(payload, separators=(",", ":"))

            # Generate timestamp and signature
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            signature = self._generate_signature(webhook.secret, timestamp, payload_str)

            # Prepare headers
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "FastAPI-Webhook/1.0",
                "X-Webhook-Signature": signature,
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Event-Type": event_type,
                "X-Webhook-Event-ID": event_id,
            }

            # Add custom headers if configured
            if webhook.custom_headers:
                headers.update(webhook.custom_headers)

            lazy_logger.debug(
                lambda: f"client.deliver: webhook_id={webhook.id}, event_type={event_type}, url={webhook.url}"
            )

            # Send HTTP POST request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook.url,
                    content=payload_str,
                    headers=headers,
                    timeout=webhook.timeout_seconds,
                )

            # Calculate response time
            response_time_ms = int((time.time() - start_time) * 1000)

            # Determine success based on status code
            success = 200 <= response.status_code < 300

            # Truncate response body
            response_body = response.text[:5000] if response.text else None

            if success:
                logger.info(
                    "Webhook delivered successfully",
                    extra={
                        "webhook_id": str(webhook.id),
                        "event_type": event_type,
                        "event_id": event_id,
                        "status_code": response.status_code,
                        "response_time_ms": response_time_ms,
                        "operation": "client.deliver",
                    },
                )
            else:
                logger.warning(
                    "Webhook delivery failed with non-2xx status",
                    extra={
                        "webhook_id": str(webhook.id),
                        "event_type": event_type,
                        "event_id": event_id,
                        "status_code": response.status_code,
                        "response_time_ms": response_time_ms,
                        "operation": "client.deliver",
                    },
                )

            return WebhookDeliveryResult(
                success=success,
                status_code=response.status_code,
                response_body=response_body,
                response_time_ms=response_time_ms,
                error_message=None if success else f"HTTP {response.status_code}",
            )

        except httpx.TimeoutException:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_message = f"Request timeout after {webhook.timeout_seconds}s"

            logger.warning(
                "Webhook delivery timeout",
                extra={
                    "webhook_id": str(webhook.id),
                    "event_type": event_type,
                    "event_id": event_id,
                    "timeout_seconds": webhook.timeout_seconds,
                    "operation": "client.deliver",
                },
            )

            return WebhookDeliveryResult(
                success=False,
                status_code=None,
                response_body=None,
                response_time_ms=response_time_ms,
                error_message=error_message,
            )

        except httpx.RequestError as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_message = f"Request error: {str(e)}"

            logger.error(
                "Webhook delivery request error",
                extra={
                    "webhook_id": str(webhook.id),
                    "event_type": event_type,
                    "event_id": event_id,
                    "error": str(e),
                    "operation": "client.deliver",
                },
                exc_info=True,
            )

            return WebhookDeliveryResult(
                success=False,
                status_code=None,
                response_body=None,
                response_time_ms=response_time_ms,
                error_message=error_message,
            )

        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_message = f"Unexpected error: {str(e)}"

            logger.error(
                "Webhook delivery unexpected error",
                extra={
                    "webhook_id": str(webhook.id),
                    "event_type": event_type,
                    "event_id": event_id,
                    "error": str(e),
                    "operation": "client.deliver",
                },
                exc_info=True,
            )

            return WebhookDeliveryResult(
                success=False,
                status_code=None,
                response_body=None,
                response_time_ms=response_time_ms,
                error_message=error_message,
            )


__all__ = ["WebhookClient", "WebhookDeliveryResult"]
