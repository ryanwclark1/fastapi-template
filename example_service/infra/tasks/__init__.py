"""Background task infrastructure using Taskiq."""
from __future__ import annotations

from example_service.infra.tasks.broker import broker, get_broker

__all__ = ["broker", "get_broker"]
