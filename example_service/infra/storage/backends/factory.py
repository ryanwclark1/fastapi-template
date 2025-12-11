"""Backend factory for creating storage backends dynamically."""

from __future__ import annotations

from typing import TYPE_CHECKING

from example_service.core.settings.storage import StorageBackendType
from example_service.infra.storage.exceptions import StorageNotConfiguredError

if TYPE_CHECKING:
    from example_service.core.settings.storage import StorageSettings

    from .protocol import StorageBackend


def create_storage_backend(settings: StorageSettings) -> StorageBackend:
    """Factory function to create appropriate storage backend.

    Args:
        settings: Storage configuration settings

    Returns:
        Initialized storage backend implementing StorageBackend protocol

    Raises:
        StorageNotConfiguredError: If backend type unsupported or settings invalid

    Example:
        settings = get_storage_settings()
        backend = create_storage_backend(settings)
        await backend.startup()
        result = await backend.upload_object("file.txt", data)
        await backend.shutdown()
    """
    if not settings.is_configured:
        msg = (
            "Storage not configured. Set STORAGE_ENABLED=true and provide credentials."
        )
        raise StorageNotConfiguredError(msg)

    backend_type = settings.backend

    match backend_type:
        case StorageBackendType.S3 | StorageBackendType.MINIO:
            # Both S3 and MinIO use the same S3-compatible backend
            from .s3.backend import S3Backend

            return S3Backend(settings)

        case _:
            msg = (
                f"Unsupported storage backend: {backend_type}. "
                f"Supported backends: {', '.join([t.value for t in StorageBackendType])}"
            )
            raise StorageNotConfiguredError(
                msg,
            )
