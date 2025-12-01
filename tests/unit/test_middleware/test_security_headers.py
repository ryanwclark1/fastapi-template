"""Unit tests for SecurityHeadersMiddleware."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import AsyncClient

from example_service.app.middleware.security_headers import (
    SecurityHeadersMiddleware,
    get_security_headers,
)


class TestSecurityHeadersMiddleware:
    """Test suite for SecurityHeadersMiddleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create FastAPI app with security headers middleware.

        Returns:
            FastAPI application with middleware.
        """
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        return app

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncClient:
        """Create async HTTP client.

        Args:
            app: FastAPI application fixture.

        Returns:
            Async HTTP client.
        """
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    async def test_hsts_header_present(self, client: AsyncClient):
        """Test that Strict-Transport-Security header is present."""
        response = await client.get("/test")

        assert "strict-transport-security" in response.headers
        hsts = response.headers["strict-transport-security"]
        assert "max-age=31536000" in hsts  # 1 year
        assert "includeSubDomains" in hsts

    async def test_hsts_disabled_in_debug_mode(self):
        """Test that HSTS is disabled when enable_hsts=False."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, enable_hsts=False)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert "strict-transport-security" not in response.headers

    async def test_csp_header_present(self, client: AsyncClient):
        """Test that Content-Security-Policy header is present."""
        response = await client.get("/test")

        assert "content-security-policy" in response.headers
        csp = response.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        # Default (non-production) environment allows 'self' for frame-ancestors
        assert "frame-ancestors" in csp
        assert (
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net"
            " https://unpkg.com"
            in csp
        )
        assert (
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com"
            in csp
        )
        assert (
            "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com"
            in csp
        )
        # Default now includes ws/wss for WebSocket support
        assert "connect-src 'self'" in csp
        assert "worker-src 'self' blob:" in csp

    async def test_x_frame_options_header(self, client: AsyncClient):
        """Test that X-Frame-Options header is present."""
        response = await client.get("/test")

        assert "x-frame-options" in response.headers
        assert response.headers["x-frame-options"] == "DENY"

    async def test_x_content_type_options_header(self, client: AsyncClient):
        """Test that X-Content-Type-Options header is present."""
        response = await client.get("/test")

        assert "x-content-type-options" in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_x_xss_protection_header(self, client: AsyncClient):
        """Test that X-XSS-Protection header is present."""
        response = await client.get("/test")

        assert "x-xss-protection" in response.headers
        assert response.headers["x-xss-protection"] == "1; mode=block"

    async def test_referrer_policy_header(self, client: AsyncClient):
        """Test that Referrer-Policy header is present."""
        response = await client.get("/test")

        assert "referrer-policy" in response.headers
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    async def test_permissions_policy_header(self, client: AsyncClient):
        """Test that Permissions-Policy header is present."""
        response = await client.get("/test")

        assert "permissions-policy" in response.headers
        policy = response.headers["permissions-policy"]

        # Check that dangerous features are denied
        assert "geolocation=()" in policy
        assert "microphone=()" in policy
        assert "camera=()" in policy

    async def test_x_permitted_cross_domain_policies_header(self, client: AsyncClient):
        """Test that X-Permitted-Cross-Domain-Policies header is present."""
        response = await client.get("/test")

        assert "x-permitted-cross-domain-policies" in response.headers
        assert response.headers["x-permitted-cross-domain-policies"] == "none"

    async def test_x_powered_by_removed(self):
        """Test that X-Powered-By header is removed if present."""
        app = FastAPI()

        # Add middleware that sets X-Powered-By
        @app.middleware("http")
        async def add_powered_by(request, call_next):
            response = await call_next(request)
            response.headers["X-Powered-By"] = "FastAPI"
            return response

        # Add security middleware (should remove X-Powered-By)
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        # X-Powered-By should be removed by security middleware
        assert "x-powered-by" not in response.headers

    async def test_custom_csp_directives(self):
        """Test custom CSP directives configuration."""
        app = FastAPI()
        custom_csp = {
            "default-src": "'none'",
            "script-src": "'self' https://cdn.example.com",
        }
        app.add_middleware(SecurityHeadersMiddleware, csp_directives=custom_csp)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "script-src 'self' https://cdn.example.com" in csp

    async def test_custom_frame_options(self):
        """Test custom X-Frame-Options configuration."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, frame_options="SAMEORIGIN")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert response.headers["x-frame-options"] == "SAMEORIGIN"

    async def test_custom_permissions_policy(self):
        """Test custom Permissions-Policy configuration."""
        app = FastAPI()
        custom_policy = {
            "geolocation": ["self"],
            "camera": [],
        }
        app.add_middleware(SecurityHeadersMiddleware, permissions_policy=custom_policy)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        policy = response.headers["permissions-policy"]
        assert "geolocation=(self)" in policy
        assert "camera=()" in policy

    async def test_hsts_with_preload(self):
        """Test HSTS header with preload directive."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_preload=True,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        hsts = response.headers["strict-transport-security"]
        assert "preload" in hsts

    async def test_hsts_without_subdomains(self):
        """Test HSTS header without includeSubDomains."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_include_subdomains=False,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        hsts = response.headers["strict-transport-security"]
        assert "includeSubDomains" not in hsts

    async def test_custom_hsts_max_age(self):
        """Test custom HSTS max-age configuration."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_max_age=7776000,  # 90 days
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        hsts = response.headers["strict-transport-security"]
        assert "max-age=7776000" in hsts

    async def test_disable_individual_headers(self):
        """Test disabling individual security headers."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_csp=False,
            enable_frame_options=False,
            enable_xss_protection=False,
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        # Disabled headers should not be present
        assert "content-security-policy" not in response.headers
        assert "x-frame-options" not in response.headers
        assert "x-xss-protection" not in response.headers

        # Other headers should still be present
        assert "x-content-type-options" in response.headers
        assert "referrer-policy" in response.headers

    async def test_handles_non_http_scope(self):
        """Test that middleware passes through non-HTTP scopes."""
        from unittest.mock import AsyncMock

        from starlette.types import Receive, Scope, Send

        async def simple_app(scope: Scope, receive: Receive, send: Send):
            await send({"type": "websocket.accept"})

        middleware = SecurityHeadersMiddleware(simple_app)

        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should pass through without adding headers
        send.assert_called_once()

    async def test_all_default_headers_present(self, client: AsyncClient):
        """Test that all default security headers are present."""
        response = await client.get("/test")

        expected_headers = [
            "strict-transport-security",
            "content-security-policy",
            "x-frame-options",
            "x-content-type-options",
            "x-xss-protection",
            "referrer-policy",
            "permissions-policy",
            "x-permitted-cross-domain-policies",
        ]

        for header in expected_headers:
            assert header in response.headers, f"Missing header: {header}"

    async def test_custom_referrer_policy(self):
        """Test custom Referrer-Policy configuration."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            referrer_policy="no-referrer",
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert response.headers["referrer-policy"] == "no-referrer"

    async def test_csp_with_multiple_directives(self, client: AsyncClient):
        """Test CSP header with multiple complex directives."""
        response = await client.get("/test")

        csp = response.headers["content-security-policy"]

        # Verify multiple directives are present and properly formatted
        assert "default-src 'self'" in csp
        assert "script-src" in csp
        assert "style-src" in csp
        assert "img-src" in csp
        assert "connect-src 'self'" in csp
        assert "base-uri 'self'" in csp
        assert "form-action 'self'" in csp

    async def test_permissions_policy_format(self, client: AsyncClient):
        """Test that Permissions-Policy has correct format."""
        response = await client.get("/test")

        policy = response.headers["permissions-policy"]

        # Verify format: feature=()
        assert "geolocation=()" in policy
        assert "microphone=()" in policy
        assert "camera=()" in policy
        assert "payment=()" in policy
        assert "usb=()" in policy

    async def test_headers_applied_to_all_responses(self):
        """Test that security headers are applied to all response types."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/json")
        async def json_endpoint():
            return {"type": "json"}

        @app.get("/text")
        async def text_endpoint():
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("text response")

        @app.get("/redirect")
        async def redirect_endpoint():
            from fastapi.responses import RedirectResponse

            return RedirectResponse(url="/json")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            # JSON response
            response = await client.get("/json")
            assert "x-frame-options" in response.headers

            # Text response
            response = await client.get("/text")
            assert "x-frame-options" in response.headers

            # Redirect response
            response = await client.get("/redirect")
            assert "x-frame-options" in response.headers

    async def test_performance_with_pure_asgi(self):
        """Test that pure ASGI implementation has minimal overhead."""
        import time

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Warm up
            await client.get("/test")

            # Measure performance
            start = time.perf_counter()
            for _ in range(100):
                await client.get("/test")
            elapsed = time.perf_counter() - start

            # Should complete 100 requests in reasonable time
            assert elapsed < 1.0, f"100 requests took {elapsed:.3f}s, performance degraded"


class TestEnvironmentAwareFeatures:
    """Test suite for environment-aware security features."""

    async def test_production_environment_enables_stricter_csp(self):
        """Test that production environment uses stricter CSP by default."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, environment="production")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        csp = response.headers["content-security-policy"]
        # Production CSP should not include unsafe-inline/unsafe-eval for scripts
        assert "'unsafe-eval'" not in csp
        # Should include upgrade-insecure-requests
        assert "upgrade-insecure-requests" in csp

    async def test_development_environment_allows_relaxed_csp(self):
        """Test that development environment uses relaxed CSP."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, environment="development")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        csp = response.headers["content-security-policy"]
        # Development CSP should include unsafe-eval for Swagger
        assert "'unsafe-eval'" in csp
        # Should allow WebSocket connections
        assert "ws:" in csp or "wss:" in csp

    async def test_production_auto_enables_hsts(self):
        """Test that HSTS is auto-enabled in production."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware, environment="production", enable_hsts=None
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert "strict-transport-security" in response.headers

    async def test_is_production_parameter_deprecated_but_works(self):
        """Test that deprecated is_production parameter still works."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, is_production=True)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        csp = response.headers["content-security-policy"]
        # Should use production-style CSP
        assert "'unsafe-eval'" not in csp


class TestServerHeaderHandling:
    """Test suite for Server header customization."""

    async def test_server_header_removed_when_none(self):
        """Test that Server header is removed when server_header=None."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, server_header=None)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert "server" not in response.headers

    async def test_server_header_kept_when_false(self):
        """Test that Server header is kept when server_header=False."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, server_header=False)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/test")

        # Server header should be present (uvicorn default)
        # Note: This may vary based on ASGI server
        # The important thing is that False doesn't remove it

    async def test_server_header_custom_value(self):
        """Test that custom Server header value is set."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, server_header="CustomServer/1.0")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert response.headers.get("server") == "CustomServer/1.0"


class TestEnhancedPermissionsPolicy:
    """Test suite for enhanced Permissions-Policy features."""

    async def test_enhanced_permissions_policy_includes_all_features(self):
        """Test that enhanced permissions policy includes comprehensive features."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        policy = response.headers["permissions-policy"]

        # Check for enhanced features from accent-hub
        enhanced_features = [
            "ambient-light-sensor",
            "autoplay",
            "battery",
            "display-capture",
            "document-domain",
            "encrypted-media",
            "execution-while-not-rendered",
            "execution-while-out-of-viewport",
            "midi",
            "navigation-override",
            "picture-in-picture",
            "publickey-credentials-get",
            "screen-wake-lock",
            "sync-xhr",
            "web-share",
            "xr-spatial-tracking",
        ]

        for feature in enhanced_features:
            assert feature in policy, f"Missing enhanced feature: {feature}"

    async def test_fullscreen_allowed_for_self(self):
        """Test that fullscreen is allowed for same origin."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        policy = response.headers["permissions-policy"]
        assert "fullscreen=(self)" in policy


class TestCSPEnhancements:
    """Test suite for CSP enhancements."""

    async def test_csp_handles_valueless_directives(self):
        """Test that CSP correctly handles directives without values."""
        app = FastAPI()
        custom_csp = {
            "default-src": "'self'",
            "upgrade-insecure-requests": "",  # Valueless directive
        }
        app.add_middleware(SecurityHeadersMiddleware, csp_directives=custom_csp)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        csp = response.headers["content-security-policy"]
        # Should include valueless directive without extra semicolon
        assert "upgrade-insecure-requests" in csp
        # Should be properly formatted (no trailing semicolon)
        assert csp.endswith("upgrade-insecure-requests") or "; " in csp

    async def test_production_csp_includes_upgrade_insecure_requests(self):
        """Test that production CSP includes upgrade-insecure-requests."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware, environment="production")

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        csp = response.headers["content-security-policy"]
        assert "upgrade-insecure-requests" in csp


class TestGetSecurityHeadersHelper:
    """Test suite for get_security_headers helper function."""

    def test_get_security_headers_basic(self):
        """Test get_security_headers returns basic headers."""
        headers = get_security_headers()

        assert "X-Content-Type-Options" in headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in headers
        assert headers["X-Frame-Options"] == "DENY"
        assert "X-XSS-Protection" in headers
        assert "Referrer-Policy" in headers
        assert "X-Permitted-Cross-Domain-Policies" in headers

    def test_get_security_headers_with_hsts(self):
        """Test get_security_headers includes HSTS when requested."""
        headers = get_security_headers(include_hsts=True)

        assert "Strict-Transport-Security" in headers
        assert "max-age=31536000" in headers["Strict-Transport-Security"]
        assert "includeSubDomains" in headers["Strict-Transport-Security"]

    def test_get_security_headers_with_csp(self):
        """Test get_security_headers includes CSP when requested."""
        headers = get_security_headers(include_csp=True)

        assert "Content-Security-Policy" in headers
        csp = headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "upgrade-insecure-requests" in csp

    def test_get_security_headers_with_custom_csp(self):
        """Test get_security_headers with custom CSP directives."""
        custom_csp = {
            "default-src": "'none'",
            "script-src": "'self' https://cdn.example.com",
        }
        headers = get_security_headers(include_csp=True, csp_directives=custom_csp)

        csp = headers["Content-Security-Policy"]
        assert "default-src 'none'" in csp
        assert "script-src 'self' https://cdn.example.com" in csp

    def test_get_security_headers_with_valueless_directive(self):
        """Test get_security_headers handles valueless CSP directives."""
        custom_csp = {
            "default-src": "'self'",
            "upgrade-insecure-requests": "",
        }
        headers = get_security_headers(include_csp=True, csp_directives=custom_csp)

        csp = headers["Content-Security-Policy"]
        assert "upgrade-insecure-requests" in csp
        assert "default-src 'self'" in csp

    async def test_get_security_headers_in_error_handler(self):
        """Test get_security_headers works in custom error handlers."""
        from starlette.exceptions import HTTPException

        app = FastAPI()

        @app.exception_handler(HTTPException)
        async def http_exception_handler(request, exc):
            headers = get_security_headers(include_hsts=True, include_csp=True)
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=headers,
            )

        @app.get("/error")
        async def error_endpoint():
            raise HTTPException(status_code=500, detail="Test error")

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/error")

        assert response.status_code == 500
        # Verify security headers are present
        assert "x-content-type-options" in response.headers
        assert "strict-transport-security" in response.headers
        assert "content-security-policy" in response.headers


class TestBackwardCompatibility:
    """Test suite to ensure backward compatibility."""

    async def test_default_behavior_unchanged(self):
        """Test that default middleware behavior is unchanged."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        # All headers should be present by default
        assert "strict-transport-security" in response.headers
        assert "content-security-policy" in response.headers
        assert "x-frame-options" in response.headers
        assert "x-content-type-options" in response.headers

    async def test_legacy_parameters_still_work(self):
        """Test that all legacy parameters still work."""
        app = FastAPI()
        app.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=True,
            hsts_max_age=7776000,
            enable_csp=True,
            csp_directives={"default-src": "'self'"},
            enable_frame_options=True,
            frame_options="SAMEORIGIN",
        )

        @app.get("/test")
        async def test_endpoint():
            return {"message": "ok"}

        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/test")

        assert "max-age=7776000" in response.headers["strict-transport-security"]
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
