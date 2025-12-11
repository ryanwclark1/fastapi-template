"""Unit tests for storage backend factory."""

import pytest

from example_service.core.settings.storage import StorageBackendType, StorageSettings
from example_service.infra.storage.backends import create_storage_backend
from example_service.infra.storage.backends.s3.backend import S3Backend
from example_service.infra.storage.exceptions import StorageNotConfiguredError

try:
    import aioboto3

    AIOBOTO3_AVAILABLE = True
except ImportError:
    AIOBOTO3_AVAILABLE = False


class TestBackendFactory:
    """Test backend factory creation logic."""

    @pytest.mark.skipif(
        not AIOBOTO3_AVAILABLE, reason="aioboto3 not installed",
    )
    def test_create_s3_backend(self):
        """Test creating S3 backend."""
        settings = StorageSettings(
            enabled=True,
            backend=StorageBackendType.S3,
            bucket="test-bucket",
            access_key="test-key",
            secret_key="test-secret",
        )

        backend = create_storage_backend(settings)

        assert isinstance(backend, S3Backend)
        assert backend.backend_name == "s3"

    @pytest.mark.skipif(
        not AIOBOTO3_AVAILABLE, reason="aioboto3 not installed",
    )
    def test_create_minio_backend(self):
        """Test creating MinIO backend (same as S3)."""
        settings = StorageSettings(
            enabled=True,
            backend=StorageBackendType.MINIO,
            bucket="test-bucket",
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
        )

        backend = create_storage_backend(settings)

        # MinIO uses the same S3Backend
        assert isinstance(backend, S3Backend)
        assert backend.backend_name == "s3"

    def test_factory_rejects_unconfigured_storage(self):
        """Test that factory rejects unconfigured storage."""
        settings = StorageSettings(enabled=False)

        with pytest.raises(StorageNotConfiguredError) as exc_info:
            create_storage_backend(settings)

        assert "Storage not configured" in str(exc_info.value)


class TestStorageBackendType:
    """Test StorageBackendType enum."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert StorageBackendType.S3.value == "s3"
        assert StorageBackendType.MINIO.value == "minio"
        # Note: GCS and Azure backends were removed as they were unimplemented stubs

    def test_enum_is_string(self):
        """Test that enum values are strings."""
        assert isinstance(StorageBackendType.S3.value, str)

    def test_enum_comparison(self):
        """Test enum comparison."""
        assert StorageBackendType.S3 == StorageBackendType.S3
        assert StorageBackendType.S3 != StorageBackendType.MINIO
