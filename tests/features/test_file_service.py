"""Tests for the file service layer."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from hashlib import sha256
from io import BytesIO
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from example_service.core.settings.storage import StorageSettings
from example_service.features.files.models import File, FileStatus, FileThumbnail
from example_service.features.files.repository import FileRepository
from example_service.features.files.service import FileService
from example_service.infra.storage.client import InvalidFileError, StorageClientError

pytestmark = pytest.mark.asyncio


if os.getenv("RUN_POSTGRES_TESTS") != "1":  # pragma: no cover - default skip
    pytest.skip(
        "Set RUN_POSTGRES_TESTS=1 to run Postgres-backed file service tests",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def disable_webhook_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent webhook dispatcher from running during unit tests."""

    async def _noop(*args, **kwargs) -> int:
        return 0

    monkeypatch.setattr(
        "example_service.features.files.service.dispatch_event",
        _noop,
    )


class FakeStorageClient:
    """Minimal fake storage client for exercising FileService."""

    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.uploads: dict[str, dict] = {}
        self.deleted_keys: list[str] = []
        self.presigned_requests: list[str] = []

    async def upload_file(
        self,
        file_obj,
        key: str,
        content_type: str | None = None,
        metadata: dict | None = None,
        bucket: str | None = None,
    ) -> dict:
        payload = file_obj.read()
        checksum = sha256(payload).hexdigest()
        etag = f"etag-{len(self.uploads) + 1}"
        bucket_name = bucket or self.settings.bucket
        self.uploads[key] = {
            "payload": payload,
            "content_type": content_type,
            "metadata": metadata or {},
            "bucket": bucket_name,
            "etag": etag,
        }
        return {
            "bucket": bucket_name,
            "size_bytes": len(payload),
            "checksum_sha256": checksum,
            "etag": etag,
        }

    async def generate_presigned_upload(self, key: str, content_type: str) -> dict:
        self.presigned_requests.append(key)
        return {
            "url": f"https://upload.test/{key}",
            "fields": {"key": key, "content-type": content_type},
        }

    async def get_file_info(self, key: str) -> dict | None:
        stored = self.uploads.get(key)
        if stored is None:
            return None
        return {
            "key": key,
            "size_bytes": len(stored["payload"]),
            "content_type": stored["content_type"],
            "etag": stored["etag"],
            "metadata": stored["metadata"],
        }

    async def get_presigned_url(self, key: str) -> str:
        return f"https://download.test/{key}"

    async def delete_file(self, key: str) -> None:
        self.deleted_keys.append(key)
        self.uploads.pop(key, None)


@pytest.fixture
def storage_settings() -> StorageSettings:
    """Create deterministic storage settings for tests."""
    return StorageSettings(
        enabled=True,
        bucket="test-bucket",
        upload_prefix="uploads",
        allowed_content_types=["image/png", "application/pdf"],
        max_file_size_mb=2,
        presigned_url_expiry_seconds=900,
    )


@pytest.fixture
def fake_storage_client(storage_settings: StorageSettings) -> FakeStorageClient:
    """Provide a fake storage client backed by in-memory state."""
    return FakeStorageClient(storage_settings)


@pytest.fixture(scope="session")
def postgres_dsn():
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres container unavailable: {exc}", allow_module_level=True)
    # Convert to async connection URL for psycopg3
    # get_connection_url() may return postgresql:// or postgresql+psycopg2://
    original_url = container.get_connection_url()
    # Replace any psycopg2 reference with psycopg (psycopg3)
    url = original_url.replace("postgresql+psycopg2://", "postgresql+psycopg://").replace(
        "postgresql://", "postgresql+psycopg://"
    )
    yield url
    container.stop()


@pytest.fixture
async def session(postgres_dsn) -> AsyncGenerator[AsyncSession]:
    """Provide an isolated PostgreSQL-backed session with file tables."""
    import sqlalchemy as sa

    engine = create_async_engine(postgres_dsn)
    async with engine.begin() as conn:
        # Create filestatus enum before creating File table
        result = await conn.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'filestatus'
                )
                """
            )
        )
        exists = result.scalar()

        if not exists:
            # Create the filestatus enum type
            sa_enum = sa.Enum(
                "pending", "processing", "ready", "failed", "deleted", name="filestatus"
            )
            await conn.run_sync(lambda sync_conn, e=sa_enum: e.create(sync_conn, checkfirst=False))

        # Now create the file tables
        await conn.run_sync(
            lambda sync_conn: File.metadata.create_all(
                sync_conn,
                tables=[File.__table__, FileThumbnail.__table__],
            )
        )

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    await engine.dispose()


@pytest.fixture
def file_repository() -> FileRepository:
    """Repository bound to the File model."""
    return FileRepository()


@pytest.fixture
def file_service(
    session: AsyncSession,
    fake_storage_client: FakeStorageClient,
    file_repository: FileRepository,
) -> FileService:
    """Instantiate the service with fake dependencies."""
    return FileService(
        session=session,
        storage_client=fake_storage_client,
        repository=file_repository,
    )


async def create_file(
    session: AsyncSession,
    *,
    storage_key: str | None = None,
    status: FileStatus = FileStatus.PENDING,
    owner_id: str | None = "user-1",
    is_public: bool = False,
) -> File:
    """Persist a file record for tests."""
    file = File(
        original_filename="avatar.png",
        storage_key=storage_key or f"uploads/{uuid4()}.png",
        bucket="test-bucket",
        content_type="image/png",
        size_bytes=128,
        checksum_sha256="seed",
        status=status,
        owner_id=owner_id,
        is_public=is_public,
    )
    session.add(file)
    await session.flush()
    await session.refresh(file)
    return file


async def attach_thumbnail(
    session: AsyncSession,
    file: File,
    storage_key: str,
) -> FileThumbnail:
    """Persist a thumbnail row linked to the provided file."""
    thumbnail = FileThumbnail(
        file_id=file.id,
        storage_key=storage_key,
        width=100,
        height=100,
        size_bytes=42,
    )
    session.add(thumbnail)
    await session.flush()
    await session.refresh(file)
    return thumbnail


async def test_create_presigned_upload_persists_pending_record(
    session: AsyncSession,
    file_service: FileService,
    file_repository: FileRepository,
    fake_storage_client: FakeStorageClient,
) -> None:
    response = await file_service.create_presigned_upload(
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=512,
        owner_id="owner-123",
        is_public=True,
    )

    stored = await file_repository.get(session, response["file_id"])
    assert stored is not None
    assert stored.status == FileStatus.PENDING
    assert stored.owner_id == "owner-123"
    assert stored.is_public is True
    assert stored.storage_key == response["storage_key"]
    assert response["expires_in"] == fake_storage_client.settings.presigned_url_expiry_seconds
    assert response["upload_fields"]["key"] == response["storage_key"]
    assert "owner-123" in response["storage_key"]


async def test_create_presigned_upload_rejects_invalid_files(
    file_service: FileService,
) -> None:
    with pytest.raises(InvalidFileError):
        await file_service.create_presigned_upload(
            filename="malware.exe",
            content_type="application/octet-stream",
            size_bytes=256,
        )

    with pytest.raises(InvalidFileError):
        await file_service.create_presigned_upload(
            filename="empty.bin",
            content_type="application/pdf",
            size_bytes=0,
        )


async def test_upload_file_queues_thumbnail_task(
    file_service: FileService,
) -> None:
    dispatcher = AsyncMock(return_value=True)
    file_service._dispatch_thumbnail_task = dispatcher  # type: ignore[assignment]

    file = await file_service.upload_file(
        file_obj=BytesIO(b"image-bytes"),
        filename="avatar.png",
        content_type="image/png",
    )

    dispatcher.assert_awaited_once()
    dispatched_id, dispatched_type = dispatcher.call_args.args
    assert str(dispatched_id) == str(file.id)
    assert dispatched_type == "image/png"


async def test_complete_upload_marks_file_ready_when_storage_has_object(
    session: AsyncSession,
    file_service: FileService,
    fake_storage_client: FakeStorageClient,
) -> None:
    dispatcher = AsyncMock(return_value=True)
    file_service._dispatch_thumbnail_task = dispatcher  # type: ignore[assignment]

    file = await create_file(session, status=FileStatus.PENDING)
    await fake_storage_client.upload_file(
        BytesIO(b"payload"),
        key=file.storage_key,
        content_type=file.content_type,
        metadata={"original_filename": file.original_filename},
    )

    updated = await file_service.complete_upload(file.id, etag="manual-etag")

    assert updated.status == FileStatus.READY
    assert updated.etag == "manual-etag"
    dispatcher.assert_awaited_once_with(file.id, file.content_type)


async def test_complete_upload_marks_failed_when_storage_missing(
    session: AsyncSession,
    file_service: FileService,
    file_repository: FileRepository,
) -> None:
    file = await create_file(session, status=FileStatus.PENDING)

    with pytest.raises(StorageClientError):
        await file_service.complete_upload(file.id)

    refreshed = await file_repository.get(session, file.id)
    assert refreshed is not None
    assert refreshed.status == FileStatus.FAILED


async def test_delete_file_hard_deletes_records_and_objects(
    session: AsyncSession,
    file_service: FileService,
    file_repository: FileRepository,
    fake_storage_client: FakeStorageClient,
) -> None:
    file = await create_file(session, status=FileStatus.READY)
    thumbnail = await attach_thumbnail(session, file, storage_key="thumbnails/preview.png")

    await file_service.delete_file(file.id, hard_delete=True)

    assert await file_repository.get(session, file.id) is None
    assert file.storage_key in fake_storage_client.deleted_keys
    assert thumbnail.storage_key in fake_storage_client.deleted_keys


async def test_get_download_url_requires_ready_status(
    session: AsyncSession,
    file_service: FileService,
) -> None:
    file = await create_file(session, status=FileStatus.PENDING)

    with pytest.raises(ValueError, match=r"is not ready for download"):
        await file_service.get_download_url(file.id)


async def test_get_download_url_returns_presigned_payload(
    session: AsyncSession,
    file_service: FileService,
    fake_storage_client: FakeStorageClient,
) -> None:
    file = await create_file(session, status=FileStatus.READY)
    result = await file_service.get_download_url(file.id)

    assert result["filename"] == file.original_filename
    assert result["download_url"].endswith(file.storage_key)
    assert result["expires_in"] == fake_storage_client.settings.presigned_url_expiry_seconds
