"""Prometheus metrics endpoint for observability.

This module exposes Prometheus-compatible metrics for monitoring and alerting.
The endpoint is designed for scraping by Prometheus, Grafana Agent, or other
OpenMetrics-compatible collectors.

Endpoints:
    GET /metrics - Prometheus scrape endpoint returning OpenMetrics format

Metrics Exposed:
    HTTP Request Metrics:
        - http_requests_total - Total request count by method, path, status
        - http_request_duration_seconds - Request latency histogram with exemplars
        - http_requests_in_progress - Currently processing requests gauge

    Database Metrics:
        - db_connections_total - Connection pool statistics
        - db_query_duration_seconds - Query execution time with exemplars

    Cache Metrics:
        - cache_hits_total / cache_misses_total - Cache hit ratio tracking
        - cache_operation_duration_seconds - Redis operation latency

    Messaging Metrics:
        - rabbitmq_messages_published_total - Messages sent to broker
        - rabbitmq_messages_consumed_total - Messages processed

    Task Metrics:
        - taskiq_tasks_total - Background task execution counts
        - taskiq_task_duration_seconds - Task execution time

    Application Info:
        - app_info - Service version, name, and environment labels

Example Prometheus Configuration:
    ```yaml
    scrape_configs:
      - job_name: 'example-service'
        static_configs:
          - targets: ['localhost:8000']
        metrics_path: '/metrics'
        scrape_interval: 15s
    ```

Note:
    All histogram and counter metrics support exemplars for distributed
    tracing correlation. This enables click-through from metrics to
    traces in Grafana when using Tempo or similar backends.
"""

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
