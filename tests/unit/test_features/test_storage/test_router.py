"""Unit tests for storage API router endpoints."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient

from example_service.core.dependencies.auth import get_current_user, require_role
from example_service.core.dependencies.tenant import get_tenant_context
from example_service.core.schemas.auth import AuthUser
from example_service.features.storage.dependencies import get_storage_service
from example_service.infra.storage.backends import TenantContext
from example_service.infra.storage.exceptions import StorageError, StorageFileNotFoundError


@pytest.fixture
def mock_storage_service():
    """Create a mock storage service."""
    service = AsyncMock()
    service.is_ready = True
    service._backend = AsyncMock()
    service._backend.backend_name = "s3"
    return service


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user."""
    return AuthUser(
        user_id="admin-123",
        email="admin@example.com",
        roles=["admin"],
        permissions=["*"],
        acl={},
        metadata={},
    )


@pytest.fixture
def mock_tenant_context():
    """Create a mock tenant context."""
    return TenantContext(
        tenant_uuid="tenant-123",
        tenant_slug="acme",
    )


@pytest.fixture
async def storage_client(
    mock_storage_service, mock_admin_user, mock_tenant_context
) -> AsyncGenerator[AsyncClient]:
    """Create HTTP client with storage router and mocked dependencies."""
    from example_service.features.storage.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Override dependencies
    async def override_get_current_user() -> AuthUser:
        return mock_admin_user

    async def override_require_admin(
        user: AuthUser = Depends(override_get_current_user),
    ) -> AuthUser:
        return user

    async def override_get_storage_service():
        return mock_storage_service

    async def override_get_tenant_context():
        return mock_tenant_context

    app.dependency_overrides[get_current_user] = override_get_current_user
    # Override require_role("admin") by creating a dependency override
    app.dependency_overrides[require_role("admin")] = override_require_admin
    app.dependency_overrides[get_storage_service] = override_get_storage_service
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    # Cleanup
    app.dependency_overrides.clear()


class TestBucketEndpoints:
    """Test bucket management endpoints."""

    @pytest.mark.asyncio
    async def test_create_bucket_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful bucket creation."""
        mock_storage_service.create_bucket.return_value = True

        response = await storage_client.post(
            "/api/v1/storage/buckets",
            json={
                "name": "test-bucket",
                "region": "us-west-2",
                "acl": "private",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "test-bucket"
        assert data["region"] == "us-west-2"
        mock_storage_service.create_bucket.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_bucket_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful bucket deletion."""
        mock_storage_service.delete_bucket.return_value = True

        response = await storage_client.delete("/api/v1/storage/buckets/test-bucket")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "deleted successfully" in data["message"]
        mock_storage_service.delete_bucket.assert_awaited_once_with(
            bucket="test-bucket", force=False
        )

    @pytest.mark.asyncio
    async def test_delete_bucket_with_force(
        self, storage_client: AsyncClient, mock_storage_service
    ):
        """Test bucket deletion with force flag."""
        mock_storage_service.delete_bucket.return_value = True

        response = await storage_client.delete("/api/v1/storage/buckets/test-bucket?force=true")

        assert response.status_code == status.HTTP_200_OK
        mock_storage_service.delete_bucket.assert_awaited_once_with(
            bucket="test-bucket", force=True
        )

    @pytest.mark.asyncio
    async def test_list_buckets_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful bucket listing."""
        mock_storage_service.list_buckets.return_value = [
            {
                "name": "bucket-1",
                "region": "us-west-2",
                "creation_date": datetime.now(UTC),
                "versioning_enabled": False,
            },
            {
                "name": "bucket-2",
                "region": "us-east-1",
                "creation_date": datetime.now(UTC),
                "versioning_enabled": True,
            },
        ]

        response = await storage_client.get("/api/v1/storage/buckets")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["buckets"]) == 2
        assert data["total"] == 2
        assert data["buckets"][0]["name"] == "bucket-1"
        assert data["buckets"][1]["versioning_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_bucket_info_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test getting bucket information."""
        mock_storage_service.bucket_exists.return_value = True
        mock_storage_service.list_buckets.return_value = [
            {
                "name": "test-bucket",
                "region": "us-west-2",
                "creation_date": datetime.now(UTC),
                "versioning_enabled": False,
            }
        ]

        response = await storage_client.get("/api/v1/storage/buckets/test-bucket")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "test-bucket"
        assert data["region"] == "us-west-2"

    @pytest.mark.asyncio
    async def test_get_bucket_info_not_found(
        self, storage_client: AsyncClient, mock_storage_service
    ):
        """Test getting info for non-existent bucket."""
        mock_storage_service.bucket_exists.return_value = False

        response = await storage_client.get("/api/v1/storage/buckets/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestObjectEndpoints:
    """Test object management endpoints."""

    @pytest.mark.asyncio
    async def test_list_objects_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful object listing."""
        from example_service.infra.storage.backends import ObjectMetadata

        mock_storage_service._resolve_bucket.return_value = "test-bucket"
        mock_storage_service._backend.list_objects.return_value = (
            [
                ObjectMetadata(
                    key="file1.txt",
                    size_bytes=1024,
                    content_type="text/plain",
                    last_modified=datetime.now(UTC),
                    etag="abc123",
                    storage_class="STANDARD",
                    custom_metadata={},
                ),
                ObjectMetadata(
                    key="file2.pdf",
                    size_bytes=2048,
                    content_type="application/pdf",
                    last_modified=datetime.now(UTC),
                    etag="def456",
                    storage_class="STANDARD",
                    custom_metadata={},
                ),
            ],
            None,  # No continuation token
        )

        response = await storage_client.get("/api/v1/storage/objects?prefix=&max_keys=100")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["objects"]) == 2
        assert data["total"] == 2
        assert data["has_more"] is False
        assert data["objects"][0]["key"] == "file1.txt"
        assert data["objects"][1]["size_bytes"] == 2048

    @pytest.mark.asyncio
    async def test_list_objects_with_pagination(
        self, storage_client: AsyncClient, mock_storage_service
    ):
        """Test object listing with pagination."""
        from example_service.infra.storage.backends import ObjectMetadata

        mock_storage_service._resolve_bucket.return_value = "test-bucket"
        mock_storage_service._backend.list_objects.return_value = (
            [
                ObjectMetadata(
                    key="file1.txt",
                    size_bytes=1024,
                    content_type="text/plain",
                    last_modified=datetime.now(UTC),
                    etag="abc123",
                    storage_class="STANDARD",
                    custom_metadata={},
                )
            ],
            "next-token-123",  # Has more results
        )

        response = await storage_client.get("/api/v1/storage/objects?max_keys=1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["has_more"] is True
        assert data["continuation_token"] == "next-token-123"

    @pytest.mark.asyncio
    async def test_upload_object_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful object upload."""
        mock_storage_service.upload_file.return_value = {
            "key": "test.txt",
            "bucket": "test-bucket",
            "etag": "abc123",
            "size_bytes": 1024,
            "checksum_sha256": "def456",
            "version_id": None,
        }

        files = {"file": ("test.txt", BytesIO(b"test content"), "text/plain")}
        response = await storage_client.post("/api/v1/storage/objects/test.txt", files=files)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["key"] == "test.txt"
        assert data["size_bytes"] == 1024
        assert data["etag"] == "abc123"

    @pytest.mark.asyncio
    async def test_upload_object_with_acl(self, storage_client: AsyncClient, mock_storage_service):
        """Test object upload with ACL."""
        mock_storage_service.upload_file.return_value = {
            "key": "test.txt",
            "bucket": "test-bucket",
            "etag": "abc123",
            "size_bytes": 1024,
            "checksum_sha256": "def456",
            "version_id": None,
        }

        files = {"file": ("test.txt", BytesIO(b"test content"), "text/plain")}
        response = await storage_client.post(
            "/api/v1/storage/objects/test.txt?acl=public-read", files=files
        )

        assert response.status_code == status.HTTP_201_CREATED
        # Verify ACL was passed to upload_file
        call_args = mock_storage_service.upload_file.call_args
        assert call_args.kwargs["acl"] == "public-read"

    @pytest.mark.asyncio
    async def test_download_object_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful object download."""
        mock_storage_service.download_file.return_value = b"test content"
        mock_storage_service.get_file_info.return_value = {
            "content_type": "text/plain",
            "size_bytes": 12,
        }

        response = await storage_client.get("/api/v1/storage/objects/test.txt")

        assert response.status_code == status.HTTP_200_OK
        assert response.content == b"test content"
        # FastAPI may add charset to content-type
        assert response.headers["content-type"].startswith("text/plain")

    @pytest.mark.asyncio
    async def test_download_object_not_found(
        self, storage_client: AsyncClient, mock_storage_service
    ):
        """Test downloading non-existent object."""
        mock_storage_service.download_file.side_effect = StorageFileNotFoundError(
            "Object not found"
        )

        response = await storage_client.get("/api/v1/storage/objects/nonexistent.txt")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_object_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful object deletion."""
        mock_storage_service.delete_file.return_value = True

        response = await storage_client.delete("/api/v1/storage/objects/test.txt")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["deleted"] is True
        assert data["key"] == "test.txt"


class TestACLEndpoints:
    """Test ACL management endpoints."""

    @pytest.mark.asyncio
    async def test_set_object_acl_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful ACL setting."""
        mock_storage_service.set_object_acl.return_value = True

        response = await storage_client.put(
            "/api/v1/storage/objects/test.txt/acl",
            json={"acl": "public-read"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "public-read" in data["message"]
        mock_storage_service.set_object_acl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_object_acl_success(self, storage_client: AsyncClient, mock_storage_service):
        """Test successful ACL retrieval."""
        # get_object_acl is async, so we need to use AsyncMock or return_value properly
        from unittest.mock import AsyncMock

        mock_storage_service.get_object_acl = AsyncMock(
            return_value={
                "owner": {"ID": "owner-id", "DisplayName": "owner"},
                "grants": [
                    {
                        "Grantee": {"Type": "CanonicalUser", "ID": "user-id"},
                        "Permission": "FULL_CONTROL",
                    }
                ],
            }
        )

        response = await storage_client.get("/api/v1/storage/objects/test.txt/acl")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "owner" in data
        assert "grants" in data
        assert len(data["grants"]) == 1
        mock_storage_service.get_object_acl.assert_awaited_once()


class TestSchemaValidation:
    """Test request/response schema validation."""

    @pytest.mark.asyncio
    async def test_bucket_create_validation(
        self, storage_client: AsyncClient, mock_storage_service
    ):
        """Test bucket creation schema validation."""
        # Too short bucket name
        response = await storage_client.post(
            "/api/v1/storage/buckets",
            json={"name": "ab"},  # Min length is 3
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_object_list_query_validation(
        self, storage_client: AsyncClient, mock_storage_service
    ):
        """Test object list query parameter validation."""
        # max_keys too large
        response = await storage_client.get("/api/v1/storage/objects?max_keys=99999")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
