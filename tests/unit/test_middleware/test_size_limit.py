"""Tests for request size limit middleware."""

from __future__ import annotations

import json

import pytest

from example_service.app.middleware.size_limit import RequestSizeLimitMiddleware


@pytest.mark.asyncio
async def test_size_limit_blocks_large_requests():
    send_messages = []

    async def send(message):
        send_messages.append(message)

    async def dummy_app(scope, receive, send):  # pragma: no cover - should not be reached
        msg = "App should not be called for oversized requests"
        raise AssertionError(msg)

    middleware = RequestSizeLimitMiddleware(dummy_app, max_size=5)
    scope = {"type": "http", "headers": [(b"content-length", b"10")]}

    async def receive():
        return {"type": "http.request"}

    await middleware(scope, receive, send)

    statuses = [msg.get("status") for msg in send_messages if msg.get("type") == "http.response.start"]
    assert statuses == [413]
    body = next(msg["body"] for msg in send_messages if msg["type"] == "http.response.body")
    detail = json.loads(body)["detail"]
    assert "exceeds maximum" in detail


@pytest.mark.asyncio
async def test_size_limit_passes_through_when_within_limit():
    called = []

    async def send(message):  # pragma: no cover - send not used for pass through
        called.append(message)

    async def dummy_app(scope, receive, send):
        called.append(("app", scope["type"]))

    middleware = RequestSizeLimitMiddleware(dummy_app, max_size=100)
    scope = {"type": "http", "headers": [(b"content-length", b"50")]}

    async def receive():
        return {"type": "http.request"}

    await middleware(scope, receive, send)

    assert ("app", "http") in called
