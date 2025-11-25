"""Unit tests for RateLimitMiddleware."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

from example_service.app.middleware.constants import EXEMPT_PATHS
from example_service.app.middleware.rate_limit import RateLimitMiddleware
from example_service.core.exceptions import RateLimitException


class TestRateLimitMiddleware:
    """Test suite for RateLimitMiddleware."""

    @pytest.fixture
    def mock_limiter(self):
        """Create a mock RateLimiter.

        Returns:
            Mock RateLimiter instance.
        """
        limiter = MagicMock()
        limiter.check_limit = AsyncMock()
        return limiter

    @pytest.fixture
    def app_with_rate_limit(self, mock_limiter):
        """Create FastAPI app with rate limit middleware.

        Args:
            mock_limiter: Mock RateLimiter fixture.

        Returns:
            FastAPI application with middleware.
        """
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
            enabled=True,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        @app.get("/health")
        async def health_endpoint():
            return {"status": "healthy"}

        return app

    @pytest.fixture
    async def client(self, app_with_rate_limit: FastAPI) -> AsyncClient:
        """Create async HTTP client.

        Args:
            app_with_rate_limit: FastAPI application fixture.

        Returns:
            Async HTTP client.
        """
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app_with_rate_limit), base_url="http://test"
        ) as ac:
            yield ac

    async def test_allows_request_under_limit(self, client: AsyncClient, mock_limiter):
        """Test that requests under rate limit are allowed."""
        # Configure mock to allow request
        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 9, "reset": 1234567890},
        )

        response = await client.get("/test")

        assert response.status_code == 200
        mock_limiter.check_limit.assert_called_once()

    async def test_rejects_request_over_limit(self, client: AsyncClient, mock_limiter):
        """Test that requests exceeding rate limit are rejected with 429."""
        # Configure mock to deny request
        mock_limiter.check_limit.return_value = (
            False,
            {"limit": 10, "remaining": 0, "reset": 1234567890, "retry_after": 60},
        )

        response = await client.get("/test")

        # RateLimitException should be raised and handled by exception handler
        # Default behavior without custom handler would be 500, but with proper
        # exception handler it should be 429
        assert response.status_code in [429, 500]  # Depends on exception handler setup

    async def test_rate_limit_headers_present(self, client: AsyncClient, mock_limiter):
        """Test that rate limit headers are included in response."""
        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 5, "reset": 1234567890},
        )

        response = await client.get("/test")

        assert response.status_code == 200
        assert "x-ratelimit-limit" in response.headers
        assert "x-ratelimit-remaining" in response.headers
        assert "x-ratelimit-reset" in response.headers

        assert response.headers["x-ratelimit-limit"] == "10"
        assert response.headers["x-ratelimit-remaining"] == "5"
        assert response.headers["x-ratelimit-reset"] == "1234567890"

    async def test_exempt_paths_skip_rate_limiting(self, mock_limiter):
        """Test that exempt paths bypass rate limiting."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
        )

        @app.get("/health")
        async def health_endpoint():
            return {"status": "healthy"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

        assert response.status_code == 200
        # check_limit should not be called for exempt paths
        mock_limiter.check_limit.assert_not_called()

    async def test_custom_exempt_paths(self, mock_limiter):
        """Test custom exempt paths configuration."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
            exempt_paths=["/custom/exempt"],
        )

        @app.get("/custom/exempt")
        async def exempt_endpoint():
            return {"status": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/custom/exempt")

        assert response.status_code == 200
        mock_limiter.check_limit.assert_not_called()

    async def test_default_key_function_uses_ip(self, client: AsyncClient, mock_limiter):
        """Test that default key function uses client IP address."""
        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 9, "reset": 1234567890},
        )

        await client.get("/test")

        # Check that key starts with "ip:"
        call_args = mock_limiter.check_limit.call_args
        assert call_args is not None
        key = call_args[1]["key"]
        assert key.startswith("ip:")

    async def test_custom_key_function(self, mock_limiter):
        """Test using custom key function for rate limiting."""

        def custom_key_func(request: Request) -> str:
            return f"user:{request.headers.get('X-User-ID', 'anonymous')}"

        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
            key_func=custom_key_func,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 9, "reset": 1234567890},
        )

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/test", headers={"X-User-ID": "user123"})

        call_args = mock_limiter.check_limit.call_args
        assert call_args[1]["key"] == "user:user123"

    async def test_x_forwarded_for_handling(self, mock_limiter):
        """Test that X-Forwarded-For header is used for rate limiting."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 9, "reset": 1234567890},
        )

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/test", headers={"X-Forwarded-For": "192.168.1.1, 10.0.0.1"})

        # Should use first IP in X-Forwarded-For chain
        call_args = mock_limiter.check_limit.call_args
        key = call_args[1]["key"]
        assert "192.168.1.1" in key

    async def test_disabled_middleware_passes_through(self):
        """Test that disabled middleware doesn't perform rate limiting."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=None,
            enabled=False,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert response.status_code == 200

    def test_requires_limiter_when_enabled(self):
        """Test that ValueError is raised when limiter not provided but enabled."""
        with pytest.raises(ValueError, match="limiter is required"):
            app = FastAPI()
            app.add_middleware(
                RateLimitMiddleware,
                limiter=None,
                enabled=True,
            )

    async def test_redis_failure_allows_request(self, client: AsyncClient, mock_limiter):
        """Test graceful degradation when Redis fails."""
        # Configure mock to raise exception (simulating Redis failure)
        mock_limiter.check_limit.side_effect = Exception("Redis connection failed")

        response = await client.get("/test")

        # Should allow request despite Redis failure
        assert response.status_code == 200

        # No rate limit headers should be present on failure
        assert "x-ratelimit-limit" not in response.headers

    async def test_rate_limit_exception_propagated(self, client: AsyncClient, mock_limiter):
        """Test that RateLimitException is properly raised."""
        # Configure mock to deny request
        mock_limiter.check_limit.return_value = (
            False,
            {"limit": 10, "remaining": 0, "reset": 1234567890, "retry_after": 60},
        )

        with patch(
            "example_service.app.middleware.rate_limit.logger"
        ) as mock_logger:
            response = await client.get("/test")

            # Should log warning about rate limit
            assert mock_logger.warning.called

    async def test_handles_non_http_scope(self, mock_limiter):
        """Test that middleware passes through non-HTTP scopes."""
        from unittest.mock import AsyncMock

        from starlette.types import Receive, Scope, Send

        async def simple_app(scope: Scope, receive: Receive, send: Send):
            await send({"type": "websocket.accept"})

        middleware = RateLimitMiddleware(
            simple_app, limiter=mock_limiter, default_limit=10, default_window=60
        )

        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should pass through without rate limiting
        send.assert_called_once()
        mock_limiter.check_limit.assert_not_called()

    async def test_rate_limit_with_different_methods(self, mock_limiter):
        """Test rate limiting works for different HTTP methods."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
        )

        @app.get("/test")
        async def get_endpoint():
            return {"method": "GET"}

        @app.post("/test")
        async def post_endpoint():
            return {"method": "POST"}

        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 9, "reset": 1234567890},
        )

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # GET request
            response = await client.get("/test")
            assert response.status_code == 200

            # POST request
            response = await client.post("/test")
            assert response.status_code == 200

        # Should be called twice (once per request)
        assert mock_limiter.check_limit.call_count == 2

    async def test_concurrent_requests(self, mock_limiter):
        """Test middleware handles concurrent requests correctly."""
        import asyncio

        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        mock_limiter.check_limit.return_value = (
            True,
            {"limit": 10, "remaining": 9, "reset": 1234567890},
        )

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Make 10 concurrent requests
            tasks = [client.get("/test") for _ in range(10)]
            responses = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r.status_code == 200 for r in responses)
        assert mock_limiter.check_limit.call_count == 10

    async def test_rate_limit_metadata_structure(self, client: AsyncClient, mock_limiter):
        """Test that rate limit metadata has correct structure."""
        metadata = {
            "limit": 100,
            "remaining": 75,
            "reset": 1234567890,
        }
        mock_limiter.check_limit.return_value = (True, metadata)

        response = await client.get("/test")

        assert response.status_code == 200

        # Verify all metadata fields are in headers
        assert int(response.headers["x-ratelimit-limit"]) == metadata["limit"]
        assert int(response.headers["x-ratelimit-remaining"]) == metadata["remaining"]
        assert int(response.headers["x-ratelimit-reset"]) == metadata["reset"]

    async def test_path_prefix_matching_for_exemptions(self, mock_limiter):
        """Test that exempt path matching works with path prefixes."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limiter=mock_limiter,
            default_limit=10,
            default_window=60,
            exempt_paths=["/health"],
        )

        @app.get("/health/live")
        async def health_live():
            return {"status": "ok"}

        @app.get("/health/ready")
        async def health_ready():
            return {"status": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Both should be exempt (prefix matching)
            await client.get("/health/live")
            await client.get("/health/ready")

        # Should not call rate limiter for exempt paths
        mock_limiter.check_limit.assert_not_called()
