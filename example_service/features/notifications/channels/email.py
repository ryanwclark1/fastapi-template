"""Email channel dispatcher using EnhancedEmailService."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from example_service.features.notifications.channels.base import DeliveryResult
from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from example_service.features.notifications.models import (
        Notification,
        NotificationDelivery,
        UserNotificationPreference,
    )
    from example_service.infra.email.enhanced_service import EnhancedEmailService


class EmailChannelDispatcher:
    """Dispatcher for email notifications via EnhancedEmailService.

    Integrates with existing multi-provider email infrastructure (SMTP, SES, SendGrid, Mailgun).
    Tracks message IDs and delivery status.
    """

    def __init__(self, email_service: EnhancedEmailService | None = None) -> None:
        """Initialize with email service.

        Args:
            email_service: Optional email service (defaults to singleton)
        """
        from example_service.infra.email.enhanced_service import (
            get_enhanced_email_service,
        )

        self._email_service = email_service or get_enhanced_email_service()
        self._logger = get_logger()

    async def send(
        self,
        notification: Notification,
        delivery: NotificationDelivery,
    ) -> DeliveryResult:
        """Send notification via email.

        Args:
            notification: Notification with rendered content (title, body, body_html)
            delivery: Delivery record (will update email_message_id, email_recipient)

        Returns:
            DeliveryResult with email-specific metadata
        """
        start_time = time.time()

        try:
            # Get user's email address
            # NOTE: Fetch from user service/cache once available.
            # For now, assume it's in the notification context or user_id is email
            recipient = self._get_user_email(notification)

            if not recipient:
                return DeliveryResult(
                    success=False,
                    error_message="No email address found for user",
                    error_category="validation",
                )

            # Prepare email content
            subject = notification.title  # Already rendered from template
            body_text = notification.body
            body_html = notification.body_html

            # Send email via EnhancedEmailService
            result = await self._email_service.send_email(
                to_addresses=[recipient],
                subject=subject,
                body_text=body_text or "",
                body_html=body_html,
                tenant_id=notification.tenant_id,
            )

            # Calculate response time
            elapsed_ms = int((time.time() - start_time) * 1000)

            # Update delivery record
            delivery.email_recipient = recipient
            delivery.email_message_id = result.message_id if result.success else None
            delivery.response_time_ms = elapsed_ms

            if result.success:
                self._logger.info(
                    f"Email sent for notification {notification.id} to {recipient}",
                    extra={"message_id": result.message_id},
                )
                return DeliveryResult(
                    success=True,
                    response_time_ms=elapsed_ms,
                    metadata={
                        "message_id": result.message_id or "",
                        "recipient": recipient,
                        "provider": result.provider or "unknown",
                    },
                )

            self._logger.warning(
                f"Email delivery failed for notification {notification.id}: {result.error}",
            )

            return DeliveryResult(
                success=False,
                error_message=result.error or "Unknown email error",
                error_category="email_provider",
                response_time_ms=elapsed_ms,
                metadata={"recipient": recipient},
            )

        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.exception(
                f"Exception sending email for notification {notification.id}: {exc}",
            )

            return DeliveryResult(
                success=False,
                error_message=str(exc),
                error_category="exception",
                response_time_ms=elapsed_ms,
            )

    async def is_enabled_for_user(
        self,
        preferences: UserNotificationPreference | None,
    ) -> bool:
        """Check if email is enabled for user.

        Args:
            preferences: User preferences (None = use defaults)

        Returns:
            True if email channel is enabled
        """
        if preferences is None:
            # Default: email enabled
            return True

        return "email" in preferences.enabled_channels

    def get_channel_name(self) -> str:
        """Get channel identifier.

        Returns:
            Channel name: 'email'
        """
        return "email"

    def _get_user_email(self, notification: Notification) -> str | None:
        """Get user's email address.

        Args:
            notification: Notification instance

        Returns:
            Email address or None if not found
        """
        # Strategy 1: Check if email is in context_data
        if notification.context_data and "user_email" in notification.context_data:
            return notification.context_data["user_email"]

        # Strategy 2: Check if user_id is an email address
        if notification.user_id and "@" in notification.user_id:
            return notification.user_id

        # Strategy 3: TODO - Fetch from user service/accent-auth
        # For now, return None to indicate missing email
        self._logger.warning(
            f"Could not determine email for user {notification.user_id}",
        )
        return None
