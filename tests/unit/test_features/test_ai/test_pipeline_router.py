"""Unit tests for AI Pipeline Router endpoints."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
import pytest

from example_service.features.ai.pipeline.router import router
from example_service.features.ai.pipeline.schemas import (
    PipelineExecutionRequest,
    SetBudgetRequest,
)
from example_service.infra.ai.capabilities import Capability, ProviderType
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

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
else:  # pragma: no cover - runtime placeholder for typing-only import
    AsyncGenerator = Any


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    """Create a mock orchestrator."""
    orchestrator = MagicMock()
    orchestrator.execute = AsyncMock()
    orchestrator.execute_async = AsyncMock()
    orchestrator.get_execution = AsyncMock()
    orchestrator.get_progress = AsyncMock()
    return orchestrator


@pytest.fixture
def mock_budget_service() -> MagicMock:
    """Create a mock budget service."""
    budget_service = MagicMock()
    budget_service.check_budget = AsyncMock(
        return_value=BudgetCheckResult(
            allowed=True,
            action=BudgetAction.ALLOWED,
            current_spend_usd=Decimal("0.00"),
            limit_usd=Decimal("100.00"),
            percent_used=0.0,
            period=BudgetPeriod.DAILY,
            message="Budget OK",
        ),
    )
    budget_service.set_budget = AsyncMock()
    budget_service.get_budget_status = AsyncMock()
    budget_service.get_spend_summary = AsyncMock()
    return budget_service


@pytest.fixture
def mock_pipeline() -> PipelineDefinition:
    """Create a mock pipeline."""
    return PipelineDefinition(
        name="test_pipeline",
        version="1.0.0",
        description="Test pipeline",
        tags=["test"],
        steps=[
            PipelineStep(
                name="step1",
                capability=Capability.TRANSCRIPTION,
                description="Transcribe",
            ),
        ],
        estimated_duration_seconds=10,
        estimated_cost_usd=Decimal("0.10"),
    )


@pytest.fixture
def mock_pipeline_result() -> PipelineResult:
    """Create a mock pipeline result."""
    return PipelineResult(
        execution_id="exec-123",
        pipeline_name="test_pipeline",
        pipeline_version="1.0.0",
        success=True,
        output={"result": "test"},
        completed_steps=["step1"],
        failed_step=None,
        total_duration_ms=1000,
        total_cost_usd=Decimal("0.05"),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


@pytest.fixture
async def ai_client(
    mock_orchestrator: MagicMock, mock_budget_service: MagicMock,
) -> AsyncGenerator[AsyncClient]:
    """Create HTTP client with AI router and mocked dependencies."""
    app = FastAPI()
    app.include_router(router)

    # Override dependencies
    async def override_get_orchestrator():
        return mock_orchestrator

    async def override_get_current_tenant():
        return "test-tenant"

    async def override_validate_tenant_budget():
        return "test-tenant"

    from unittest.mock import AsyncMock

    async def override_get_session():
        return AsyncMock()

    with patch(
        "example_service.features.ai.pipeline.router.get_instrumented_orchestrator",
    ) as mock_get_orch:
        mock_get_orch.return_value = mock_orchestrator

        with patch(
            "example_service.features.ai.pipeline.router.get_budget_service",
        ) as mock_get_budget:
            mock_get_budget.return_value = mock_budget_service

            # Import the actual functions from the router module for dependency overrides
            from example_service.features.ai.pipeline.router import (
                get_current_tenant,
                get_orchestrator,
                get_session,
                validate_tenant_budget,
            )

            app.dependency_overrides[get_session] = override_get_session
            app.dependency_overrides[get_orchestrator] = override_get_orchestrator
            app.dependency_overrides[get_current_tenant] = override_get_current_tenant
            # Don't override validate_tenant_budget—keep the real dependency so budget checks run.

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
            ) as client:
                yield client

            app.dependency_overrides.clear()


class TestListPipelines:
    """Test GET /ai/pipelines endpoint."""

    @pytest.mark.asyncio
    async def test_list_pipelines_success(self, ai_client: AsyncClient) -> None:
        """Test successfully listing pipelines."""
        with patch("example_service.features.ai.pipeline.router.list_pipelines") as mock_list:
            mock_list.return_value = [
                PipelineDefinition(
                    name="pipeline1",
                    version="1.0.0",
                    description="Test",
                    tags=[],
                    steps=[],
                    estimated_duration_seconds=10,
                    estimated_cost_usd=Decimal("0.10"),
                ),
            ]

            response = await ai_client.get("/ai/pipelines")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "pipelines" in data
            assert len(data["pipelines"]) == 1


class TestGetPipeline:
    """Test GET /ai/pipelines/{name} endpoint."""

    @pytest.mark.asyncio
    async def test_get_pipeline_success(
        self, ai_client: AsyncClient, mock_pipeline: PipelineDefinition,
    ) -> None:
        """Test successfully getting a pipeline."""
        with patch("example_service.features.ai.pipeline.router.get_pipeline") as mock_get:
            mock_get.return_value = mock_pipeline

            response = await ai_client.get("/ai/pipelines/test_pipeline")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["name"] == "test_pipeline"

    @pytest.mark.asyncio
    async def test_get_pipeline_not_found(self, ai_client: AsyncClient) -> None:
        """Test getting non-existent pipeline."""
        with patch("example_service.features.ai.pipeline.router.get_pipeline") as mock_get:
            mock_get.return_value = None

            response = await ai_client.get("/ai/pipelines/nonexistent")

            assert response.status_code == status.HTTP_404_NOT_FOUND


class TestExecutePipeline:
    """Test POST /ai/pipelines/execute endpoint."""

    @pytest.mark.asyncio
    async def test_execute_pipeline_sync_success(
        self,
        ai_client: AsyncClient,
        mock_orchestrator: MagicMock,
        mock_pipeline_result: PipelineResult,
    ) -> None:
        """Test successfully executing pipeline in sync mode."""
        mock_orchestrator.execute.return_value = mock_pipeline_result

        with patch("example_service.features.ai.pipeline.router.get_pipeline") as mock_get:
            mock_get.return_value = PipelineDefinition(
                name="test_pipeline",
                version="1.0.0",
                description="Test",
                tags=[],
                steps=[],
                estimated_duration_seconds=10,
                estimated_cost_usd=Decimal("0.10"),
            )

            response = await ai_client.post(
                "/ai/pipelines/execute",
                json={
                    "pipeline_name": "test_pipeline",
                    "input_data": {"data": "test"},
                    "async_processing": False,
                },
            )

            if response.status_code != status.HTTP_200_OK:
                import json

                with contextlib.suppress(Exception):
                    response.json()
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["execution_id"] == "exec-123"
            assert data["success"] is True

    @pytest.mark.asyncio
    async def test_execute_pipeline_async_success(
        self,
        ai_client: AsyncClient,
        mock_orchestrator: MagicMock,
    ) -> None:
        """Test successfully executing pipeline in async mode."""
        # Note: The router generates execution_id internally, so we just check it exists
        with patch("example_service.features.ai.pipeline.router.get_pipeline") as mock_get:
            mock_get.return_value = PipelineDefinition(
                name="test_pipeline",
                version="1.0.0",
                description="Test",
                tags=[],
                steps=[],
                estimated_duration_seconds=10,
                estimated_cost_usd=Decimal("0.10"),
            )

            response = await ai_client.post(
                "/ai/pipelines/execute",
                json={
                    "pipeline_name": "test_pipeline",
                    "input_data": {"data": "test"},
                    "async_processing": True,
                },
            )

            assert response.status_code == status.HTTP_202_ACCEPTED
            data = response.json()
            assert "execution_id" in data
            assert data["execution_id"].startswith("exec-")
            assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_execute_pipeline_not_found(self, ai_client: AsyncClient) -> None:
        """Test executing non-existent pipeline."""
        with patch("example_service.features.ai.pipeline.router.get_pipeline") as mock_get:
            with patch("example_service.features.ai.pipeline.router.list_pipelines") as mock_list:
                mock_get.return_value = None
                mock_list.return_value = [
                    PipelineDefinition(
                        name="test_pipeline",
                        version="1.0.0",
                        description="Test",
                        tags=[],
                        steps=[],
                        estimated_duration_seconds=10,
                        estimated_cost_usd=Decimal("0.10"),
                    ),
                ]

                response = await ai_client.post(
                    "/ai/pipelines/execute",
                    json={
                        "pipeline_name": "nonexistent",
                        "input_data": {},
                        "async_processing": False,
                    },
                )

                assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_execute_pipeline_budget_exceeded(
        self, ai_client: AsyncClient, mock_budget_service: MagicMock,
    ) -> None:
        """Test executing pipeline when budget is exceeded."""
        # Override the check_budget mock to return blocked result
        mock_budget_service.check_budget = AsyncMock(
            return_value=BudgetCheckResult(
                allowed=False,
                action=BudgetAction.BLOCKED,
                current_spend_usd=Decimal("100.00"),
                limit_usd=Decimal("100.00"),
                percent_used=100.0,
                period=BudgetPeriod.DAILY,
                message="Budget exceeded",
            ),
        )

        with patch("example_service.features.ai.pipeline.router.get_pipeline") as mock_get:
            mock_get.return_value = PipelineDefinition(
                name="test_pipeline",
                version="1.0.0",
                description="Test",
                tags=[],
                steps=[],
                estimated_duration_seconds=10,
                estimated_cost_usd=Decimal("0.10"),
            )

            response = await ai_client.post(
                "/ai/pipelines/execute",
                json={
                    "pipeline_name": "test_pipeline",
                    "input_data": {},
                    "async_processing": False,
                },
            )

            assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
            data = response.json()
            assert "budget_exceeded" in data["detail"]["error"]


class TestGetExecution:
    """Test GET /ai/pipelines/executions/{execution_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_execution_success(
        self,
        ai_client: AsyncClient,
        mock_orchestrator: MagicMock,
        mock_pipeline_result: PipelineResult,
    ) -> None:
        """Test successfully getting execution result."""
        mock_orchestrator.get_execution.return_value = mock_pipeline_result

        response = await ai_client.get("/ai/pipelines/executions/exec-123")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["execution_id"] == "exec-123"
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_get_execution_not_found(
        self, ai_client: AsyncClient, mock_orchestrator: MagicMock,
    ) -> None:
        """Test getting non-existent execution."""
        mock_orchestrator.get_execution.return_value = None

        response = await ai_client.get("/ai/pipelines/executions/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestGetProgress:
    """Test GET /ai/pipelines/executions/{execution_id}/progress endpoint."""

    @pytest.mark.asyncio
    async def test_get_progress_success(
        self, ai_client: AsyncClient, mock_orchestrator: MagicMock,
    ) -> None:
        """Test successfully getting execution progress."""
        mock_orchestrator.get_progress.return_value = {
            "execution_id": "exec-123",
            "status": "processing",
            "completed_steps": ["step1"],
            "current_step": "step2",
            "progress_percent": 50,
        }

        response = await ai_client.get("/ai/pipelines/executions/exec-123/progress")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "processing"
        assert data["progress_percent"] == 50

    @pytest.mark.asyncio
    async def test_get_progress_not_found(
        self, ai_client: AsyncClient, mock_orchestrator: MagicMock,
    ) -> None:
        """Test getting progress for non-existent execution."""
        mock_orchestrator.get_progress.return_value = None

        response = await ai_client.get("/ai/pipelines/executions/nonexistent/progress")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestBudgetEndpoints:
    """Test budget management endpoints."""

    @pytest.mark.asyncio
    async def test_set_budget_success(
        self, ai_client: AsyncClient, mock_budget_service: MagicMock,
    ) -> None:
        """Test successfully setting budget."""
        response = await ai_client.post(
            "/ai/pipelines/budget",
            json={
                "limit_usd": "100.00",
                "period": "daily",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        mock_budget_service.set_budget.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_budget_status_success(
        self, ai_client: AsyncClient, mock_budget_service: MagicMock,
    ) -> None:
        """Test successfully getting budget status."""
        mock_budget_service.get_budget_status.return_value = {
            "limit_usd": Decimal("100.00"),
            "current_spend_usd": Decimal("50.00"),
            "period": "daily",
            "action": "allowed",
        }

        response = await ai_client.get("/ai/pipelines/budget/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "limit_usd" in data
        assert "current_spend_usd" in data

    @pytest.mark.asyncio
    async def test_get_spend_summary_success(
        self, ai_client: AsyncClient, mock_budget_service: MagicMock,
    ) -> None:
        """Test successfully getting spend summary."""
        mock_budget_service.get_spend_summary.return_value = {
            "total_spend_usd": Decimal("75.00"),
            "period": "daily",
            "breakdown": {},
        }

        response = await ai_client.get("/ai/pipelines/budget/spend")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "total_spend_usd" in data


class TestListCapabilities:
    """Test GET /ai/pipelines/capabilities endpoint."""

    @pytest.mark.asyncio
    async def test_list_capabilities_success(self, ai_client: AsyncClient) -> None:
        """Test successfully listing capabilities."""
        with patch(
            "example_service.features.ai.pipeline.router.get_capability_registry",
        ) as mock_registry:
            mock_registry.return_value.list_capabilities.return_value = [
                Capability.TRANSCRIPTION,
                Capability.LLM_GENERATION,
            ]

            response = await ai_client.get("/ai/pipelines/capabilities")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "capabilities" in data


class TestListProviders:
    """Test GET /ai/pipelines/providers endpoint."""

    @pytest.mark.asyncio
    async def test_list_providers_success(self, ai_client: AsyncClient) -> None:
        """Test successfully listing providers."""
        with patch(
            "example_service.features.ai.pipeline.router.get_capability_registry",
        ) as mock_registry:
            mock_provider = MagicMock()
            mock_provider.name = "test_provider"
            mock_provider.provider_type = ProviderType.EXTERNAL
            mock_registry.return_value.list_providers.return_value = [mock_provider]

            response = await ai_client.get("/ai/pipelines/providers")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert "providers" in data
