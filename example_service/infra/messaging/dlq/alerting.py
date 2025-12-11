"""DLQ alerting module with configurable channels and rate limiting.

This module provides alerting capabilities for DLQ events:
- Multiple alert channels (email, webhook, logging)
- Alert severity levels (info, warning, critical)
- Rate limiting to prevent alert storms
- Integration with email service and Prometheus metrics

Example:
    from example_service.infra.messaging.dlq.alerting import (
        DLQAlerter,
        AlertConfig,
        get_dlq_alerter,
    )

    alerter = get_dlq_alerter()
    await alerter.alert_dlq_message(
        original_queue="orders",
        error_type="ValidationError",
        retry_count=5,
        message_preview="Order ID: 12345",
    )
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from example_service.infra.email.service import EmailService

from example_service.infra.email.schemas import EmailPriority

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    """Available alert channels."""

    LOG = "log"
    EMAIL = "email"
    WEBHOOK = "webhook"


@dataclass
class AlertConfig:
    """Configuration for DLQ alerting.

    Attributes:
        enabled: Whether alerting is enabled.
        channels: List of alert channels to use.
        email_recipients: Recipients for email alerts.
        webhook_url: URL for webhook alerts.
        rate_limit_seconds: Minimum seconds between alerts (per queue).
        warning_threshold: Retry count threshold for warning severity.
        critical_threshold: Retry count threshold for critical severity.
        include_message_preview: Whether to include message preview in alerts.
        max_preview_length: Maximum length of message preview.
    """

    enabled: bool = True
    channels: list[AlertChannel] = field(default_factory=lambda: [AlertChannel.LOG])
    email_recipients: list[str] = field(default_factory=list)
    webhook_url: str | None = None
    rate_limit_seconds: int = 60
    warning_threshold: int = 3
    critical_threshold: int = 5
    include_message_preview: bool = True
    max_preview_length: int = 500


@dataclass
class DLQAlert:
    """Representation of a DLQ alert.

    Attributes:
        timestamp: When the alert was created.
        severity: Alert severity level.
        original_queue: Queue that produced the failed message.
        error_type: Type of exception that caused the failure.
        error_message: Error message (truncated).
        retry_count: Number of retry attempts.
        message_preview: Preview of the message content.
        metadata: Additional alert metadata.
    """

    timestamp: datetime
    severity: AlertSeverity
    original_queue: str
    error_type: str
    error_message: str
    retry_count: int
    message_preview: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity.value,
            "original_queue": self.original_queue,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "message_preview": self.message_preview,
            "metadata": self.metadata,
        }

    def format_subject(self) -> str:
        """Format email subject line."""
        severity_emoji = {
            AlertSeverity.INFO: "i",  # Information symbol
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🚨",
        }
        emoji = severity_emoji.get(self.severity, "")
        return f"{emoji} DLQ Alert [{self.severity.value.upper()}]: {self.original_queue} - {self.error_type}"

    def format_body(self) -> str:
        """Format alert body for email/log."""
        lines = [
            f"DLQ Alert - {self.severity.value.upper()}",
            "=" * 50,
            f"Timestamp: {self.timestamp.isoformat()}",
            f"Queue: {self.original_queue}",
            f"Error Type: {self.error_type}",
            f"Error Message: {self.error_message}",
            f"Retry Count: {self.retry_count}",
        ]

        if self.message_preview:
            lines.extend(
                [
                    "",
                    "Message Preview:",
                    "-" * 30,
                    self.message_preview,
                ],
            )

        if self.metadata:
            lines.extend(
                [
                    "",
                    "Metadata:",
                    "-" * 30,
                ],
            )
            for key, value in self.metadata.items():
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)


class RateLimiter:
    """Simple rate limiter for alert throttling.

    Prevents alert storms by limiting alerts per queue.
    """

    def __init__(self, min_interval_seconds: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            min_interval_seconds: Minimum seconds between alerts per key.
        """
        self._last_alert: dict[str, datetime] = {}
        self._min_interval = min_interval_seconds

    def should_alert(self, key: str) -> bool:
        """Check if an alert should be sent for the given key.

        Args:
            key: Rate limit key (e.g., queue name).

        Returns:
            True if alert should be sent, False if rate limited.
        """
        now = datetime.now(UTC)
        last = self._last_alert.get(key)

        if last is None:
            self._last_alert[key] = now
            return True

        elapsed = (now - last).total_seconds()
        if elapsed >= self._min_interval:
            self._last_alert[key] = now
            return True

        return False

    def reset(self, key: str | None = None) -> None:
        """Reset rate limit state.

        Args:
            key: Optional specific key to reset. If None, resets all.
        """
        if key is None:
            self._last_alert.clear()
        else:
            self._last_alert.pop(key, None)


class DLQAlerter:
    """DLQ alerter with multiple channels and rate limiting.

    Sends alerts when messages are routed to the Dead Letter Queue.
    Supports email, webhook, and logging channels with rate limiting.

    Example:
        config = AlertConfig(
            channels=[AlertChannel.EMAIL, AlertChannel.LOG],
            email_recipients=["ops@example.com"],
            critical_threshold=5,
        )
        alerter = DLQAlerter(config)

        await alerter.alert_dlq_message(
            original_queue="orders",
            error_type="ValidationError",
            retry_count=5,
        )
    """

    def __init__(
        self,
        config: AlertConfig | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        """Initialize DLQ alerter.

        Args:
            config: Alert configuration.
            email_service: Optional email service for email alerts.
        """
        self.config = config or AlertConfig()
        self._email_service = email_service
        self._rate_limiter = RateLimiter(self.config.rate_limit_seconds)
        self._http_client: Any | None = None

    def _determine_severity(self, retry_count: int) -> AlertSeverity:
        """Determine alert severity based on retry count.

        Args:
            retry_count: Number of retry attempts.

        Returns:
            Appropriate severity level.
        """
        if retry_count >= self.config.critical_threshold:
            return AlertSeverity.CRITICAL
        if retry_count >= self.config.warning_threshold:
            return AlertSeverity.WARNING
        return AlertSeverity.INFO

    def _truncate_message(self, message: str) -> str:
        """Truncate message to maximum preview length.

        Args:
            message: Message to truncate.

        Returns:
            Truncated message with ellipsis if needed.
        """
        if len(message) <= self.config.max_preview_length:
            return message
        return message[: self.config.max_preview_length - 3] + "..."

    async def alert_dlq_message(
        self,
        original_queue: str,
        error_type: str,
        error_message: str = "",
        retry_count: int = 0,
        message_body: dict[str, Any] | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Send alert for a DLQ message.

        This is the main entry point for DLQ alerting. It:
        1. Checks if alerting is enabled
        2. Applies rate limiting
        3. Determines severity
        4. Sends to configured channels

        Args:
            original_queue: Queue that produced the failed message.
            error_type: Type of exception that caused the failure.
            error_message: Error message.
            retry_count: Number of retry attempts.
            message_body: Optional message body for preview.
            metadata: Additional metadata to include.

        Returns:
            True if alert was sent, False if skipped (rate limited/disabled).
        """
        if not self.config.enabled:
            return False

        # Apply rate limiting per queue
        rate_key = f"{original_queue}:{error_type}"
        if not self._rate_limiter.should_alert(rate_key):
            logger.debug(
                "DLQ alert rate limited",
                extra={"queue": original_queue, "error_type": error_type},
            )
            return False

        # Prepare message preview
        message_preview = None
        if self.config.include_message_preview and message_body:
            if isinstance(message_body, dict):
                import json

                message_preview = self._truncate_message(
                    json.dumps(message_body, indent=2, default=str),
                )
            else:
                message_preview = self._truncate_message(str(message_body))

        # Create alert
        alert = DLQAlert(
            timestamp=datetime.now(UTC),
            severity=self._determine_severity(retry_count),
            original_queue=original_queue,
            error_type=error_type,
            error_message=self._truncate_message(error_message)[:200],
            retry_count=retry_count,
            message_preview=message_preview,
            metadata=metadata or {},
        )

        # Send to all configured channels
        tasks = []
        for channel in self.config.channels:
            if channel == AlertChannel.LOG:
                tasks.append(self._send_log_alert(alert))
            elif channel == AlertChannel.EMAIL:
                tasks.append(self._send_email_alert(alert))
            elif channel == AlertChannel.WEBHOOK:
                tasks.append(self._send_webhook_alert(alert))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Update Prometheus metrics
        self._record_alert_metrics(alert)

        return True

    async def _send_log_alert(self, alert: DLQAlert) -> None:
        """Send alert via structured logging.

        Args:
            alert: Alert to send.
        """
        log_method = {
            AlertSeverity.INFO: logger.info,
            AlertSeverity.WARNING: logger.warning,
            AlertSeverity.CRITICAL: logger.critical,
        }.get(alert.severity, logger.error)

        log_method(
            "DLQ alert: %s in queue %s",
            alert.error_type,
            alert.original_queue,
            extra={
                "dlq_alert": alert.to_dict(),
                "alert_severity": alert.severity.value,
                "original_queue": alert.original_queue,
                "retry_count": alert.retry_count,
            },
        )

    async def _send_email_alert(self, alert: DLQAlert) -> None:
        """Send alert via email.

        Args:
            alert: Alert to send.
        """
        if not self.config.email_recipients:
            logger.debug("No email recipients configured for DLQ alerts")
            return

        email_service = self._get_email_service()
        if email_service is None:
            logger.warning("Email service not available for DLQ alerts")
            return

        try:
            await email_service.send(
                to=self.config.email_recipients,
                subject=alert.format_subject(),
                body=alert.format_body(),
                priority=EmailPriority.HIGH
                if alert.severity == AlertSeverity.CRITICAL
                else EmailPriority.NORMAL,
                tags=["dlq-alert", f"severity:{alert.severity.value}"],
                metadata={
                    "queue": alert.original_queue,
                    "error_type": alert.error_type,
                },
            )
            logger.debug(
                "DLQ email alert sent",
                extra={"recipients": self.config.email_recipients},
            )
        except Exception as e:
            logger.exception(
                "Failed to send DLQ email alert: %s",
                str(e),
            )

    async def _send_webhook_alert(self, alert: DLQAlert) -> None:
        """Send alert via webhook (e.g., Slack, PagerDuty).

        Args:
            alert: Alert to send.
        """
        if not self.config.webhook_url:
            logger.debug("No webhook URL configured for DLQ alerts")
            return

        try:
            import httpx

            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            # Format payload for common webhook formats
            payload = {
                "text": alert.format_subject(),
                "attachments": [
                    {
                        "color": self._severity_color(alert.severity),
                        "fields": [
                            {"title": "Queue", "value": alert.original_queue, "short": True},
                            {"title": "Error Type", "value": alert.error_type, "short": True},
                            {
                                "title": "Retry Count",
                                "value": str(alert.retry_count),
                                "short": True,
                            },
                            {"title": "Severity", "value": alert.severity.value, "short": True},
                            {
                                "title": "Error Message",
                                "value": alert.error_message,
                                "short": False,
                            },
                        ],
                    },
                ],
                # Also include structured data for non-Slack webhooks
                "alert": alert.to_dict(),
            }

            response = await self._http_client.post(
                self.config.webhook_url,
                json=payload,
            )
            response.raise_for_status()

            logger.debug(
                "DLQ webhook alert sent",
                extra={"url": self.config.webhook_url},
            )
        except ImportError:
            logger.warning("httpx not installed, cannot send webhook alerts")
        except Exception as e:
            logger.exception(
                "Failed to send DLQ webhook alert: %s",
                str(e),
            )

    def _severity_color(self, severity: AlertSeverity) -> str:
        """Get color code for alert severity (for Slack/webhooks).

        Args:
            severity: Alert severity.

        Returns:
            Hex color code.
        """
        return {
            AlertSeverity.INFO: "#36a64f",  # Green
            AlertSeverity.WARNING: "#ffcc00",  # Yellow
            AlertSeverity.CRITICAL: "#ff0000",  # Red
        }.get(severity, "#808080")

    def _get_email_service(self) -> EmailService | None:
        """Get email service instance (lazy loading).

        Returns:
            Email service or None if not available.
        """
        if self._email_service is not None:
            return self._email_service

        try:
            from example_service.infra.email.service import get_email_service

            self._email_service = get_email_service()
            return self._email_service
        except Exception as e:
            logger.debug("Could not get email service: %s", str(e))
            return None

    def _record_alert_metrics(self, alert: DLQAlert) -> None:
        """Record alert in Prometheus metrics.

        Args:
            alert: Alert that was sent.
        """
        try:
            from .metrics import dlq_routed_total

            dlq_routed_total.labels(
                queue=alert.original_queue,
                reason=alert.error_type,
            ).inc()
        except Exception as e:
            logger.debug("Failed to record DLQ metrics: %s", str(e))  # Metrics are best-effort

    async def close(self) -> None:
        """Close any open resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


# Module-level alerter instance
_alerter: DLQAlerter | None = None


@lru_cache(maxsize=1)
def get_default_alert_config() -> AlertConfig:
    """Get default alert configuration from settings.

    Returns:
        AlertConfig with settings-based defaults.
    """
    try:
        from example_service.core.settings import get_app_settings

        settings = get_app_settings()

        # Build channels list from settings
        channels = [AlertChannel.LOG]
        email_recipients: list[str] = []

        if hasattr(settings, "dlq_alert_email") and settings.dlq_alert_email:
            channels.append(AlertChannel.EMAIL)
            email_recipients = [settings.dlq_alert_email]

        if hasattr(settings, "dlq_webhook_url") and settings.dlq_webhook_url:
            channels.append(AlertChannel.WEBHOOK)

        return AlertConfig(
            enabled=getattr(settings, "dlq_alerts_enabled", True),
            channels=channels,
            email_recipients=email_recipients,
            webhook_url=getattr(settings, "dlq_webhook_url", None),
            rate_limit_seconds=getattr(settings, "dlq_alert_rate_limit", 60),
            critical_threshold=getattr(settings, "dlq_critical_threshold", 5),
        )
    except Exception:
        # Return safe defaults if settings not available
        return AlertConfig()


def get_dlq_alerter() -> DLQAlerter:
    """Get or create the DLQ alerter singleton.

    Returns:
        Configured DLQAlerter instance.
    """
    global _alerter
    if _alerter is None:
        config = get_default_alert_config()
        _alerter = DLQAlerter(config)
    return _alerter


__all__ = [
    "AlertChannel",
    "AlertConfig",
    "AlertSeverity",
    "DLQAlert",
    "DLQAlerter",
    "RateLimiter",
    "get_default_alert_config",
    "get_dlq_alerter",
]
