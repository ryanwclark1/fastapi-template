"""Unit tests for Email Router endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
import pytest

from example_service.core.dependencies.database import get_async_session
from example_service.features.email.dependencies import (
    _lazy_get_enhanced_email_service,
    get_email_config_service,
)
from example_service.features.email.models import (
    EmailAuditLog,
    EmailConfig,
    EmailProviderType,
    EmailUsageLog,
)
from example_service.features.email.router import router
from example_service.features.email.service import EmailConfigService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
else:  # pragma: no cover - runtime placeholder for typing-only import
    AsyncGenerator = Any


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_email_service() -> AsyncMock:
    """Create a mock email service."""
    service = AsyncMock()
    service.invalidate_config_cache = MagicMock(return_value=1)
    service.send = AsyncMock()
    service.health_check = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_config_repository() -> MagicMock:
    """Create a mock config repository."""
    repo = MagicMock()
    repo.get_by_tenant_id = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update_config = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture
def mock_usage_repository() -> MagicMock:
    """Create a mock usage log repository."""
    repo = MagicMock()
    repo.get_usage_stats = AsyncMock(return_value={
        "total_emails": 0,
        "successful_emails": 0,
        "failed_emails": 0,
        "success_rate": 0.0,
        "total_recipients": 0,
        "total_cost_usd": None,
    })
    repo.get_usage_by_provider = AsyncMock(return_value={})
    return repo


@pytest.fixture
def mock_audit_repository() -> MagicMock:
    """Create a mock audit log repository."""
    repo = MagicMock()
    repo.get_audit_logs = AsyncMock()
    return repo


@pytest.fixture
async def email_client(
    mock_session: AsyncMock,
    mock_email_service: AsyncMock,
    mock_config_repository: MagicMock,
    mock_usage_repository: MagicMock,
    mock_audit_repository: MagicMock,
) -> AsyncGenerator[AsyncClient]:
    """Create HTTP client with email router and mocked dependencies."""
    app = FastAPI()
    app.include_router(router)

    # Create a mock service with our mock dependencies
    mock_service = EmailConfigService(
        session=mock_session,
        email_service=mock_email_service,
        config_repository=mock_config_repository,
        usage_repository=mock_usage_repository,
        audit_repository=mock_audit_repository,
    )

    # Override the service dependency
    async def override_get_email_config_service():
        yield mock_service

    def override_get_enhanced_email_service():
        return mock_email_service

    app.dependency_overrides[get_email_config_service] = override_get_email_config_service
    app.dependency_overrides[_lazy_get_enhanced_email_service] = override_get_enhanced_email_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    # Cleanup
    app.dependency_overrides.clear()


class TestCreateOrUpdateConfig:
    """Test POST /email/configs/{tenant_id} endpoint."""

    @pytest.mark.asyncio
    async def test_create_new_config(
        self,
        email_client: AsyncClient,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test creating a new email configuration."""
        # Mock no existing config
        mock_config_repository.get_by_tenant_id.return_value = None

        # Mock create to return a new config
        created_config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="user@example.com",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            encryption_version=1,
        )
        mock_config_repository.create.return_value = created_config

        response = await email_client.post(
            "/email/configs/tenant-123",
            json={
                "provider_type": "smtp",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "user@example.com",
                "smtp_password": "secret",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["tenant_id"] == "tenant-123"
        assert data["provider_type"] == "smtp"
        mock_config_repository.create.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_update_existing_config(
        self,
        email_client: AsyncClient,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test updating an existing email configuration."""
        # Mock existing config
        existing_config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="old.example.com",
            smtp_port=587,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            encryption_version=1,
        )
        mock_config_repository.get_by_tenant_id.return_value = existing_config
        mock_config_repository.update_config.return_value = existing_config

        response = await email_client.post(
            "/email/configs/tenant-123",
            json={
                "provider_type": "smtp",
                "smtp_host": "new.example.com",
                "smtp_port": 465,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["tenant_id"] == "tenant-123"
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")


class TestGetConfig:
    """Test GET /email/configs/{tenant_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_config_success(
        self, email_client: AsyncClient, mock_config_repository: MagicMock,
    ) -> None:
        """Test successfully retrieving email configuration."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="smtp.example.com",
            smtp_port=587,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            encryption_version=1,
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        response = await email_client.get("/email/configs/tenant-123")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == "tenant-123"
        assert data["provider_type"] == "smtp"
        assert data["smtp_host"] == "smtp.example.com"
        # Credentials should be masked
        assert "smtp_password" not in data
        assert "has_smtp_password" in data

    @pytest.mark.asyncio
    async def test_get_config_not_found(
        self, email_client: AsyncClient, mock_config_repository: MagicMock,
    ) -> None:
        """Test retrieving non-existent configuration."""
        mock_config_repository.get_by_tenant_id.return_value = None

        response = await email_client.get("/email/configs/tenant-123")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()


class TestUpdateConfig:
    """Test PUT /email/configs/{tenant_id} endpoint."""

    @pytest.mark.asyncio
    async def test_update_config_success(
        self,
        email_client: AsyncClient,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test successfully updating configuration."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="old.example.com",
            smtp_port=587,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            encryption_version=1,
        )
        mock_config_repository.get_by_tenant_id.return_value = config
        mock_config_repository.update_config.return_value = config

        response = await email_client.put(
            "/email/configs/tenant-123",
            json={"smtp_host": "new.example.com", "smtp_port": 465},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_update_config_not_found(
        self, email_client: AsyncClient, mock_config_repository: MagicMock,
    ) -> None:
        """Test updating non-existent configuration."""
        mock_config_repository.get_by_tenant_id.return_value = None

        response = await email_client.put(
            "/email/configs/tenant-123",
            json={"smtp_host": "new.example.com"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteConfig:
    """Test DELETE /email/configs/{tenant_id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_config_success(
        self,
        email_client: AsyncClient,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test successfully deleting configuration."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            encryption_version=1,
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        response = await email_client.delete("/email/configs/tenant-123")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_config_repository.delete.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_delete_config_not_found(
        self, email_client: AsyncClient, mock_config_repository: MagicMock,
    ) -> None:
        """Test deleting non-existent configuration."""
        mock_config_repository.get_by_tenant_id.return_value = None

        response = await email_client.delete("/email/configs/tenant-123")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTestConfig:
    """Test POST /email/configs/{tenant_id}/test endpoint."""

    @pytest.mark.asyncio
    async def test_send_test_email_success(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test successfully sending test email."""
        mock_email_service.send.return_value = MagicMock(
            success=True,
            message_id="msg-123",
            backend="smtp",
            error=None,
            error_code=None,
        )

        response = await email_client.post(
            "/email/configs/tenant-123/test",
            json={"to": "test@example.com", "use_tenant_config": True},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["message_id"] == "msg-123"
        assert data["provider"] == "smtp"
        assert "duration_ms" in data
        mock_email_service.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_test_email_failure(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test test email failure handling."""
        mock_email_service.send.return_value = MagicMock(
            success=False,
            message_id=None,
            backend="smtp",
            error="Connection failed",
            error_code="CONNECTION_ERROR",
        )

        response = await email_client.post(
            "/email/configs/tenant-123/test",
            json={"to": "test@example.com", "use_tenant_config": True},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Connection failed"
        assert data["error_code"] == "CONNECTION_ERROR"

    @pytest.mark.asyncio
    async def test_send_test_email_exception(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test test email exception handling."""
        mock_email_service.send.side_effect = Exception("Unexpected error")

        response = await email_client.post(
            "/email/configs/tenant-123/test",
            json={"to": "test@example.com", "use_tenant_config": True},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Unexpected error"
        assert data["error_code"] == "TEST_FAILED"


class TestCheckHealth:
    """Test GET /email/configs/{tenant_id}/health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_success(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test successful health check."""
        mock_email_service.health_check.return_value = True

        response = await email_client.get("/email/configs/tenant-123/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_healthy"] is True
        assert len(data["checks"]) == 1
        assert data["checks"][0]["healthy"] is True
        assert data["checks"][0]["provider"] == "configured"
        assert "response_time_ms" in data["checks"][0]

    @pytest.mark.asyncio
    async def test_health_check_failure(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test health check failure."""
        mock_email_service.health_check.return_value = False

        response = await email_client.get("/email/configs/tenant-123/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_healthy"] is False
        assert data["checks"][0]["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_exception(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test health check exception handling."""
        mock_email_service.health_check.side_effect = Exception("Health check failed")

        response = await email_client.get("/email/configs/tenant-123/health")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["overall_healthy"] is False
        assert data["checks"][0]["healthy"] is False
        assert "error" in data["checks"][0]


class TestListProviders:
    """Test GET /email/providers endpoint."""

    @pytest.mark.asyncio
    async def test_list_providers(
        self, email_client: AsyncClient, mock_email_service: AsyncMock,
    ) -> None:
        """Test listing available email providers."""
        response = await email_client.get("/email/providers")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) > 0

        # Check that all expected providers are present
        provider_types = [p["provider_type"] for p in data["providers"]]
        assert "smtp" in provider_types
        assert "aws_ses" in provider_types
        assert "sendgrid" in provider_types
        assert "mailgun" in provider_types
        assert "console" in provider_types
        assert "file" in provider_types

        # Check provider structure
        smtp_provider = next(p for p in data["providers"] if p["provider_type"] == "smtp")
        assert "name" in smtp_provider
        assert "description" in smtp_provider
        assert "required_fields" in smtp_provider
        assert "optional_fields" in smtp_provider
        assert "supports_attachments" in smtp_provider
        assert "supports_html" in smtp_provider


class TestGetUsageStats:
    """Test GET /email/configs/{tenant_id}/usage endpoint."""

    @pytest.mark.asyncio
    async def test_get_usage_stats(
        self, email_client: AsyncClient, mock_usage_repository: MagicMock,
    ) -> None:
        """Test getting usage statistics."""
        mock_usage_repository.get_usage_stats.return_value = {
            "total_emails": 5,
            "successful_emails": 5,
            "failed_emails": 0,
            "success_rate": 100.0,
            "total_recipients": 5,
            "total_cost_usd": 0.003,
        }
        mock_usage_repository.get_usage_by_provider.return_value = {
            "smtp": {"count": 5, "cost": 0.003},
        }

        response = await email_client.get("/email/configs/tenant-123/usage")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == "tenant-123"
        assert "total_emails" in data
        assert "successful_emails" in data
        assert "failed_emails" in data
        assert "success_rate" in data
        assert "emails_by_provider" in data
        assert "period_start" in data
        assert "period_end" in data

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_date_range(
        self, email_client: AsyncClient, mock_usage_repository: MagicMock,
    ) -> None:
        """Test getting usage statistics with custom date range."""
        mock_usage_repository.get_usage_stats.return_value = {
            "total_emails": 1,
            "successful_emails": 1,
            "failed_emails": 0,
            "success_rate": 100.0,
            "total_recipients": 1,
            "total_cost_usd": None,
        }
        mock_usage_repository.get_usage_by_provider.return_value = {}

        # Use URL-safe format without timezone (FastAPI handles UTC naively)
        start_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        end_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        response = await email_client.get(
            f"/email/configs/tenant-123/usage?start_date={start_date}&end_date={end_date}",
        )

        assert response.status_code == status.HTTP_200_OK


class TestGetAuditLogs:
    """Test GET /email/configs/{tenant_id}/audit-logs endpoint."""

    @pytest.mark.asyncio
    async def test_get_audit_logs(
        self, email_client: AsyncClient, mock_audit_repository: MagicMock,
    ) -> None:
        """Test getting audit logs."""
        # Mock audit logs
        logs = [
            EmailAuditLog(
                id=f"audit-{i}",
                tenant_id="tenant-123",
                recipient_hash="hash-123",
                status="sent",
                provider="smtp",
                created_at=datetime.now(UTC) - timedelta(hours=i),
            )
            for i in range(3)
        ]

        # Mock SearchResult
        from example_service.core.database.repository import SearchResult
        mock_audit_repository.get_audit_logs.return_value = SearchResult(
            items=logs,
            total=3,
            limit=50,
            offset=0,
        )

        response = await email_client.get("/email/configs/tenant-123/audit-logs")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "logs" in data
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 50
        assert len(data["logs"]) == 3

    @pytest.mark.asyncio
    async def test_get_audit_logs_pagination(
        self, email_client: AsyncClient, mock_audit_repository: MagicMock,
    ) -> None:
        """Test getting audit logs with pagination."""
        logs = [
            EmailAuditLog(
                id=f"audit-{i}",
                tenant_id="tenant-123",
                recipient_hash="hash-123",
                status="sent",
                provider="smtp",
                created_at=datetime.now(UTC),
            )
            for i in range(5)
        ]

        from example_service.core.database.repository import SearchResult
        mock_audit_repository.get_audit_logs.return_value = SearchResult(
            items=logs,
            total=10,
            limit=5,
            offset=5,
        )

        response = await email_client.get("/email/configs/tenant-123/audit-logs?page=2&page_size=5")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 5
        assert data["total"] == 10
