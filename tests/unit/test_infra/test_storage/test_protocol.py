"""Unit tests for storage backend protocol and data structures."""

from datetime import UTC, datetime

import pytest

from example_service.infra.storage.backends import (
    BucketInfo,
    ObjectMetadata,
    TenantContext,
    UploadResult,
)


class TestTenantContext:
    """Test TenantContext dataclass."""

    def test_create_tenant_context(self):
        """Test creating a valid tenant context."""
        context = TenantContext(
            tenant_uuid="test-uuid-123",
            tenant_slug="acme",
            metadata={"foo": "bar"},
        )

        assert context.tenant_uuid == "test-uuid-123"
        assert context.tenant_slug == "acme"
        assert context.metadata == {"foo": "bar"}

    def test_tenant_context_immutable(self):
        """Test that TenantContext is immutable (frozen)."""
        context = TenantContext(
            tenant_uuid="test-uuid-123",
            tenant_slug="acme",
        )

        with pytest.raises(AttributeError):
            context.tenant_uuid = "new-uuid"  # type: ignore[misc]

    def test_tenant_context_default_metadata(self):
        """Test that metadata defaults to empty dict."""
        context = TenantContext(
            tenant_uuid="test-uuid-123",
            tenant_slug="acme",
        )

        assert context.metadata == {}

    def test_tenant_context_equality(self):
        """Test equality comparison."""
        context1 = TenantContext(
            tenant_uuid="test-uuid-123",
            tenant_slug="acme",
        )
        context2 = TenantContext(
            tenant_uuid="test-uuid-123",
            tenant_slug="acme",
        )

        assert context1 == context2

    def test_tenant_context_hash(self):
        """Test that TenantContext is hashable."""
        context = TenantContext(
            tenant_uuid="test-uuid-123",
            tenant_slug="acme",
        )

        # Should be able to use as dict key or in set
        test_dict = {context: "value"}
        assert test_dict[context] == "value"


class TestObjectMetadata:
    """Test ObjectMetadata dataclass."""

    def test_create_object_metadata(self):
        """Test creating valid object metadata."""
        last_modified = datetime.now(UTC)
        metadata = ObjectMetadata(
            key="path/to/file.txt",
            size_bytes=1024,
            content_type="text/plain",
            last_modified=last_modified,
            etag="abc123",
            storage_class="STANDARD",
            custom_metadata={"user": "alice"},
            acl="private",
        )

        assert metadata.key == "path/to/file.txt"
        assert metadata.size_bytes == 1024
        assert metadata.content_type == "text/plain"
        assert metadata.last_modified == last_modified
        assert metadata.etag == "abc123"
        assert metadata.storage_class == "STANDARD"
        assert metadata.custom_metadata == {"user": "alice"}
        assert metadata.acl == "private"

    def test_object_metadata_immutable(self):
        """Test that ObjectMetadata is immutable."""
        metadata = ObjectMetadata(
            key="file.txt",
            size_bytes=1024,
            content_type="text/plain",
            last_modified=datetime.now(UTC),
            etag="abc123",
            storage_class="STANDARD",
            custom_metadata={},
        )

        with pytest.raises(AttributeError):
            metadata.size_bytes = 2048  # type: ignore[misc]

    def test_object_metadata_optional_fields(self):
        """Test that optional fields can be None."""
        metadata = ObjectMetadata(
            key="file.txt",
            size_bytes=1024,
            content_type=None,
            last_modified=datetime.now(UTC),
            etag=None,
            storage_class=None,
            custom_metadata={},
            acl=None,
        )

        assert metadata.content_type is None
        assert metadata.etag is None
        assert metadata.storage_class is None
        assert metadata.acl is None


class TestUploadResult:
    """Test UploadResult dataclass."""

    def test_create_upload_result(self):
        """Test creating valid upload result."""
        result = UploadResult(
            key="path/to/file.txt",
            bucket="my-bucket",
            etag="abc123",
            size_bytes=1024,
            checksum_sha256="def456",
            version_id="v1",
        )

        assert result.key == "path/to/file.txt"
        assert result.bucket == "my-bucket"
        assert result.etag == "abc123"
        assert result.size_bytes == 1024
        assert result.checksum_sha256 == "def456"
        assert result.version_id == "v1"

    def test_upload_result_immutable(self):
        """Test that UploadResult is immutable."""
        result = UploadResult(
            key="file.txt",
            bucket="my-bucket",
            etag="abc123",
            size_bytes=1024,
            checksum_sha256="def456",
        )

        with pytest.raises(AttributeError):
            result.size_bytes = 2048  # type: ignore[misc]

    def test_upload_result_optional_version(self):
        """Test that version_id is optional."""
        result = UploadResult(
            key="file.txt",
            bucket="my-bucket",
            etag="abc123",
            size_bytes=1024,
            checksum_sha256="def456",
        )

        assert result.version_id is None


class TestBucketInfo:
    """Test BucketInfo dataclass."""

    def test_create_bucket_info(self):
        """Test creating valid bucket info."""
        creation_date = datetime.now(UTC)
        info = BucketInfo(
            name="my-bucket",
            region="us-west-2",
            creation_date=creation_date,
            versioning_enabled=True,
        )

        assert info.name == "my-bucket"
        assert info.region == "us-west-2"
        assert info.creation_date == creation_date
        assert info.versioning_enabled is True

    def test_bucket_info_immutable(self):
        """Test that BucketInfo is immutable."""
        info = BucketInfo(
            name="my-bucket",
            region="us-west-2",
            creation_date=datetime.now(UTC),
        )

        with pytest.raises(AttributeError):
            info.name = "new-bucket"  # type: ignore[misc]

    def test_bucket_info_default_versioning(self):
        """Test that versioning_enabled defaults to False."""
        info = BucketInfo(
            name="my-bucket",
            region="us-west-2",
            creation_date=datetime.now(UTC),
        )

        assert info.versioning_enabled is False

    def test_bucket_info_optional_fields(self):
        """Test that region and creation_date can be None."""
        info = BucketInfo(
            name="my-bucket",
            region=None,
            creation_date=None,
        )

        assert info.region is None
        assert info.creation_date is None
