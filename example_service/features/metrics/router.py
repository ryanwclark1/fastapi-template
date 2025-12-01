"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from example_service.infra.metrics.prometheus import REGISTRY

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics in OpenMetrics format with exemplar support.

    Returns metrics for scraping by Prometheus, including:
    - HTTP request metrics (rate, duration, in-progress) with trace exemplars
    - Database metrics (connections, query duration) with trace exemplars
    - Cache metrics (hits, misses, operation latency) with trace exemplars
    - RabbitMQ metrics (messages published/consumed)
    - Taskiq metrics (task execution, duration, status)
    - Application info (version, service, environment)

    All histograms and counters support exemplars for trace correlation,
    enabling click-through from metrics to traces in Grafana.

    Returns:
        Response with Prometheus metrics in OpenMetrics format.
    """
    data = generate_latest(REGISTRY)
    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
