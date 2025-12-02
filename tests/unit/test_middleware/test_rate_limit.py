"""Tests for rate limit middleware."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from example_service.app.middleware import rate_limit as rl
from example_service.core.exceptions import RateLimitException


class DummyLimiter:
    def __init__(
        self, allowed: bool = True, metadata: dict | None = None, exc: Exception | None = None
    ):
        self.allowed = allowed
        self.metadata = metadata or {"limit": 5, "remaining": 4, "reset": 1, "retry_after": 1}
        self.exc = exc
        self.called_with: list[dict] = []

    async def check_limit(self, **kwargs):
        self.called_with.append(kwargs)
        if self.exc:
            raise self.exc
        return self.allowed, self.metadata


def _basic_scope(path: str = "/"):
    return {"type": "http", "path": path, "method": "GET", "headers": []}


@pytest.mark.asyncio
async def test_rate_limit_injects_headers_on_success():
    send_messages = []

    async def send(message):
        send_messages.append(message)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    limiter = DummyLimiter(allowed=True)
    middleware = rl.RateLimitMiddleware(app, limiter=limiter)

    async def receive():
        return {"type": "http.request"}

    await middleware(_basic_scope("/api"), receive, send)

    # First message is start; should include rate limit headers
    start = next(msg for msg in send_messages if msg["type"] == "http.response.start")
    header_keys = {k for k, _ in start["headers"]}
    assert b"x-ratelimit-limit" in header_keys
    assert limiter.called_with
    assert limiter.called_with[0]["endpoint"] == "/api"


@pytest.mark.asyncio
async def test_rate_limit_returns_json_when_exceeded():
    send_messages = []

    async def send(message):
        send_messages.append(message)

    async def receive():
        return {"type": "http.request"}

    async def app(scope, receive, send):  # pragma: no cover - not reached
        raise AssertionError("Should not call downstream app on limit")

    exc = RateLimitException(
        detail="nope",
        instance="/api",
        extra={"retry_after": 2, "limit": 1, "remaining": 0, "reset": 0},
    )
    limiter = DummyLimiter(allowed=False, metadata=exc.extra)
    middleware = rl.RateLimitMiddleware(app, limiter=limiter)

    await middleware(_basic_scope("/api"), receive, send)

    body = next(msg["body"] for msg in send_messages if msg["type"] == "http.response.body")
    payload = json.loads(body)
    assert payload["detail"] == "Rate limit exceeded. Retry after 2 seconds"


@pytest.mark.asyncio
async def test_rate_limit_fail_open_on_error(monkeypatch: pytest.MonkeyPatch):
    send_messages = []

    async def send(message):
        send_messages.append(message)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    limiter = DummyLimiter(exc=RuntimeError("redis down"))
    middleware = rl.RateLimitMiddleware(app, limiter=limiter)

    async def receive():
        return {"type": "http.request"}

    await middleware(_basic_scope("/api"), receive, send)

    assert any(msg["type"] == "http.response.start" for msg in send_messages)


def test_default_key_func_uses_forwarded_header():
    scope = _basic_scope("/api")
    scope["headers"] = [(b"x-forwarded-for", b"10.0.0.1, 9.9.9.9")]
    request = Request(scope)
    key = rl.RateLimitMiddleware._default_key_func(request)
    assert key == "ip:10.0.0.1"
