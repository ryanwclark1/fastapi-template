"""Tests for RateLimitMiddleware behavior."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from example_service.app.middleware.rate_limit import RateLimitMiddleware


class StubLimiter:
    """Async limiter stub with configurable responses."""

    def __init__(
        self,
        *,
        allowed: bool = True,
        metadata: dict[str, Any] | None = None,
        error: Exception | None = None,
    ):
        self.allowed = allowed
        self.metadata = metadata or {"limit": 5, "remaining": 4, "reset": 30, "retry_after": 10}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def check_limit(self, **kwargs: Any) -> tuple[bool, dict[str, Any]]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.allowed, self.metadata


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Provide an async test client with the rate limit middleware configured."""
    limiter = StubLimiter()
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(RateLimitMiddleware, limiter=limiter, default_limit=5, default_window=60)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client._limiter = limiter  # type: ignore[attr-defined]
        yield client


@pytest.mark.asyncio
async def test_allows_request_and_sets_headers(client: AsyncClient) -> None:
    response = await client.get("/ping")
    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == "5"
    assert response.headers["x-ratelimit-remaining"] == "4"
    assert response.headers["x-ratelimit-reset"] == "30"
    limiter: StubLimiter = client._limiter  # type: ignore[attr-defined]
    assert limiter.calls
    assert limiter.calls[0]["endpoint"] == "/ping"


@pytest.mark.asyncio
async def test_returns_json_when_rate_limit_exceeded() -> None:
    limiter = StubLimiter(allowed=False)
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(RateLimitMiddleware, limiter=limiter, default_limit=1, default_window=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping")

    assert response.status_code == 429
    body = response.json()
    assert "Rate limit exceeded" in body["detail"]
    assert response.headers["Retry-After"] == "10"
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "4"
    assert response.headers["X-RateLimit-Reset"] == "30"


@pytest.mark.asyncio
async def test_fail_open_when_limiter_errors() -> None:
    limiter = StubLimiter(error=RuntimeError("redis down"))
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(RateLimitMiddleware, limiter=limiter, default_limit=1, default_window=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping")

    assert response.status_code == 200
    # Headers omitted when rate limit metadata missing due to fail-open path
    assert "x-ratelimit-limit" not in response.headers


@pytest.mark.asyncio
async def test_default_key_function_uses_forwarded_header(client: AsyncClient) -> None:
    response = await client.get("/ping", headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"})
    assert response.status_code == 200
    limiter: StubLimiter = client._limiter  # type: ignore[attr-defined]
    assert limiter.calls[-1]["key"].startswith("ip:10.0.0.1")


@pytest.mark.asyncio
async def test_middleware_skips_when_disabled() -> None:
    limiter = StubLimiter()
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        enabled=False,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping")

    assert response.status_code == 200
    assert limiter.calls == []  # limiter never invoked


@pytest.mark.asyncio
async def test_middleware_skips_exempt_paths() -> None:
    limiter = StubLimiter()
    app = FastAPI()

    @app.get("/health/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        exempt_paths=["/health"],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ping")

    assert response.status_code == 200
    assert limiter.calls == []
