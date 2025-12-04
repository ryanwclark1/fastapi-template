"""Unit tests for TenantMiddleware and tenant identification strategies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient

from example_service.app.middleware.tenant import (
    HeaderTenantStrategy,
    JWTClaimTenantStrategy,
    PathPrefixTenantStrategy,
    SubdomainTenantStrategy,
    TenantIdentificationStrategy,
    TenantMiddleware,
    clear_tenant_context,
    get_tenant_context,
    require_tenant,
    set_tenant_context,
)
from example_service.core.schemas.tenant import TenantContext


class TestTenantContextFunctions:
    """Test tenant context utility functions."""

    def test_get_tenant_context_returns_none_when_not_set(self) -> None:
        """Test that get_tenant_context returns None when not set."""
        clear_tenant_context()
        assert get_tenant_context() is None

    def test_set_and_get_tenant_context(self) -> None:
        """Test setting and getting tenant context."""
        clear_tenant_context()
        context = TenantContext(tenant_id="test-tenant", identified_by="test")
        set_tenant_context(context)

        retrieved = get_tenant_context()
        assert retrieved is not None
        assert retrieved.tenant_id == "test-tenant"
        assert retrieved.identified_by == "test"

    def test_clear_tenant_context(self) -> None:
        """Test clearing tenant context."""
        context = TenantContext(tenant_id="test-tenant")
        set_tenant_context(context)
        assert get_tenant_context() is not None

        clear_tenant_context()
        assert get_tenant_context() is None

    def test_require_tenant_raises_when_not_set(self) -> None:
        """Test that require_tenant raises RuntimeError when context not set."""
        clear_tenant_context()
        with pytest.raises(RuntimeError, match="No tenant context available"):
            require_tenant()

    def test_require_tenant_returns_context_when_set(self) -> None:
        """Test that require_tenant returns context when set."""
        clear_tenant_context()
        context = TenantContext(tenant_id="test-tenant")
        set_tenant_context(context)

        retrieved = require_tenant()
        assert retrieved.tenant_id == "test-tenant"


class TestHeaderTenantStrategy:
    """Test HeaderTenantStrategy."""

    @pytest.mark.asyncio
    async def test_identify_from_default_header(self) -> None:
        """Test identifying tenant from default Accent-Tenant header."""
        strategy = HeaderTenantStrategy()
        request = MagicMock(spec=Request)
        request.headers = {"accent-tenant": "tenant-123"}

        tenant_id = await strategy.identify(request)
        assert tenant_id == "tenant-123"

    @pytest.mark.asyncio
    async def test_identify_from_custom_header(self) -> None:
        """Test identifying tenant from custom header."""
        strategy = HeaderTenantStrategy(header_name="X-Tenant-ID")
        request = MagicMock(spec=Request)
        request.headers = {"x-tenant-id": "custom-tenant"}

        tenant_id = await strategy.identify(request)
        assert tenant_id == "custom-tenant"

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_header_missing(self) -> None:
        """Test that identify returns None when header is missing."""
        strategy = HeaderTenantStrategy()
        request = MagicMock(spec=Request)
        request.headers = {}

        tenant_id = await strategy.identify(request)
        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_identify_case_insensitive(self) -> None:
        """Test that header matching is case-insensitive."""
        strategy = HeaderTenantStrategy()
        request = MagicMock(spec=Request)
        request.headers = {"ACCENT-TENANT": "tenant-123"}

        tenant_id = await strategy.identify(request)
        assert tenant_id == "tenant-123"


class TestSubdomainTenantStrategy:
    """Test SubdomainTenantStrategy."""

    @pytest.mark.asyncio
    async def test_identify_from_subdomain(self) -> None:
        """Test identifying tenant from subdomain."""
        strategy = SubdomainTenantStrategy(base_domain="example.com")
        request = MagicMock(spec=Request)
        request.headers = {"host": "acme-corp.example.com"}

        tenant_id = await strategy.identify(request)
        assert tenant_id == "acme-corp"

    @pytest.mark.asyncio
    async def test_identify_from_subdomain_with_port(self) -> None:
        """Test identifying tenant from subdomain with port."""
        strategy = SubdomainTenantStrategy(base_domain="example.com")
        request = MagicMock(spec=Request)
        request.headers = {"host": "acme-corp.example.com:8080"}

        tenant_id = await strategy.identify(request)
        assert tenant_id == "acme-corp"

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_no_subdomain(self) -> None:
        """Test that identify returns None when no subdomain."""
        strategy = SubdomainTenantStrategy(base_domain="example.com")
        request = MagicMock(spec=Request)
        request.headers = {"host": "example.com"}

        tenant_id = await strategy.identify(request)
        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_different_domain(self) -> None:
        """Test that identify returns None for different domain."""
        strategy = SubdomainTenantStrategy(base_domain="example.com")
        request = MagicMock(spec=Request)
        request.headers = {"host": "other-domain.com"}

        tenant_id = await strategy.identify(request)
        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_identify_with_custom_pattern(self) -> None:
        """Test identifying tenant with custom subdomain pattern."""
        strategy = SubdomainTenantStrategy(
            base_domain="example.com", subdomain_pattern=r"^([a-z0-9]+)"
        )
        request = MagicMock(spec=Request)
        request.headers = {"host": "tenant123.example.com"}

        tenant_id = await strategy.identify(request)
        assert tenant_id == "tenant123"

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_host_missing(self) -> None:
        """Test that identify returns None when host header is missing."""
        strategy = SubdomainTenantStrategy(base_domain="example.com")
        request = MagicMock(spec=Request)
        request.headers = {}

        tenant_id = await strategy.identify(request)
        assert tenant_id is None


class TestJWTClaimTenantStrategy:
    """Test JWTClaimTenantStrategy."""

    @pytest.mark.asyncio
    async def test_identify_from_user_tenant_id_attribute(self) -> None:
        """Test identifying tenant from user.tenant_id attribute."""
        strategy = JWTClaimTenantStrategy()
        request = MagicMock(spec=Request)
        user = MagicMock()
        user.tenant_id = "tenant-123"
        request.state.user = user

        tenant_id = await strategy.identify(request)
        assert tenant_id == "tenant-123"

    @pytest.mark.asyncio
    async def test_identify_from_user_metadata(self) -> None:
        """Test identifying tenant from user.metadata dict."""
        strategy = JWTClaimTenantStrategy(claim_name="tenant_id")
        request = MagicMock(spec=Request)
        user = MagicMock()
        user.metadata = {"tenant_id": "tenant-456"}
        request.state.user = user

        tenant_id = await strategy.identify(request)
        assert tenant_id == "tenant-456"

    @pytest.mark.asyncio
    async def test_identify_from_custom_claim_name(self) -> None:
        """Test identifying tenant from custom claim name."""
        strategy = JWTClaimTenantStrategy(claim_name="org_id")
        request = MagicMock(spec=Request)
        user = MagicMock()
        user.metadata = {"org_id": "org-789"}
        request.state.user = user

        tenant_id = await strategy.identify(request)
        assert tenant_id == "org-789"

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_no_user(self) -> None:
        """Test that identify returns None when no user in request state."""
        strategy = JWTClaimTenantStrategy()
        request = MagicMock(spec=Request)
        request.state.user = None

        tenant_id = await strategy.identify(request)
        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_no_tenant_info(self) -> None:
        """Test that identify returns None when user has no tenant info."""
        strategy = JWTClaimTenantStrategy()
        request = MagicMock(spec=Request)
        user = MagicMock()
        del user.tenant_id
        user.metadata = {}
        request.state.user = user

        tenant_id = await strategy.identify(request)
        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_identify_prefers_tenant_id_attribute_over_metadata(self) -> None:
        """Test that tenant_id attribute takes precedence over metadata."""
        strategy = JWTClaimTenantStrategy()
        request = MagicMock(spec=Request)
        user = MagicMock()
        user.tenant_id = "attribute-tenant"
        user.metadata = {"tenant_id": "metadata-tenant"}
        request.state.user = user

        tenant_id = await strategy.identify(request)
        assert tenant_id == "attribute-tenant"


class TestPathPrefixTenantStrategy:
    """Test PathPrefixTenantStrategy."""

    @pytest.mark.asyncio
    async def test_identify_from_path_prefix(self) -> None:
        """Test identifying tenant from path prefix."""
        strategy = PathPrefixTenantStrategy(prefix="/t")
        request = MagicMock(spec=Request)
        request.url.path = "/t/acme-corp/api/users"

        tenant_id = await strategy.identify(request)
        assert tenant_id == "acme-corp"

    @pytest.mark.asyncio
    async def test_identify_from_custom_prefix(self) -> None:
        """Test identifying tenant from custom path prefix."""
        strategy = PathPrefixTenantStrategy(prefix="/tenant")
        request = MagicMock(spec=Request)
        request.url.path = "/tenant/company-123/api"

        tenant_id = await strategy.identify(request)
        assert tenant_id == "company-123"

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_prefix_missing(self) -> None:
        """Test that identify returns None when prefix is missing."""
        strategy = PathPrefixTenantStrategy(prefix="/t")
        request = MagicMock(spec=Request)
        request.url.path = "/api/users"

        tenant_id = await strategy.identify(request)
        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_identify_returns_none_when_no_tenant_in_path(self) -> None:
        """Test that identify returns None when path doesn't match pattern."""
        strategy = PathPrefixTenantStrategy(prefix="/t")
        request = MagicMock(spec=Request)
        request.url.path = "/t/"

        tenant_id = await strategy.identify(request)
        assert tenant_id is None


class TestTenantMiddleware:
    """Test TenantMiddleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create a minimal FastAPI app."""

        app = FastAPI()

        # Add HTTPException handler for tests
        @app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )

        @app.get("/test")
        async def test_endpoint(request: Request) -> dict:
            tenant_id = getattr(request.state, "tenant_id", None)
            return {"tenant_id": tenant_id}

        return app

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncClient:
        """Create async HTTP client."""
        from httpx import ASGITransport

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_identifies_tenant_from_header(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware identifies tenant from header."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-123"
        assert response.headers.get("Accent-Tenant") == "tenant-123"

    @pytest.mark.asyncio
    async def test_identifies_tenant_from_subdomain(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware identifies tenant from subdomain."""
        app.add_middleware(
            TenantMiddleware, strategies=[SubdomainTenantStrategy(base_domain="test")]
        )

        # Mock the host header by creating a new client with different base_url
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://acme-corp.test"
        ) as subdomain_client:
            response = await subdomain_client.get("/test", headers={"host": "acme-corp.test"})

            assert response.status_code == 200
            assert response.json()["tenant_id"] == "acme-corp"

    @pytest.mark.asyncio
    async def test_tries_strategies_in_order(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware tries strategies in order."""
        # First strategy won't find tenant, second will
        strategy1 = HeaderTenantStrategy(header_name="X-Missing")
        strategy2 = HeaderTenantStrategy(header_name="Accent-Tenant")

        app.add_middleware(TenantMiddleware, strategies=[strategy1, strategy2])

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_uses_first_matching_strategy(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware uses first strategy that finds tenant."""
        strategy1 = HeaderTenantStrategy(header_name="Accent-Tenant")
        strategy2 = HeaderTenantStrategy(header_name="X-Tenant-ID")

        app.add_middleware(TenantMiddleware, strategies=[strategy1, strategy2])

        response = await client.get(
            "/test", headers={"Accent-Tenant": "first", "X-Tenant-ID": "second"}
        )

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "first"

    @pytest.mark.asyncio
    async def test_uses_default_tenant_when_none_identified(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware uses default tenant when none identified."""
        app.add_middleware(
            TenantMiddleware, strategies=[HeaderTenantStrategy()], default_tenant="default-tenant"
        )

        response = await client.get("/test")

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "default-tenant"
        assert response.headers.get("Accent-Tenant") == "default-tenant"

    @pytest.mark.asyncio
    async def test_raises_error_when_tenant_required_but_not_found(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware raises error when tenant required but not found."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()], required=True)

        response = await client.get("/test")

        assert response.status_code == 400
        assert "Tenant identifier required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_allows_request_when_tenant_required_and_found(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware allows request when tenant required and found."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()], required=True)

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_validates_tenant_when_validator_provided(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware validates tenant when validator provided."""

        async def validator(tenant_id: str) -> bool:
            return tenant_id == "valid-tenant"

        app.add_middleware(
            TenantMiddleware,
            strategies=[HeaderTenantStrategy()],
            tenant_validator=validator,
        )

        response = await client.get("/test", headers={"Accent-Tenant": "valid-tenant"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "valid-tenant"

    @pytest.mark.asyncio
    async def test_rejects_invalid_tenant(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware rejects invalid tenant."""

        async def validator(tenant_id: str) -> bool:
            return tenant_id == "valid-tenant"

        app.add_middleware(
            TenantMiddleware,
            strategies=[HeaderTenantStrategy()],
            tenant_validator=validator,
        )

        response = await client.get("/test", headers={"Accent-Tenant": "invalid-tenant"})

        assert response.status_code == 404
        assert "Tenant not found or inactive" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_handles_validator_exception(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware handles validator exceptions."""

        async def validator(tenant_id: str) -> bool:
            raise ValueError("Validation error")

        app.add_middleware(
            TenantMiddleware,
            strategies=[HeaderTenantStrategy()],
            tenant_validator=validator,
        )

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 500
        assert "Tenant validation error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_sets_tenant_context(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware sets tenant context."""

        @app.get("/context")
        async def context_endpoint() -> dict:
            context = get_tenant_context()
            return {
                "tenant_id": context.tenant_id if context else None,
                "identified_by": context.identified_by if context else None,
            }

        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/context", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "tenant-123"
        assert data["identified_by"] == "HeaderTenantStrategy"

    @pytest.mark.asyncio
    async def test_clears_tenant_context_after_request(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware clears tenant context after request."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        # Make request with tenant
        await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        # Context should be cleared after request
        assert get_tenant_context() is None

    @pytest.mark.asyncio
    async def test_handles_strategy_exception_gracefully(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that middleware handles strategy exceptions gracefully."""

        class FailingStrategy(TenantIdentificationStrategy):
            async def identify(self, request: Request) -> str | None:
                raise ValueError("Strategy error")

        app.add_middleware(TenantMiddleware, strategies=[FailingStrategy(), HeaderTenantStrategy()])

        # Should fall back to next strategy
        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_sets_request_state(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware sets request state."""

        @app.get("/state")
        async def state_endpoint(request: Request) -> dict:
            return {
                "tenant_id": getattr(request.state, "tenant_id", None),
                "has_context": hasattr(request.state, "tenant_context"),
            }

        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/state", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "tenant-123"
        assert data["has_context"] is True

    @pytest.mark.asyncio
    async def test_no_tenant_header_when_no_tenant(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that response doesn't have tenant header when no tenant identified."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/test")

        assert response.status_code == 200
        assert "Accent-Tenant" not in response.headers

    @pytest.mark.asyncio
    async def test_default_strategy_is_header(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that default strategy is HeaderTenantStrategy."""
        app.add_middleware(TenantMiddleware)

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_tenant_context_persists_during_request(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that tenant context persists during request processing."""

        @app.get("/context-check")
        async def context_check() -> dict:
            context = get_tenant_context()
            return {
                "has_context": context is not None,
                "tenant_id": context.tenant_id if context else None,
            }

        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/context-check", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        data = response.json()
        assert data["has_context"] is True
        assert data["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_multiple_strategies_fallback(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that middleware tries multiple strategies in order."""
        strategy1 = HeaderTenantStrategy(header_name="X-Missing-Header")
        strategy2 = HeaderTenantStrategy(header_name="Accent-Tenant")

        app.add_middleware(TenantMiddleware, strategies=[strategy1, strategy2])

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_subdomain_strategy_with_custom_pattern(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test subdomain strategy with custom pattern."""
        from httpx import ASGITransport

        app.add_middleware(
            TenantMiddleware,
            strategies=[
                SubdomainTenantStrategy(base_domain="test", subdomain_pattern=r"^([a-z0-9]+)")
            ],
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://tenant123.test"
        ) as subdomain_client:
            response = await subdomain_client.get("/test", headers={"host": "tenant123.test"})

            assert response.status_code == 200
            assert response.json()["tenant_id"] == "tenant123"

    @pytest.mark.asyncio
    async def test_path_prefix_strategy_with_custom_prefix(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test path prefix strategy with custom prefix."""

        # Register the test endpoint first
        @app.get("/test")
        async def test_endpoint(request: Request) -> dict:
            context = get_tenant_context()
            return {"tenant_id": context.tenant_id if context else None}

        app.add_middleware(
            TenantMiddleware, strategies=[PathPrefixTenantStrategy(prefix="/tenant")]
        )

        response = await client.get("/tenant/acme-corp/test")

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "acme-corp"

    @pytest.mark.asyncio
    async def test_jwt_strategy_with_metadata_precedence(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that JWT strategy prefers metadata over direct attribute."""
        from unittest.mock import MagicMock

        from starlette.middleware.base import BaseHTTPMiddleware

        # Create a middleware to set the user before tenant middleware runs
        class UserMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                # Simulate user from auth middleware
                user = MagicMock()
                # JWTClaimTenantStrategy uses "tenant_id" as the default claim_name
                user.metadata = {"tenant_id": "metadata-tenant"}
                user.tenant_id = "attribute-tenant"  # Should be ignored
                request.state.user = user
                return await call_next(request)

        # Add TenantMiddleware first (runs second), then UserMiddleware (runs first)
        # This ensures user is set before tenant identification
        # Note: Middleware is added in reverse order - last added runs first
        app.add_middleware(TenantMiddleware, strategies=[JWTClaimTenantStrategy()])
        app.add_middleware(UserMiddleware)

        @app.get("/jwt-test")
        async def jwt_test(request: Request) -> dict:
            return {"tenant_id": getattr(request.state, "tenant_id", None)}

        response = await client.get("/jwt-test")

        # Metadata should take precedence
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "metadata-tenant"

    @pytest.mark.asyncio
    async def test_tenant_validator_success(self, app: FastAPI, client: AsyncClient) -> None:
        """Test tenant validator with successful validation."""

        async def validator(tenant_id: str) -> bool:
            return tenant_id == "valid-tenant"

        app.add_middleware(
            TenantMiddleware,
            strategies=[HeaderTenantStrategy()],
            tenant_validator=validator,
        )

        response = await client.get("/test", headers={"Accent-Tenant": "valid-tenant"})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "valid-tenant"

    @pytest.mark.asyncio
    async def test_tenant_validator_async_exception(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test tenant validator with async exception."""

        async def validator(tenant_id: str) -> bool:
            raise ConnectionError("Database connection failed")

        app.add_middleware(
            TenantMiddleware,
            strategies=[HeaderTenantStrategy()],
            tenant_validator=validator,
        )

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 500
        assert "Tenant validation error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_tenant_context_cleared_after_request(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that tenant context is cleared after request completes."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        # Make request with tenant
        await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        # Context should be cleared
        assert get_tenant_context() is None

    @pytest.mark.asyncio
    async def test_tenant_header_in_response(self, app: FastAPI, client: AsyncClient) -> None:
        """Test that tenant ID is added to response headers."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/test", headers={"Accent-Tenant": "tenant-123"})

        assert response.status_code == 200
        assert response.headers.get("Accent-Tenant") == "tenant-123"

    @pytest.mark.asyncio
    async def test_no_tenant_header_when_not_identified(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test that no tenant header when tenant not identified."""
        app.add_middleware(TenantMiddleware, strategies=[HeaderTenantStrategy()])

        response = await client.get("/test")

        assert response.status_code == 200
        assert "Accent-Tenant" not in response.headers

    @pytest.mark.asyncio
    async def test_subdomain_strategy_with_port_in_host(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test subdomain strategy handles port in host header."""
        from httpx import ASGITransport

        app.add_middleware(
            TenantMiddleware,
            strategies=[SubdomainTenantStrategy(base_domain="test")],
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://acme-corp.test:8080"
        ) as subdomain_client:
            response = await subdomain_client.get("/test", headers={"host": "acme-corp.test:8080"})

            assert response.status_code == 200
            assert response.json()["tenant_id"] == "acme-corp"

    @pytest.mark.asyncio
    async def test_path_prefix_strategy_with_trailing_slash(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Test path prefix strategy handles trailing slash."""

        # Register the test endpoint first
        @app.get("/api/test")
        async def test_endpoint(request: Request) -> dict:
            context = get_tenant_context()
            return {"tenant_id": context.tenant_id if context else None}

        app.add_middleware(TenantMiddleware, strategies=[PathPrefixTenantStrategy(prefix="/t/")])

        response = await client.get("/t/acme-corp/api/test")

        assert response.status_code == 200
        assert response.json()["tenant_id"] == "acme-corp"
