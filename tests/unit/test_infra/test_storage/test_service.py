"""Unit tests for StorageService bucket resolution and core logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.core.settings.storage import StorageSettings
from example_service.infra.storage.backends import TenantContext
from example_service.infra.storage.exceptions import StorageError
from example_service.infra.storage.service import StorageService


class TestBucketResolution:
    """Test bucket resolution logic in StorageService."""

    def test_explicit_bucket_takes_priority(self):
        """Test that explicit bucket parameter takes highest priority."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            bucket_naming_pattern="{tenant_slug}-uploads",
            shared_bucket="shared-bucket",
        )
        service = StorageService(settings)

        tenant = TenantContext(
            tenant_uuid="tenant-123",
            tenant_slug="acme",
        )

        # Explicit bucket should override everything
        resolved = service._resolve_bucket(tenant, bucket="explicit-bucket")
        assert resolved == "explicit-bucket"

    def test_tenant_bucket_with_multi_tenancy_enabled(self):
        """Test tenant bucket resolution when multi-tenancy is enabled."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            bucket_naming_pattern="{tenant_slug}-uploads",
            shared_bucket="shared-bucket",
        )
        service = StorageService(settings)

        tenant = TenantContext(
            tenant_uuid="tenant-123",
            tenant_slug="acme",
        )

        resolved = service._resolve_bucket(tenant, bucket=None)
        assert resolved == "acme-uploads"

    def test_tenant_bucket_with_uuid_pattern(self):
        """Test tenant bucket resolution using UUID in pattern."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            bucket_naming_pattern="tenant-{tenant_uuid}",
        )
        service = StorageService(settings)

        tenant = TenantContext(
            tenant_uuid="abc-123",
            tenant_slug="acme",
        )

        resolved = service._resolve_bucket(tenant, bucket=None)
        assert resolved == "tenant-abc-123"

    def test_fallback_to_shared_bucket(self):
        """Test fallback to shared bucket when no tenant context."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            shared_bucket="shared-uploads",
        )
        service = StorageService(settings)

        resolved = service._resolve_bucket(tenant_context=None, bucket=None)
        assert resolved == "shared-uploads"

    def test_fallback_to_default_bucket_when_no_shared(self):
        """Test fallback to default bucket when shared_bucket is None."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            shared_bucket=None,  # Will use default bucket
        )
        service = StorageService(settings)

        resolved = service._resolve_bucket(tenant_context=None, bucket=None)
        assert resolved == "default-bucket"

    def test_single_tenant_mode_uses_default_bucket(self):
        """Test that single-tenant mode (multi_tenancy=False) uses default bucket."""
        settings = StorageSettings(
            enabled=True,
            bucket="my-bucket",
            enable_multi_tenancy=False,
        )
        service = StorageService(settings)

        tenant = TenantContext(
            tenant_uuid="tenant-123",
            tenant_slug="acme",
        )

        # Even with tenant context, should use default bucket in single-tenant mode
        resolved = service._resolve_bucket(tenant, bucket=None)
        assert resolved == "my-bucket"

    def test_require_tenant_context_raises_when_missing(self):
        """Test that require_tenant_context=True raises error when context missing."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            require_tenant_context=True,
        )
        service = StorageService(settings)

        with pytest.raises(StorageError) as exc_info:
            service._resolve_bucket(tenant_context=None, bucket=None)

        assert "Tenant context required" in str(exc_info.value)
        assert exc_info.value.code == "TENANT_CONTEXT_REQUIRED"

    def test_require_tenant_context_allows_explicit_bucket(self):
        """Test that explicit bucket works even with require_tenant_context=True."""
        settings = StorageSettings(
            enabled=True,
            bucket="default-bucket",
            enable_multi_tenancy=True,
            require_tenant_context=True,
        )
        service = StorageService(settings)

        # Explicit bucket should bypass tenant requirement
        resolved = service._resolve_bucket(tenant_context=None, bucket="explicit-bucket")
        assert resolved == "explicit-bucket"


class TestStorageServiceProperties:
    """Test StorageService properties and state management."""

    def test_is_ready_when_not_initialized(self):
        """Test is_ready returns False when not initialized."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        assert service.is_ready is False

    def test_backend_name_when_not_initialized(self):
        """Test backend_name returns None when not initialized."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        assert service.backend_name is None

    def test_settings_property(self):
        """Test settings property returns the settings."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        assert service.settings == settings
        assert service.settings.bucket == "test-bucket"


class TestStorageServiceLifecycle:
    """Test StorageService startup and shutdown."""

    @pytest.mark.asyncio
    async def test_startup_skipped_when_not_configured(self):
        """Test that startup is skipped when storage is not configured."""
        settings = StorageSettings(enabled=False)
        service = StorageService(settings)

        await service.startup()

        assert service._backend is None
        assert service._initialized is False

    @pytest.mark.asyncio
    async def test_startup_creates_backend(self):
        """Test that startup creates the backend via factory."""
        settings = StorageSettings(
            enabled=True,
            bucket="test-bucket",
            access_key="test-key",
            secret_key="test-secret",
        )
        service = StorageService(settings)

        mock_backend = AsyncMock()
        mock_backend.backend_name = "s3"
        mock_backend.is_ready = True

        with patch(
            "example_service.infra.storage.service.create_storage_backend",
            return_value=mock_backend,
        ):
            await service.startup()

        assert service._backend == mock_backend
        assert service._initialized is True
        assert service.is_ready is True
        mock_backend.startup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_when_not_initialized(self):
        """Test that shutdown handles not being initialized."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        # Should not raise
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_calls_backend_shutdown(self):
        """Test that shutdown properly calls backend shutdown."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        mock_backend = AsyncMock()
        service._backend = mock_backend
        service._initialized = True

        await service.shutdown()

        mock_backend.shutdown.assert_awaited_once()
        assert service._initialized is False

    @pytest.mark.asyncio
    async def test_health_check_when_not_ready(self):
        """Test health check returns False when not ready."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        result = await service.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_delegates_to_backend(self):
        """Test health check delegates to backend."""
        settings = StorageSettings(enabled=True, bucket="test-bucket")
        service = StorageService(settings)

        mock_backend = AsyncMock()
        mock_backend.is_ready = True
        mock_backend.health_check.return_value = True
        service._backend = mock_backend
        service._initialized = True

        result = await service.health_check()

        assert result is True
        mock_backend.health_check.assert_awaited_once()
