"""Event infrastructure for reliable event delivery.

This package provides the infrastructure for the transactional outbox pattern:
- EventOutbox model for storing pending events
- OutboxProcessor for publishing events to the message broker
- Outbox repository for CRUD operations
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
