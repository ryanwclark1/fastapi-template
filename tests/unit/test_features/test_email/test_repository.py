"""Unit tests for Email Repository classes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from example_service.features.email.models import (
    EmailAuditLog,
    EmailConfig,
    EmailProviderType,
    EmailUsageLog,
)
from example_service.features.email.repository import (
    EmailAuditLogRepository,
    EmailConfigRepository,
    EmailUsageLogRepository,
    get_email_audit_log_repository,
    get_email_config_repository,
    get_email_usage_log_repository,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


class TestEmailConfigRepository:
    """Tests for EmailConfigRepository."""

    def test_init(self) -> None:
        """Test repository initialization."""
        repo = EmailConfigRepository()
        assert repo.model == EmailConfig

    @pytest.mark.asyncio
    async def test_get_by_tenant_id_found(self, mock_session: AsyncMock) -> None:
        """Test getting config by tenant_id when it exists."""
        repo = EmailConfigRepository()

        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Mock the get_by method from base repository
        with patch.object(repo, "get_by", new_callable=AsyncMock) as mock_get_by:
            mock_get_by.return_value = config

            result = await repo.get_by_tenant_id(mock_session, "tenant-123")

            assert result == config
            mock_get_by.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_tenant_id_not_found(self, mock_session: AsyncMock) -> None:
        """Test getting config by tenant_id when it doesn't exist."""
        repo = EmailConfigRepository()

        with patch.object(repo, "get_by", new_callable=AsyncMock) as mock_get_by:
            mock_get_by.return_value = None

            result = await repo.get_by_tenant_id(mock_session, "tenant-123")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_active_by_tenant_id(self, mock_session: AsyncMock) -> None:
        """Test getting active config for a tenant."""
        repo = EmailConfigRepository()

        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_session.execute.return_value = mock_result

        result = await repo.get_active_by_tenant_id(mock_session, "tenant-123")

        assert result == config
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_active_configs(self, mock_session: AsyncMock) -> None:
        """Test listing all active configurations."""
        repo = EmailConfigRepository()

        configs = [
            EmailConfig(
                id=f"config-{i}",
                tenant_id=f"tenant-{i}",
                provider_type=EmailProviderType.SMTP,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            for i in range(3)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = configs
        mock_session.execute.return_value = mock_result

        result = await repo.list_active_configs(mock_session, limit=10, offset=0)

        assert len(result) == 3
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_by_provider_type(self, mock_session: AsyncMock) -> None:
        """Test listing configs by provider type."""
        repo = EmailConfigRepository()

        configs = [
            EmailConfig(
                id=f"config-{i}",
                tenant_id=f"tenant-{i}",
                provider_type=EmailProviderType.SMTP,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            for i in range(2)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = configs
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_provider_type(mock_session, "smtp", limit=10)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_update_config(self, mock_session: AsyncMock) -> None:
        """Test updating a configuration."""
        repo = EmailConfigRepository()

        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="old.example.com",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        update_data = {"smtp_host": "new.example.com", "smtp_port": 465}

        result = await repo.update_config(mock_session, config, update_data)

        assert result.smtp_host == "new.example.com"
        assert result.smtp_port == 465
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once()


class TestEmailUsageLogRepository:
    """Tests for EmailUsageLogRepository."""

    def test_init(self) -> None:
        """Test repository initialization."""
        repo = EmailUsageLogRepository()
        assert repo.model == EmailUsageLog

    @pytest.mark.asyncio
    async def test_get_usage_logs(self, mock_session: AsyncMock) -> None:
        """Test getting usage logs for a tenant."""
        repo = EmailUsageLogRepository()

        logs = [
            EmailUsageLog(
                id=f"log-{i}",
                tenant_id="tenant-123",
                provider="smtp",
                recipients_count=1,
                success=True,
                created_at=datetime.now(UTC) - timedelta(hours=i),
            )
            for i in range(3)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = logs
        mock_session.execute.return_value = mock_result

        result = await repo.get_usage_logs(
            mock_session,
            "tenant-123",
            start_date=datetime.now(UTC) - timedelta(days=30),
            end_date=datetime.now(UTC),
        )

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_usage_stats(self, mock_session: AsyncMock) -> None:
        """Test getting aggregated usage statistics."""
        repo = EmailUsageLogRepository()

        mock_row = MagicMock()
        mock_row.total_emails = 100
        mock_row.successful_emails = 95
        mock_row.total_recipients = 200
        mock_row.total_cost = 0.50

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        result = await repo.get_usage_stats(mock_session, "tenant-123")

        assert result["total_emails"] == 100
        assert result["successful_emails"] == 95
        assert result["failed_emails"] == 5
        assert result["success_rate"] == 95.0

    @pytest.mark.asyncio
    async def test_get_usage_by_provider(self, mock_session: AsyncMock) -> None:
        """Test getting usage statistics grouped by provider."""
        repo = EmailUsageLogRepository()

        rows = [
            MagicMock(provider="smtp", count=50, cost=0.25),
            MagicMock(provider="sendgrid", count=50, cost=0.25),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        result = await repo.get_usage_by_provider(mock_session, "tenant-123")

        assert "smtp" in result
        assert "sendgrid" in result
        assert result["smtp"]["count"] == 50
        assert result["sendgrid"]["count"] == 50

    @pytest.mark.asyncio
    async def test_get_all_usage_logs(self, mock_session: AsyncMock) -> None:
        """Test getting all usage logs for admin reporting."""
        repo = EmailUsageLogRepository()

        logs = [
            EmailUsageLog(
                id=f"log-{i}",
                tenant_id=f"tenant-{i % 3}",
                provider="smtp",
                recipients_count=1,
                success=True,
                created_at=datetime.now(UTC),
            )
            for i in range(10)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = logs
        mock_session.execute.return_value = mock_result

        result = await repo.get_all_usage_logs(
            mock_session,
            start_date=datetime.now(UTC) - timedelta(days=30),
        )

        assert len(result) == 10


class TestEmailAuditLogRepository:
    """Tests for EmailAuditLogRepository."""

    def test_init(self) -> None:
        """Test repository initialization."""
        repo = EmailAuditLogRepository()
        assert repo.model == EmailAuditLog

    @pytest.mark.asyncio
    async def test_get_audit_logs(self, mock_session: AsyncMock) -> None:
        """Test getting audit logs with offset-based pagination."""
        repo = EmailAuditLogRepository()

        with patch.object(repo, "search", new_callable=AsyncMock) as mock_search:
            from example_service.core.database.repository import SearchResult

            logs = [
                EmailAuditLog(
                    id=f"audit-{i}",
                    tenant_id="tenant-123",
                    recipient_hash="hash-123",
                    status="sent",
                    created_at=datetime.now(UTC),
                )
                for i in range(5)
            ]

            mock_search.return_value = SearchResult(
                items=logs,
                total=5,
                limit=50,
                offset=0,
            )

            result = await repo.get_audit_logs(mock_session, "tenant-123", limit=50, offset=0)

            assert result.total == 5
            assert len(result.items) == 5

    @pytest.mark.asyncio
    async def test_get_audit_logs_cursor_no_cursor(self, mock_session: AsyncMock) -> None:
        """Test cursor-based pagination without initial cursor."""
        repo = EmailAuditLogRepository()

        now = datetime.now(UTC)
        logs = [
            EmailAuditLog(
                id=f"audit-{i}",
                tenant_id="tenant-123",
                recipient_hash="hash-123",
                status="sent",
                created_at=now - timedelta(hours=i),
            )
            for i in range(6)  # 6 items = 5 + 1 for has_more check
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = logs
        mock_session.execute.return_value = mock_result

        items, next_cursor, prev_cursor, has_more = await repo.get_audit_logs_cursor(
            mock_session,
            "tenant-123",
            limit=5,
            cursor=None,
        )

        assert len(items) == 5
        assert has_more is True
        assert next_cursor is not None
        assert prev_cursor is None  # No prev cursor for first page

    @pytest.mark.asyncio
    async def test_get_audit_logs_cursor_with_cursor(self, mock_session: AsyncMock) -> None:
        """Test cursor-based pagination with cursor."""
        repo = EmailAuditLogRepository()

        import base64

        # Create a valid cursor
        now = datetime.now(UTC)
        cursor_str = f"{now.isoformat()}_audit-0"
        cursor = base64.urlsafe_b64encode(cursor_str.encode()).decode()

        logs = [
            EmailAuditLog(
                id=f"audit-{i + 5}",
                tenant_id="tenant-123",
                recipient_hash="hash-123",
                status="sent",
                created_at=now - timedelta(hours=i + 5),
            )
            for i in range(3)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = logs
        mock_session.execute.return_value = mock_result

        items, _next_cursor, prev_cursor, has_more = await repo.get_audit_logs_cursor(
            mock_session,
            "tenant-123",
            limit=5,
            cursor=cursor,
        )

        assert len(items) == 3
        assert has_more is False
        assert prev_cursor is not None  # Has prev cursor after first page

    @pytest.mark.asyncio
    async def test_get_by_recipient_hash(self, mock_session: AsyncMock) -> None:
        """Test finding audit logs by recipient hash."""
        repo = EmailAuditLogRepository()

        logs = [
            EmailAuditLog(
                id=f"audit-{i}",
                tenant_id="tenant-123",
                recipient_hash="hash-abc123",
                status="sent",
                created_at=datetime.now(UTC),
            )
            for i in range(2)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = logs
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_recipient_hash(mock_session, "hash-abc123")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_by_status(self, mock_session: AsyncMock) -> None:
        """Test finding audit logs by status."""
        repo = EmailAuditLogRepository()

        logs = [
            EmailAuditLog(
                id=f"audit-{i}",
                tenant_id="tenant-123",
                recipient_hash="hash-123",
                status="failed",
                created_at=datetime.now(UTC),
            )
            for i in range(3)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = logs
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_status(mock_session, "failed", tenant_id="tenant-123")

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_count_by_status(self, mock_session: AsyncMock) -> None:
        """Test counting audit logs grouped by status."""
        repo = EmailAuditLogRepository()

        rows = [
            MagicMock(status="sent", count=100),
            MagicMock(status="failed", count=5),
            MagicMock(status="bounced", count=2),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        result = await repo.count_by_status(mock_session, "tenant-123")

        assert result["sent"] == 100
        assert result["failed"] == 5
        assert result["bounced"] == 2


class TestRepositorySingletons:
    """Tests for repository singleton factory functions."""

    def test_get_email_config_repository_singleton(self) -> None:
        """Test that get_email_config_repository returns singleton."""
        # Reset the singleton
        import example_service.features.email.repository as repo_module
        repo_module._email_config_repository = None

        repo1 = get_email_config_repository()
        repo2 = get_email_config_repository()

        assert repo1 is repo2

    def test_get_email_usage_log_repository_singleton(self) -> None:
        """Test that get_email_usage_log_repository returns singleton."""
        import example_service.features.email.repository as repo_module
        repo_module._email_usage_log_repository = None

        repo1 = get_email_usage_log_repository()
        repo2 = get_email_usage_log_repository()

        assert repo1 is repo2

    def test_get_email_audit_log_repository_singleton(self) -> None:
        """Test that get_email_audit_log_repository returns singleton."""
        import example_service.features.email.repository as repo_module
        repo_module._email_audit_log_repository = None

        repo1 = get_email_audit_log_repository()
        repo2 = get_email_audit_log_repository()

        assert repo1 is repo2
