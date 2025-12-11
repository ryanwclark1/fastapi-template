"""Tests for MetricsMiddleware."""

from __future__ import annotations

import types

import pytest
from starlette.requests import Request
from starlette.responses import Response

from example_service.app.middleware.metrics import MetricsMiddleware


class DummyMetric:
    def __init__(self):
        self.calls = []

    def labels(self, **kwargs):
        self.calls.append(("labels", kwargs))
        return self

    def inc(self, exemplar=None):
        self.calls.append(("inc", exemplar))

    def dec(self):
        self.calls.append(("dec", None))

    def observe(self, value, exemplar=None):
        self.calls.append(("observe", value, exemplar))


@pytest.mark.asyncio
async def test_metrics_middleware_records_metrics(monkeypatch: pytest.MonkeyPatch):
    duration_metric = DummyMetric()
    total_metric = DummyMetric()
    in_progress = DummyMetric()

    monkeypatch.setattr(
        "example_service.app.middleware.metrics.http_request_duration_seconds",
        duration_metric,
    )
    monkeypatch.setattr(
        "example_service.app.middleware.metrics.http_requests_total",
        total_metric,
    )
    monkeypatch.setattr(
        "example_service.app.middleware.metrics.http_requests_in_progress",
        in_progress,
    )

    span_context = types.SimpleNamespace(is_valid=True, trace_id=1234)
    span = types.SimpleNamespace(get_span_context=lambda: span_context)
    monkeypatch.setattr("example_service.app.middleware.metrics.trace.get_current_span", lambda: span)

    async def call_next(request):
        return Response("ok", status_code=201)

    middleware = MetricsMiddleware(app=None)
    request = Request(
        {
            "type": "http",
            "path": "/api/items/1",
            "method": "GET",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
        },
    )
    request.scope["route"] = types.SimpleNamespace(path="/api/items/{id}")

    response = await middleware.dispatch(request, call_next)

    assert response.headers.get("X-Process-Time") is not None
    assert any(call[0] == "observe" for call in duration_metric.calls)
    assert any(call[0] == "inc" for call in total_metric.calls)
    assert ("dec", None) in in_progress.calls
