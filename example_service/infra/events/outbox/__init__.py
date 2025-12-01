"""Transactional outbox pattern implementation.

The outbox pattern ensures reliable event publishing by:
1. Writing events to a database table in the same transaction as domain changes
2. Processing the outbox table asynchronously to publish to the message broker
3. Marking events as processed after successful publication

This guarantees at-least-once delivery semantics.
"""

from example_service.infra.events.outbox.models import EventOutbox
from example_service.infra.events.outbox.processor import (
    OutboxProcessor,
    start_outbox_processor,
    stop_outbox_processor,
)
from example_service.infra.events.outbox.repository import OutboxRepository

__all__ = [
    "EventOutbox",
    "OutboxProcessor",
    "OutboxRepository",
    "start_outbox_processor",
    "stop_outbox_processor",
]
