"""Tests for DebugMiddleware."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Scope

from example_service.app.middleware.debug import DebugMiddleware


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {
        "type": "http",
        "path": "/debug",
        "method": "GET",
        "headers": headers or [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
    }


@pytest.mark.asyncio
async def test_debug_middleware_adds_trace_headers(monkeypatch: pytest.MonkeyPatch):
    captured_context: dict = {}

    async def app(scope, receive, send):
        # immediate response
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = DebugMiddleware(app, header_prefix="X-")

    # Patch set_log_context to capture
    monkeypatch.setattr(
        "example_service.app.middleware.debug.set_log_context",
        lambda **kwargs: captured_context.update(kwargs),
    )

    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request"}

    await middleware(_scope(), receive, send)

    start = next(msg for msg in messages if msg["type"] == "http.response.start")
    header_keys = {k for k, _ in start["headers"]}
    assert b"X-Trace-Id".lower() in header_keys
    assert b"X-Span-Id".lower() in header_keys
    assert captured_context["path"] == "/debug"


@pytest.mark.asyncio
async def test_debug_middleware_respects_existing_trace_id():
    async def call_next(request):
        return Response("ok", status_code=204)

    middleware = DebugMiddleware(lambda scope, receive, send: None, enabled=True)
    request = Request(_scope(headers=[(b"x-trace-id", b"existing-trace")]))

    response = await middleware.dispatch(request, call_next)

    assert isinstance(response, Response)
    assert response.status_code == 204
    assert response.headers["X-Trace-Id"] == "existing-trace"


@pytest.mark.asyncio
async def test_debug_middleware_short_circuits_when_disabled():
    async def call_next(request):
        return Response("ok", status_code=200)

    middleware = DebugMiddleware(lambda scope, receive, send: None, enabled=False)
    request = Request(_scope())

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
