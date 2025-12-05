"""Metrics infrastructure for Prometheus monitoring."""

from __future__ import annotations

from prometheus_client import generate_latest

from example_service.infra.metrics import availability, business, tracking
from example_service.infra.metrics.prometheus import REGISTRY

__all__ = [
    "REGISTRY",
    "availability",
    "business",
    "generate_latest",
    "tracking",
]
