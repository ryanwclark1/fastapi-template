"""Tests for MetricsMiddleware instrumentation."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from example_service.app.middleware.metrics import MetricsMiddleware


class StubMetric:
    """Simple metric stub capturing call details."""

    def __init__(self) -> None:
        self.labels_calls: list[dict[str, Any]] = []
        self.observe_calls: list[tuple[float, dict[str, Any] | None]] = []
        self.inc_calls: list[dict[str, Any] | None] = []
        self.dec_calls: list[dict[str, Any] | None] = []

    def labels(self, **label_kwargs: Any) -> StubMetric:
        self.labels_calls.append(label_kwargs)
        return self

    def observe(self, value: float, exemplar: dict[str, Any] | None = None) -> None:
        self.observe_calls.append((value, exemplar))

    def inc(self, exemplar: dict[str, Any] | None = None) -> None:
        self.inc_calls.append(exemplar)

    def dec(self, exemplar: dict[str, Any] | None = None) -> None:
        self.dec_calls.append(exemplar)


class DummySpanContext:
    def __init__(self, valid: bool, trace_id: int = 0) -> None:
        self._valid = valid
        self.trace_id = trace_id

    @property
    def is_valid(self) -> bool:
        return self._valid


class DummySpan:
    def __init__(self, context: DummySpanContext) -> None:
        self._context = context

    def get_span_context(self) -> DummySpanContext:
        return self._context


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient]:
    """Provide an async client with MetricsMiddleware and stubbed metrics."""
    duration_metric = StubMetric()
    total_metric = StubMetric()
    in_progress_metric = StubMetric()

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
        in_progress_metric,
    )

    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/items/{item_id}")
    async def get_item(item_id: int):
        return {"item_id": item_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        async_client._duration_metric = duration_metric  # type: ignore[attr-defined]
        async_client._total_metric = total_metric  # type: ignore[attr-defined]
        async_client._in_progress_metric = in_progress_metric  # type: ignore[attr-defined]
        yield async_client


@pytest.mark.asyncio
async def test_metrics_record_without_trace(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "example_service.app.middleware.metrics.trace.get_current_span",
        lambda: DummySpan(DummySpanContext(valid=False)),
    )

    response = await client.get("/items/123")
    assert response.status_code == 200
    assert "X-Process-Time" in response.headers

    duration_metric: StubMetric = client._duration_metric  # type: ignore[attr-defined]
    total_metric: StubMetric = client._total_metric  # type: ignore[attr-defined]
    in_progress: StubMetric = client._in_progress_metric  # type: ignore[attr-defined]

    assert duration_metric.labels_calls[-1]["endpoint"].startswith("/items")
    assert duration_metric.observe_calls[-1][1] is None  # no exemplar
    assert total_metric.labels_calls[-1]["status"] == 200
    assert total_metric.inc_calls[-1] is None
    assert len(in_progress.inc_calls) == len(in_progress.dec_calls) == 1


@pytest.mark.asyncio
async def test_metrics_include_exemplar_when_trace_present(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "example_service.app.middleware.metrics.trace.get_current_span",
        lambda: DummySpan(DummySpanContext(valid=True, trace_id=0xABC)),
    )

    response = await client.get("/items/456")
    assert response.status_code == 200

    duration_metric: StubMetric = client._duration_metric  # type: ignore[attr-defined]
    total_metric: StubMetric = client._total_metric  # type: ignore[attr-defined]

    _, exemplar = duration_metric.observe_calls[-1]
    assert exemplar == {"trace_id": format(0xABC, "032x")}

    total_exemplar = total_metric.inc_calls[-1]
    assert total_exemplar == {"trace_id": format(0xABC, "032x")}
