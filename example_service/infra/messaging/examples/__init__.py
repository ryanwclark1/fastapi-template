"""Faststream example implementations.

This package contains working examples of different Faststream patterns:
- Trigger-based: Event-driven message processing
- Temporal-based: Time-based scheduled message processing
"""

from .temporal import schedule_periodic_task, scheduled_health_check
from .trigger import (
    publish_user_created_event,
    publish_user_notification,
    user_created_handler,
    user_notification_handler,
)

__all__ = [
    # Trigger-based examples
    "user_created_handler",
    "user_notification_handler",
    "publish_user_created_event",
    "publish_user_notification",
    # Temporal-based examples
    "scheduled_health_check",
    "schedule_periodic_task",
]
