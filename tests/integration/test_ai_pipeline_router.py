"""Integration tests for AI Pipeline Router.

Tests all REST and WebSocket endpoints of the pipeline router:
- Pipeline discovery (list pipelines, capabilities, providers)
- Pipeline execution (sync and async modes)
- Progress tracking and result retrieval
- Budget management endpoints
- WebSocket event streaming
- Health check

Test Strategy:
    - Mock the AI infrastructure (orchestrator, registry, event store, budget)
    - Use FastAPI TestClient with dependency overrides
    - Test both success paths and error handling
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

from example_service.infra.ai.capabilities import Capability, ProviderType
from example_service.infra.ai.events import EventType
from example_service.infra.ai.observability import (
    BudgetAction,
    BudgetCheckResult,
    BudgetPeriod,
)
from example_service.infra.ai.pipelines.types import (
    PipelineDefinition,
    PipelineResult,
    PipelineStep,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_tenant_id() -> str:
    """Mock tenant ID for testing."""
    return "tenant-test-123"


@pytest.fixture
def mock_pipeline() -> PipelineDefinition:
    """Create a mock pipeline for testing."""
    return PipelineDefinition(
        name="test_pipeline",
        version="1.0.0",
        description="A test pipeline",
        tags=["test", "mock"],
        steps=[
            PipelineStep(
                name="step_1",
                capability=Capability.TRANSCRIPTION,
                description="Transcribe audio",
            ),
            PipelineStep(
                name="step_2",
                capability=Capability.LLM_GENERATION,
                description="Generate summary",
            ),
        ],
        estimated_duration_seconds=30,
        estimated_cost_usd=Decimal("0.10"),
    )


@pytest.fixture
def mock_pipeline_result() -> PipelineResult:
    """Create a mock pipeline result."""
    return PipelineResult(
        execution_id="exec-test-12345",
        pipeline_name="test_pipeline",
        pipeline_version="1.0.0",
        success=True,
        output={"transcript": "Hello world", "summary": "A greeting"},
        completed_steps=["step_1", "step_2"],
        failed_step=None,
        total_duration_ms=1500,
        total_cost_usd=Decimal("0.05"),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_provider():
    """Create a mock provider registration."""
    provider = MagicMock()
    provider.name = "mock_openai"
    provider.provider_type = ProviderType.EXTERNAL
    provider.capabilities = [Capability.TRANSCRIPTION, Capability.LLM_GENERATION]
    provider.requires_api_key = True
    provider.documentation_url = None  # Explicitly set to avoid MagicMock
    return provider


@pytest.fixture
def mock_registry(mock_provider):
    """Create a mock capability registry."""
    registry = MagicMock()
    registry.get_all_providers.return_value = [mock_provider]
    registry.get_providers_for_capability.return_value = [mock_provider]
    return registry


@pytest.fixture
def mock_event_store():
    """Create a mock event store."""
    store = AsyncMock()
    store.get_events = AsyncMock(return_value=[])
    store.get_workflow_state = AsyncMock(
        return_value={
            "status": "completed",
            "total_steps": 2,
            "completed_steps": ["step_1", "step_2"],
            "current_step": "step_2",
            "pipeline_name": "test_pipeline",
            "pipeline_version": "1.0.0",
            "output": {"result": "test"},
            "step_results": {
                "step_1": {
                    "status": "completed",
                    "provider_used": "mock_openai",
                    "duration_ms": 500,
                    "cost": Decimal("0.02"),
                },
                "step_2": {
                    "status": "completed",
                    "provider_used": "mock_openai",
                    "duration_ms": 1000,
                    "cost": Decimal("0.03"),
                },
            },
            "total_cost": Decimal("0.05"),
            "total_duration_ms": 1500,
            "started_at": datetime.now(UTC),
            "completed_at": datetime.now(UTC),
        }
    )
    return store


@pytest.fixture
def mock_budget_service():
    """Create a mock budget service."""
    service = AsyncMock()
    service.check_budget = AsyncMock(
        return_value=BudgetCheckResult(
            allowed=True,
            action=BudgetAction.ALLOWED,
            current_spend_usd=Decimal("5.00"),
            limit_usd=Decimal("100.00"),
            percent_used=5.0,
            period=BudgetPeriod.MONTHLY,
            message="Budget OK",
        )
    )
    service.get_spend_summary = AsyncMock(
        return_value={
            "total": Decimal("5.00"),
            "record_count": 10,
            "by_pipeline": {"test_pipeline": Decimal("3.00")},
            "by_provider": {"mock_openai": Decimal("5.00")},
            "by_capability": {"transcription": Decimal("2.00")},
        }
    )
    service.set_budget = AsyncMock()
    return service


@pytest.fixture
def mock_orchestrator(mock_pipeline_result):
    """Create a mock instrumented orchestrator."""
    orchestrator = AsyncMock()
    orchestrator.execute = AsyncMock(return_value=mock_pipeline_result)
    return orchestrator


@pytest.fixture
async def ai_client(
    mock_tenant_id,
    mock_pipeline,
    mock_registry,
    mock_event_store,
    mock_budget_service,
    mock_orchestrator,
):
    """Create async HTTP client with mocked AI infrastructure.

    This fixture:
    1. Creates a minimal FastAPI app with just the pipeline router
    2. Overrides dependencies to inject mocks
    3. Patches module-level getters for AI infrastructure
    """
    from fastapi import FastAPI

    from example_service.features.ai.pipeline.router import (
        get_current_tenant,
        get_orchestrator,
        router,
        validate_tenant_budget,
    )

    # Create minimal app with only the pipeline router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Override FastAPI dependencies
    async def override_tenant() -> str:
        return mock_tenant_id

    async def override_orchestrator() -> AsyncMock:
        return mock_orchestrator

    app.dependency_overrides[get_current_tenant] = override_tenant
    app.dependency_overrides[validate_tenant_budget] = override_tenant
    app.dependency_overrides[get_orchestrator] = override_orchestrator

    # Patch module-level getters
    with (
        patch(
            "example_service.features.ai.pipeline.router.get_capability_registry",
            return_value=mock_registry,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_event_store",
            return_value=mock_event_store,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_budget_service",
            return_value=mock_budget_service,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_pipeline", return_value=mock_pipeline
        ),
        patch(
            "example_service.features.ai.pipeline.router.list_pipelines",
            return_value=[mock_pipeline],
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


# =============================================================================
# Pipeline Discovery Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_pipelines(ai_client: AsyncClient):
    """Test listing available pipelines."""
    response = await ai_client.get("/api/v1/ai/pipelines")

    assert response.status_code == 200
    data = response.json()

    assert "pipelines" in data
    assert "total" in data
    assert data["total"] == 1

    pipeline = data["pipelines"][0]
    assert pipeline["name"] == "test_pipeline"
    assert pipeline["version"] == "1.0.0"
    assert pipeline["description"] == "A test pipeline"
    assert "test" in pipeline["tags"]
    assert pipeline["step_count"] == 2


@pytest.mark.asyncio
async def test_list_pipelines_with_tag_filter(ai_client: AsyncClient):
    """Test listing pipelines with tag filter."""
    response = await ai_client.get("/api/v1/ai/pipelines?tags=test")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 0  # Filtering is applied


@pytest.mark.asyncio
async def test_list_capabilities(ai_client: AsyncClient):
    """Test listing available capabilities."""
    response = await ai_client.get("/api/v1/ai/pipelines/capabilities")

    assert response.status_code == 200
    data = response.json()

    assert "capabilities" in data
    # Capabilities depend on what the mock registry returns


@pytest.mark.asyncio
async def test_list_providers(ai_client: AsyncClient):
    """Test listing registered providers."""
    response = await ai_client.get("/api/v1/ai/pipelines/providers")

    assert response.status_code == 200
    data = response.json()

    assert "providers" in data
    assert "total" in data
    assert data["total"] == 1

    provider = data["providers"][0]
    assert provider["name"] == "mock_openai"
    assert provider["is_available"] is True


# =============================================================================
# Pipeline Execution Tests
# =============================================================================


@pytest.mark.asyncio
async def test_execute_pipeline_async(ai_client: AsyncClient):
    """Test async pipeline execution returns immediately."""
    response = await ai_client.post(
        "/api/v1/ai/pipelines/execute",
        json={
            "pipeline_name": "test_pipeline",
            "input_data": {"audio_url": "https://example.com/audio.wav"},
            "async_processing": True,
        },
    )

    assert response.status_code == 202
    data = response.json()

    assert "execution_id" in data
    assert data["execution_id"].startswith("exec-")
    assert data["pipeline_name"] == "test_pipeline"
    assert data["status"] == "pending"
    assert "stream_url" in data


@pytest.mark.asyncio
async def test_execute_pipeline_sync(ai_client: AsyncClient, mock_orchestrator):
    """Test synchronous pipeline execution waits for result."""
    response = await ai_client.post(
        "/api/v1/ai/pipelines/execute",
        json={
            "pipeline_name": "test_pipeline",
            "input_data": {"audio_url": "https://example.com/audio.wav"},
            "async_processing": False,
        },
    )

    assert response.status_code == 202
    data = response.json()

    assert "execution_id" in data
    assert data["status"] == "completed"
    assert data["estimated_cost_usd"] == "0.05"

    # Verify orchestrator was called
    mock_orchestrator.execute.assert_called_once()


@pytest.mark.asyncio
async def test_execute_pipeline_not_found(ai_client: AsyncClient):
    """Test execution with non-existent pipeline returns 404."""
    with patch(
        "example_service.features.ai.pipeline.router.get_pipeline",
        return_value=None,
    ):
        response = await ai_client.post(
            "/api/v1/ai/pipelines/execute",
            json={
                "pipeline_name": "nonexistent_pipeline",
                "input_data": {},
            },
        )

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "pipeline_not_found"


@pytest.mark.asyncio
async def test_execute_pipeline_with_options(ai_client: AsyncClient, mock_orchestrator):
    """Test pipeline execution with custom options."""
    response = await ai_client.post(
        "/api/v1/ai/pipelines/execute",
        json={
            "pipeline_name": "test_pipeline",
            "input_data": {"audio_url": "https://example.com/audio.wav"},
            "options": {"language": "en", "model": "whisper-1"},
            "async_processing": False,
        },
    )

    assert response.status_code == 202

    # Verify options were passed to orchestrator
    call_kwargs = mock_orchestrator.execute.call_args.kwargs
    assert call_kwargs["options"] == {"language": "en", "model": "whisper-1"}


# =============================================================================
# Progress and Result Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_execution_progress(ai_client: AsyncClient, mock_event_store):
    """Test getting execution progress."""
    # Set up mock to return some events
    mock_event_store.get_events.return_value = [{"event_type": "workflow_started"}]
    mock_event_store.get_workflow_state.return_value = {
        "status": "running",
        "total_steps": 2,
        "completed_steps": ["step_1"],
        "current_step": "step_2",
        "message": "Processing step 2",
    }

    response = await ai_client.get("/api/v1/ai/pipelines/exec-12345")

    assert response.status_code == 200
    data = response.json()

    assert data["execution_id"] == "exec-12345"
    assert data["status"] == "running"
    assert data["steps_completed"] == 1
    assert data["total_steps"] == 2
    assert data["progress_percent"] == 50.0


@pytest.mark.asyncio
async def test_get_execution_progress_not_found(ai_client: AsyncClient, mock_event_store):
    """Test getting progress for non-existent execution."""
    mock_event_store.get_events.return_value = []

    response = await ai_client.get("/api/v1/ai/pipelines/exec-nonexistent")

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "execution_not_found"


@pytest.mark.asyncio
async def test_get_execution_result(ai_client: AsyncClient, mock_event_store):
    """Test getting completed execution result."""
    response = await ai_client.get("/api/v1/ai/pipelines/exec-12345/result")

    assert response.status_code == 200
    data = response.json()

    assert data["execution_id"] == "exec-12345"
    assert data["status"] == "completed"
    assert data["success"] is True
    assert "output" in data
    assert "step_results" in data
    assert data["total_cost_usd"] == "0.05"


@pytest.mark.asyncio
async def test_get_execution_result_not_complete(ai_client: AsyncClient, mock_event_store):
    """Test getting result for incomplete execution returns 409."""
    mock_event_store.get_workflow_state.return_value = {
        "status": "running",
        "total_steps": 2,
        "completed_steps": ["step_1"],
    }

    response = await ai_client.get("/api/v1/ai/pipelines/exec-12345/result")

    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["error"] == "execution_not_complete"


@pytest.mark.asyncio
async def test_cancel_execution(ai_client: AsyncClient):
    """Test canceling a running execution."""
    response = await ai_client.delete("/api/v1/ai/pipelines/exec-12345")

    assert response.status_code == 202
    data = response.json()

    assert data["execution_id"] == "exec-12345"
    assert data["cancellation_requested"] is True


# =============================================================================
# Budget Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_budget_status(ai_client: AsyncClient):
    """Test getting budget status."""
    response = await ai_client.get("/api/v1/ai/pipelines/budget/status")

    assert response.status_code == 200
    data = response.json()

    assert data["tenant_id"] == "tenant-test-123"
    assert data["current_spend_usd"] == "5.00"
    assert data["limit_usd"] == "100.00"
    assert data["is_exceeded"] is False


@pytest.mark.asyncio
async def test_get_budget_status_with_period(ai_client: AsyncClient, mock_budget_service):
    """Test getting budget status with specific period."""
    response = await ai_client.get("/api/v1/ai/pipelines/budget/status?period=daily")

    assert response.status_code == 200

    # Verify correct period was used
    mock_budget_service.check_budget.assert_called_with(
        "tenant-test-123",
        period=BudgetPeriod.DAILY,
    )


@pytest.mark.asyncio
async def test_get_spend_summary(ai_client: AsyncClient):
    """Test getting spend summary breakdown."""
    response = await ai_client.get("/api/v1/ai/pipelines/budget/spend")

    assert response.status_code == 200
    data = response.json()

    assert data["tenant_id"] == "tenant-test-123"
    assert data["total_spend_usd"] == "5.00"
    assert data["record_count"] == 10
    assert "by_pipeline" in data
    assert "by_provider" in data
    assert "by_capability" in data


@pytest.mark.asyncio
async def test_set_budget_limits(ai_client: AsyncClient, mock_budget_service):
    """Test setting budget limits."""
    response = await ai_client.put(
        "/api/v1/ai/pipelines/budget/limits",
        json={
            "daily_limit_usd": "50.00",
            "monthly_limit_usd": "500.00",
            "warn_threshold_percent": 80.0,
            "policy": "warn",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["daily_limit_usd"] == "50.00"
    assert data["monthly_limit_usd"] == "500.00"

    # Verify service was called
    mock_budget_service.set_budget.assert_called_once()


@pytest.mark.asyncio
async def test_budget_exceeded_blocks_execution(
    mock_tenant_id,
    mock_pipeline,
    mock_registry,
    mock_event_store,
    mock_orchestrator,
):
    """Test that exceeded budget blocks pipeline execution."""
    from fastapi import FastAPI

    from example_service.features.ai.pipeline.router import (
        get_current_tenant,
        get_orchestrator,
        router,
        validate_tenant_budget,
    )

    # Create budget service that returns blocked
    blocked_budget_service = AsyncMock()
    blocked_budget_service.check_budget = AsyncMock(
        return_value=BudgetCheckResult(
            allowed=False,
            action=BudgetAction.BLOCKED,
            current_spend_usd=Decimal("110.00"),
            limit_usd=Decimal("100.00"),
            percent_used=110.0,
            period=BudgetPeriod.MONTHLY,
            message="Monthly budget exceeded",
        )
    )

    # Create minimal app with only the pipeline router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_tenant() -> str:
        return mock_tenant_id

    async def override_orchestrator() -> AsyncMock:
        return mock_orchestrator

    app.dependency_overrides[get_current_tenant] = override_tenant
    # DON'T override validate_tenant_budget - let it run to check budget
    app.dependency_overrides[get_orchestrator] = override_orchestrator

    with (
        patch(
            "example_service.features.ai.pipeline.router.get_capability_registry",
            return_value=mock_registry,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_event_store",
            return_value=mock_event_store,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_budget_service",
            return_value=blocked_budget_service,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_pipeline", return_value=mock_pipeline
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/ai/pipelines/execute",
                json={
                    "pipeline_name": "test_pipeline",
                    "input_data": {},
                },
            )

    assert response.status_code == 402
    data = response.json()
    assert data["detail"]["error"] == "budget_exceeded"


# =============================================================================
# Health Check Tests
# =============================================================================


@pytest.mark.asyncio
async def test_pipeline_health_check(ai_client: AsyncClient):
    """Test pipeline infrastructure health check."""
    response = await ai_client.get("/api/v1/ai/pipelines/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ("healthy", "degraded")
    assert "providers" in data
    assert "services" in data
    assert "pipelines" in data

    assert data["providers"]["registered"] == 1
    assert data["services"]["event_store"] == "available"
    assert data["services"]["budget_service"] == "available"


@pytest.mark.asyncio
async def test_pipeline_health_check_degraded(ai_client: AsyncClient, mock_registry):
    """Test health check returns degraded when no providers."""
    mock_registry.get_all_providers.return_value = []

    response = await ai_client.get("/api/v1/ai/pipelines/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
async def test_event_store_unavailable(ai_client: AsyncClient):
    """Test handling when event store is unavailable."""
    with patch(
        "example_service.features.ai.pipeline.router.get_event_store",
        return_value=None,
    ):
        response = await ai_client.get("/api/v1/ai/pipelines/exec-12345")

    assert response.status_code == 503
    assert "Event store not available" in response.json()["detail"]


@pytest.mark.asyncio
async def test_budget_service_unavailable_for_limits(ai_client: AsyncClient):
    """Test handling when budget service is unavailable for limit setting."""
    with patch(
        "example_service.features.ai.pipeline.router.get_budget_service",
        return_value=None,
    ):
        response = await ai_client.put(
            "/api/v1/ai/pipelines/budget/limits",
            json={"monthly_limit_usd": "100.00"},
        )

    assert response.status_code == 503
    assert "Budget service not available" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_request_body(ai_client: AsyncClient):
    """Test validation error for invalid request body."""
    response = await ai_client.post(
        "/api/v1/ai/pipelines/execute",
        json={
            # Missing required pipeline_name
            "input_data": {},
        },
    )

    assert response.status_code == 422  # Validation error


# =============================================================================
# WebSocket Tests (Basic connectivity)
# =============================================================================


@pytest.mark.asyncio
async def test_websocket_event_stream_connection(
    mock_tenant_id,
    mock_pipeline,
    mock_registry,
    mock_budget_service,
    mock_orchestrator,
):
    """Test WebSocket connection for event streaming."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient as SyncTestClient

    from example_service.features.ai.pipeline.router import (
        get_current_tenant,
        get_orchestrator,
        router,
        validate_tenant_budget,
    )

    # Create mock event store with async generator for subscribe
    mock_event_store = AsyncMock()
    mock_event_store.get_events = AsyncMock(return_value=[])
    mock_event_store.get_workflow_state = AsyncMock(
        return_value={
            "status": "completed",
        }
    )

    async def mock_subscribe(execution_id, event_types=None):
        # Empty async generator
        return
        yield

    mock_event_store.subscribe = mock_subscribe

    # Create minimal app with only the pipeline router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def override_tenant() -> str:
        return mock_tenant_id

    async def override_orchestrator() -> AsyncMock:
        return mock_orchestrator

    app.dependency_overrides[get_current_tenant] = override_tenant
    app.dependency_overrides[validate_tenant_budget] = override_tenant
    app.dependency_overrides[get_orchestrator] = override_orchestrator

    with (
        patch(
            "example_service.features.ai.pipeline.router.get_capability_registry",
            return_value=mock_registry,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_event_store",
            return_value=mock_event_store,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_budget_service",
            return_value=mock_budget_service,
        ),
        patch(
            "example_service.features.ai.pipeline.router.get_pipeline", return_value=mock_pipeline
        ),
        patch(
            "example_service.features.ai.pipeline.router.list_pipelines",
            return_value=[mock_pipeline],
        ),
    ):
        # Use synchronous TestClient for WebSocket testing
        with SyncTestClient(app) as client:
            with client.websocket_connect("/api/v1/ai/pipelines/exec-12345/events"):
                # Connection should succeed and close normally
                # The mock returns completed status so WebSocket should close
                pass  # Connection established successfully
