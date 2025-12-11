"""Unit tests for EmailConfigService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.features.email.exceptions import (
    EmailConfigNotFoundError,
    EmailConfigValidationError,
    EmailSendError,
)
from example_service.features.email.models import (
    EmailConfig,
    EmailProviderType,
)
from example_service.features.email.service import EmailConfigService


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
    """Create a mock enhanced email service."""
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
    repo.get_audit_logs_cursor = AsyncMock(return_value=([], None, None, False))
    return repo


@pytest.fixture
def service(
    mock_session: AsyncMock,
    mock_email_service: AsyncMock,
    mock_config_repository: MagicMock,
    mock_usage_repository: MagicMock,
    mock_audit_repository: MagicMock,
) -> EmailConfigService:
    """Create an EmailConfigService with mocked dependencies."""
    return EmailConfigService(
        session=mock_session,
        email_service=mock_email_service,
        config_repository=mock_config_repository,
        usage_repository=mock_usage_repository,
        audit_repository=mock_audit_repository,
    )


class TestProviderValidation:
    """Tests for provider-specific validation."""

    def test_provider_requirements_defined(self) -> None:
        """Test that all providers have requirements defined."""
        assert EmailProviderType.SMTP in EmailConfigService.PROVIDER_REQUIREMENTS
        assert EmailProviderType.AWS_SES in EmailConfigService.PROVIDER_REQUIREMENTS
        assert EmailProviderType.SENDGRID in EmailConfigService.PROVIDER_REQUIREMENTS
        assert EmailProviderType.MAILGUN in EmailConfigService.PROVIDER_REQUIREMENTS
        assert EmailProviderType.CONSOLE in EmailConfigService.PROVIDER_REQUIREMENTS
        assert EmailProviderType.FILE in EmailConfigService.PROVIDER_REQUIREMENTS

    def test_validate_provider_config_smtp_valid(self, service: EmailConfigService) -> None:
        """Test SMTP validation passes with required fields."""
        config_data = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
        }
        # Should not raise
        service.validate_provider_config(EmailProviderType.SMTP, config_data)

    def test_validate_provider_config_smtp_missing_fields(self, service: EmailConfigService) -> None:
        """Test SMTP validation fails when required fields are missing."""
        config_data = {
            "smtp_host": "smtp.example.com",
            # Missing smtp_port
        }
        with pytest.raises(EmailConfigValidationError) as exc_info:
            service.validate_provider_config(EmailProviderType.SMTP, config_data)

        assert "smtp_port" in exc_info.value.missing_fields
        assert exc_info.value.provider_type == "smtp"

    def test_validate_provider_config_aws_ses_valid(self, service: EmailConfigService) -> None:
        """Test AWS SES validation passes with required fields."""
        config_data = {
            "aws_access_key": "AKIAEXAMPLE",
            "aws_secret_key": "secret123",
            "aws_region": "us-east-1",
        }
        # Should not raise
        service.validate_provider_config(EmailProviderType.AWS_SES, config_data)

    def test_validate_provider_config_aws_ses_missing_fields(self, service: EmailConfigService) -> None:
        """Test AWS SES validation fails when required fields are missing."""
        config_data = {
            "aws_access_key": "AKIAEXAMPLE",
            # Missing aws_secret_key and aws_region
        }
        with pytest.raises(EmailConfigValidationError) as exc_info:
            service.validate_provider_config(EmailProviderType.AWS_SES, config_data)

        assert "aws_secret_key" in exc_info.value.missing_fields
        assert "aws_region" in exc_info.value.missing_fields

    def test_validate_provider_config_sendgrid_valid(self, service: EmailConfigService) -> None:
        """Test SendGrid validation passes with required fields."""
        config_data = {"api_key": "SG.xxx"}
        # Should not raise
        service.validate_provider_config(EmailProviderType.SENDGRID, config_data)

    def test_validate_provider_config_console_no_requirements(self, service: EmailConfigService) -> None:
        """Test console provider has no requirements."""
        config_data = {}
        # Should not raise
        service.validate_provider_config(EmailProviderType.CONSOLE, config_data)


class TestGetConfig:
    """Tests for get_config method."""

    @pytest.mark.asyncio
    async def test_get_config_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test getting a config that exists."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        result = await service.get_config("tenant-123")

        assert result == config
        mock_config_repository.get_by_tenant_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_config_not_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test getting a config that doesn't exist."""
        mock_config_repository.get_by_tenant_id.return_value = None

        result = await service.get_config("tenant-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_config_or_raise_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test get_config_or_raise when config exists."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        result = await service.get_config_or_raise("tenant-123")

        assert result == config

    @pytest.mark.asyncio
    async def test_get_config_or_raise_not_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test get_config_or_raise raises when config doesn't exist."""
        mock_config_repository.get_by_tenant_id.return_value = None

        with pytest.raises(EmailConfigNotFoundError) as exc_info:
            await service.get_config_or_raise("tenant-123")

        assert exc_info.value.tenant_id == "tenant-123"


class TestCreateOrUpdateConfig:
    """Tests for create_or_update_config method."""

    @pytest.mark.asyncio
    async def test_create_new_config(
        self,
        service: EmailConfigService,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test creating a new configuration."""
        from example_service.features.email.schemas import EmailConfigCreate

        mock_config_repository.get_by_tenant_id.return_value = None

        created_config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="smtp.example.com",
            smtp_port=587,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.create.return_value = created_config

        config_data = EmailConfigCreate(
            provider_type=EmailProviderType.SMTP,
            smtp_host="smtp.example.com",
            smtp_port=587,
        )

        result = await service.create_or_update_config("tenant-123", config_data)

        assert result == created_config
        mock_config_repository.create.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_update_existing_config(
        self,
        service: EmailConfigService,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test updating an existing configuration."""
        from example_service.features.email.schemas import EmailConfigCreate

        existing_config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="old.example.com",
            smtp_port=587,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = existing_config
        mock_config_repository.update_config.return_value = existing_config

        config_data = EmailConfigCreate(
            provider_type=EmailProviderType.SMTP,
            smtp_host="new.example.com",
            smtp_port=465,
        )

        await service.create_or_update_config("tenant-123", config_data)

        mock_config_repository.update_config.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_create_config_validation_error(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test that validation error is raised for invalid config."""
        from example_service.features.email.schemas import EmailConfigCreate

        mock_config_repository.get_by_tenant_id.return_value = None

        # Missing required fields for SMTP
        config_data = EmailConfigCreate(
            provider_type=EmailProviderType.SMTP,
            # Missing smtp_host and smtp_port
        )

        with pytest.raises(EmailConfigValidationError):
            await service.create_or_update_config("tenant-123", config_data)


class TestUpdateConfig:
    """Tests for update_config method."""

    @pytest.mark.asyncio
    async def test_update_config_success(
        self,
        service: EmailConfigService,
        mock_session: AsyncMock,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test successfully updating configuration fields."""
        from example_service.features.email.schemas import EmailConfigUpdate

        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            smtp_host="old.example.com",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config
        mock_config_repository.update_config.return_value = config

        update_data = EmailConfigUpdate(smtp_host="new.example.com")

        result = await service.update_config("tenant-123", update_data)

        assert result is not None
        mock_config_repository.update_config.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_update_config_not_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test updating non-existent configuration."""
        from example_service.features.email.schemas import EmailConfigUpdate

        mock_config_repository.get_by_tenant_id.return_value = None

        update_data = EmailConfigUpdate(smtp_host="new.example.com")

        result = await service.update_config("tenant-123", update_data)

        assert result is None


class TestDeleteConfig:
    """Tests for delete_config method."""

    @pytest.mark.asyncio
    async def test_delete_config_success(
        self,
        service: EmailConfigService,
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
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        result = await service.delete_config("tenant-123")

        assert result is True
        mock_config_repository.delete.assert_awaited_once_with(mock_session, config)
        mock_session.commit.assert_awaited_once()
        mock_email_service.invalidate_config_cache.assert_called_once_with("tenant-123")

    @pytest.mark.asyncio
    async def test_delete_config_not_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test deleting non-existent configuration."""
        mock_config_repository.get_by_tenant_id.return_value = None

        result = await service.delete_config("tenant-123")

        assert result is False


class TestTestConfig:
    """Tests for test_config method."""

    @pytest.mark.asyncio
    async def test_test_config_success(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
    ) -> None:
        """Test sending test email successfully."""
        mock_email_service.send.return_value = MagicMock(
            success=True,
            message_id="msg-123",
            backend="smtp",
            error=None,
            error_code=None,
        )

        result = await service.test_config("tenant-123", "test@example.com")

        assert result.success is True
        assert result.message_id == "msg-123"
        assert result.provider == "smtp"
        assert result.duration_ms >= 0  # May be 0 in tests due to mock speed

    @pytest.mark.asyncio
    async def test_test_config_failure(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
    ) -> None:
        """Test handling test email failure."""
        mock_email_service.send.return_value = MagicMock(
            success=False,
            message_id=None,
            backend="smtp",
            error="Connection refused",
            error_code="CONNECTION_ERROR",
        )

        result = await service.test_config("tenant-123", "test@example.com")

        assert result.success is False
        assert result.error == "Connection refused"
        assert result.error_code == "CONNECTION_ERROR"

    @pytest.mark.asyncio
    async def test_test_config_exception(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
    ) -> None:
        """Test handling exception during test email."""
        mock_email_service.send.side_effect = Exception("Network error")

        result = await service.test_config("tenant-123", "test@example.com")

        assert result.success is False
        assert result.error == "Network error"
        assert result.error_code == "TEST_FAILED"


class TestCheckHealth:
    """Tests for check_health method."""

    @pytest.mark.asyncio
    async def test_check_health_success(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
    ) -> None:
        """Test successful health check."""
        mock_email_service.health_check.return_value = True

        is_healthy, response_time_ms, error = await service.check_health("tenant-123")

        assert is_healthy is True
        assert response_time_ms is not None
        assert error is None

    @pytest.mark.asyncio
    async def test_check_health_unhealthy(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
    ) -> None:
        """Test health check returns unhealthy."""
        mock_email_service.health_check.return_value = False

        is_healthy, response_time_ms, error = await service.check_health("tenant-123")

        assert is_healthy is False
        assert response_time_ms is not None
        assert error == "Health check failed"

    @pytest.mark.asyncio
    async def test_check_health_exception(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
    ) -> None:
        """Test health check exception handling."""
        mock_email_service.health_check.side_effect = Exception("Connection failed")

        is_healthy, response_time_ms, error = await service.check_health("tenant-123")

        assert is_healthy is False
        assert response_time_ms is None
        assert error == "Connection failed"


class TestGetUsageStats:
    """Tests for get_usage_stats method."""

    @pytest.mark.asyncio
    async def test_get_usage_stats(
        self,
        service: EmailConfigService,
        mock_usage_repository: MagicMock,
    ) -> None:
        """Test getting usage statistics."""
        mock_usage_repository.get_usage_stats.return_value = {
            "total_emails": 100,
            "successful_emails": 95,
            "failed_emails": 5,
            "success_rate": 95.0,
            "total_recipients": 200,
            "total_cost_usd": 0.50,
        }
        mock_usage_repository.get_usage_by_provider.return_value = {
            "smtp": {"count": 100, "cost": 0.50},
        }

        result = await service.get_usage_stats("tenant-123")

        assert result.tenant_id == "tenant-123"
        assert result.total_emails == 100
        assert result.successful_emails == 95
        assert result.success_rate == 95.0

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_date_range(
        self,
        service: EmailConfigService,
        mock_usage_repository: MagicMock,
    ) -> None:
        """Test getting usage statistics with custom date range."""
        mock_usage_repository.get_usage_stats.return_value = {
            "total_emails": 50,
            "successful_emails": 50,
            "failed_emails": 0,
            "success_rate": 100.0,
            "total_recipients": 50,
            "total_cost_usd": None,
        }
        mock_usage_repository.get_usage_by_provider.return_value = {}

        start_date = datetime.now(UTC) - timedelta(days=7)
        end_date = datetime.now(UTC)

        result = await service.get_usage_stats(
            "tenant-123",
            start_date=start_date,
            end_date=end_date,
        )

        assert result.tenant_id == "tenant-123"
        mock_usage_repository.get_usage_stats.assert_awaited_once()

    def test_get_rate_limit_hits_happy_path(
        self,
        service: EmailConfigService,
    ) -> None:
        """Rate limit metrics aggregated per tenant."""
        sample_for_tenant = MagicMock(labels={"tenant_id": "tenant-123"}, value=2)
        sample_other = MagicMock(labels={"tenant_id": "tenant-456"}, value=4)
        collection = MagicMock(samples=[sample_for_tenant, sample_other])

        with patch(
            "example_service.features.email.service.email_rate_limit_hits_total.collect",
            return_value=[collection],
        ):
            result = service._get_rate_limit_hits("tenant-123")

        assert result == 2

    def test_get_rate_limit_hits_handles_errors(
        self,
        service: EmailConfigService,
    ) -> None:
        """Errors from Prometheus collection should be swallowed."""
        with patch(
            "example_service.features.email.service.email_rate_limit_hits_total.collect",
            side_effect=RuntimeError("boom"),
        ):
            assert service._get_rate_limit_hits("tenant-123") == 0


class TestGetAuditLogs:
    """Tests for get_audit_logs methods."""

    @pytest.mark.asyncio
    async def test_get_audit_logs_offset_based(
        self,
        service: EmailConfigService,
        mock_audit_repository: MagicMock,
    ) -> None:
        """Test getting audit logs with offset-based pagination."""
        from example_service.core.database.repository import SearchResult
        from example_service.features.email.models import EmailAuditLog

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

        mock_audit_repository.get_audit_logs.return_value = SearchResult(
            items=logs,
            total=5,
            limit=50,
            offset=0,
        )

        result = await service.get_audit_logs("tenant-123", page=1, page_size=50)

        assert result.total == 5
        assert len(result.items) == 5

    @pytest.mark.asyncio
    async def test_get_audit_logs_cursor_based(
        self,
        service: EmailConfigService,
        mock_audit_repository: MagicMock,
    ) -> None:
        """Test getting audit logs with cursor-based pagination."""
        from example_service.features.email.models import EmailAuditLog

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

        mock_audit_repository.get_audit_logs_cursor.return_value = (
            logs,
            "next-cursor-abc",
            None,
            True,
        )

        result = await service.get_audit_logs_cursor("tenant-123", limit=5)

        assert len(result["items"]) == 5
        assert result["next_cursor"] == "next-cursor-abc"
        assert result["has_more"] is True


class TestSendEmail:
    """Tests for send_email method."""

    @pytest.mark.asyncio
    async def test_send_email_success(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test sending email successfully."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        mock_email_service.send.return_value = MagicMock(
            success=True,
            message_id="msg-123",
            backend="smtp",
            error=None,
            error_code=None,
        )

        result = await service.send_email(
            tenant_id="tenant-123",
            to=["test@example.com"],
            subject="Test Subject",
            body="Test body",
        )

        assert result.success is True
        assert result.message_id == "msg-123"
        assert result.recipients_count == 1

    @pytest.mark.asyncio
    async def test_send_email_config_not_found(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test sending email when config doesn't exist."""
        mock_config_repository.get_by_tenant_id.return_value = None

        with pytest.raises(EmailConfigNotFoundError):
            await service.send_email(
                tenant_id="tenant-123",
                to=["test@example.com"],
                subject="Test Subject",
                body="Test body",
            )

    @pytest.mark.asyncio
    async def test_send_email_config_disabled(
        self,
        service: EmailConfigService,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test sending email when config is disabled."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            is_active=False,  # Disabled
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        with pytest.raises(EmailSendError) as exc_info:
            await service.send_email(
                tenant_id="tenant-123",
                to=["test@example.com"],
                subject="Test Subject",
                body="Test body",
            )

        assert exc_info.value.error_code == "CONFIG_DISABLED"

    @pytest.mark.asyncio
    async def test_send_email_provider_failure(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test handling provider failure during send."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        mock_email_service.send.return_value = MagicMock(
            success=False,
            message_id=None,
            backend="smtp",
            error="Mailbox full",
            error_code="MAILBOX_FULL",
        )

        result = await service.send_email(
            tenant_id="tenant-123",
            to=["test@example.com"],
            subject="Test Subject",
            body="Test body",
        )

        assert result.success is False
        assert result.error == "Mailbox full"

    @pytest.mark.asyncio
    async def test_send_email_exception(
        self,
        service: EmailConfigService,
        mock_email_service: AsyncMock,
        mock_config_repository: MagicMock,
    ) -> None:
        """Test handling exception during send."""
        config = EmailConfig(
            id="config-123",
            tenant_id="tenant-123",
            provider_type=EmailProviderType.SMTP,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_config_repository.get_by_tenant_id.return_value = config

        mock_email_service.send.side_effect = Exception("Network error")

        with pytest.raises(EmailSendError) as exc_info:
            await service.send_email(
                tenant_id="tenant-123",
                to=["test@example.com"],
                subject="Test Subject",
                body="Test body",
            )

        assert exc_info.value.error_code == "SEND_FAILED"


class TestGetAvailableProviders:
    """Tests for get_available_providers method."""

    def test_get_available_providers(self, service: EmailConfigService) -> None:
        """Test getting list of available providers."""
        providers = service.get_available_providers()

        assert len(providers) == 6

        # Check SMTP provider
        smtp = next(p for p in providers if p["provider_type"] == EmailProviderType.SMTP)
        assert "smtp_host" in smtp["required_fields"]
        assert "smtp_port" in smtp["required_fields"]

        # Check AWS SES provider
        ses = next(p for p in providers if p["provider_type"] == EmailProviderType.AWS_SES)
        assert "aws_access_key" in ses["required_fields"]
        assert "aws_secret_key" in ses["required_fields"]
        assert "aws_region" in ses["required_fields"]

        # Check SendGrid provider
        sendgrid = next(p for p in providers if p["provider_type"] == EmailProviderType.SENDGRID)
        assert "api_key" in sendgrid["required_fields"]

        # Check Console provider (development)
        console = next(p for p in providers if p["provider_type"] == EmailProviderType.CONSOLE)
        assert console["required_fields"] == []
