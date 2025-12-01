"""Faststream example implementations.

This package contains working examples of different Faststream patterns:

- Trigger-based: Event-driven message processing
- Temporal-based: Time-based scheduled message processing
- DLQ patterns: Dead Letter Queue handling and monitoring
- Exchange patterns: Topic, direct, and fanout exchange usage
- Retry patterns: Using utils.retry with FastStream handlers

Reference FastStream documentation:
    https://faststream.ag2.ai/latest/getting-started/
"""

from .dlq_patterns import (
    DLQMonitor,
    advanced_dlq_handler,
    extract_dlq_metadata,
    process_dlq_message,
    replay_dlq_message,
    should_replay_message,
    should_retry_exception,
)
from .exchange_patterns import (
    handle_all_example_events,
    handle_broadcast_queue1,
    handle_broadcast_queue2,
    handle_high_priority_tasks,
    handle_only_created_events,
    handle_order_events,
    handle_tenant_example_events,
    handle_user_events,
    publish_to_fanout_exchange,
    publish_to_topic_exchange,
)
from .retry_patterns import (
    handle_with_basic_retry,
    handle_with_custom_retry_condition,
    handle_with_exception_filter,
    handle_with_metrics,
    handle_with_retry_callback,
    handle_with_retry_exhaustion_handling,
    handle_with_smart_retry,
    on_retry_callback,
    should_retry_custom,
)
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
    # DLQ patterns
    "extract_dlq_metadata",
    "process_dlq_message",
    "replay_dlq_message",
    "should_replay_message",
    "should_retry_exception",
    "DLQMonitor",
    "advanced_dlq_handler",
    # Exchange patterns
    "handle_all_example_events",
    "handle_tenant_example_events",
    "handle_only_created_events",
    "handle_high_priority_tasks",
    "handle_broadcast_queue1",
    "handle_broadcast_queue2",
    "handle_user_events",
    "handle_order_events",
    "publish_to_topic_exchange",
    "publish_to_fanout_exchange",
    # Retry patterns
    "handle_with_basic_retry",
    "handle_with_exception_filter",
    "handle_with_retry_callback",
    "handle_with_custom_retry_condition",
    "handle_with_retry_exhaustion_handling",
    "handle_with_metrics",
    "handle_with_smart_retry",
    "on_retry_callback",
    "should_retry_custom",
]
