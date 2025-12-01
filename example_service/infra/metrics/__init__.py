"""Metrics infrastructure for Prometheus monitoring."""

from __future__ import annotations

from example_service.infra.metrics import business, tracking
from example_service.infra.metrics.prometheus import REGISTRY

__all__ = [
    "REGISTRY",
    "business",
    "tracking",
]
