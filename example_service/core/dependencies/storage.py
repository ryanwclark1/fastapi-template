"""Storage service dependencies for FastAPI route handlers.

This module re-exports storage dependencies from the infrastructure layer
for centralized access through the core dependencies registry.

Usage:
    from example_service.core.dependencies.storage import (
        Storage,
        OptionalStorage,
        get_storage_service,
    )

    @router.post("/upload")
    async def upload_file(
        file: UploadFile,
        storage: Storage,
    ):
        result = await storage.upload_file(
            file_obj=file.file,
            key=f"uploads/{file.filename}",
            content_type=file.content_type,
        )
        return result

    @router.get("/file/{file_id}")
    async def get_file(
        file_id: str,
        storage: OptionalStorage,
    ):
        if storage is None:
            return {"source": "database", "url": None}
        return await storage.get_file_metadata(file_id)
"""

from __future__ import annotations

# Re-export everything from infra storage dependencies
from example_service.infra.storage.dependencies import (
    OptionalStorage,
    Storage,
    get_storage_service,
    optional_storage,
    require_storage,
)

# Also export the service class for type hints
from example_service.infra.storage.service import StorageService

__all__ = [
    "OptionalStorage",
    "Storage",
    "StorageService",
    "get_storage_service",
    "optional_storage",
    "require_storage",
]
