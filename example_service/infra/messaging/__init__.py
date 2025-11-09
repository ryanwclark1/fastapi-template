"""Message broker infrastructure for event-driven communication."""
from __future__ import annotations

from example_service.infra.messaging.broker import broker, get_broker

__all__ = ["broker", "get_broker"]
