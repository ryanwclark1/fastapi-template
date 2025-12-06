"""FastAPI dependency injection for storage service.

Provides typed dependencies for injecting the storage service into
FastAPI route handlers with proper error handling and lifecycle management.

This module defines three main dependency injection patterns:

1. **get_storage_service**: Base dependency that retrieves the singleton
2. **require_storage**: Dependency that enforces storage availability (HTTP 503 if unavailable)
3. **optional_storage**: Dependency that gracefully handles storage being unavailable

Type Annotations
----------------
Storage : Type alias for required storage dependency
    Use when storage must be available for the endpoint to function.
    Automatically raises HTTP 503 if storage is not ready.

OptionalStorage : Type alias for optional storage dependency
    Use when storage is optional for the endpoint.
    Returns None if storage is not configured or not ready.

Example Usage
-------------
Required storage::

    from example_service.infra.storage.dependencies import Storage

    @router.post("/upload")
    async def upload_file(
        file: UploadFile,
        storage: Storage,
    ) -> dict:
        result = await storage.upload_file(
            file_obj=file.file,
            key=generate_upload_path(None, file.filename),
            content_type=file.content_type,
        )
        return result

Optional storage::

    from example_service.infra.storage.dependencies import OptionalStorage

    @router.get("/file/{file_id}")
    async def get_file(
        file_id: str,
        storage: OptionalStorage,
    ) -> dict:
        if storage is None:
            # Fallback to database-only retrieval
            return {"source": "database", "url": None}

        # Use storage when available
        return await storage.get_file_metadata(file_id)

Notes:
-----
- The storage service is lazily initialized on first access
- Dependencies are async to allow for future async initialization patterns
- Uses TYPE_CHECKING to avoid circular import issues
- All dependencies are reusable and composable
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

# Import at runtime to avoid circular dependencies
# StorageService is needed at runtime for the type aliases
from .service import StorageService


def get_storage_service() -> StorageService:
    """Get the singleton storage service instance.

    This is a thin wrapper that imports and returns the global
    storage service singleton. The import is deferred to runtime
    to avoid circular dependencies.

    The storage service is initialized lazily on first access,
    so this function will always return a valid instance, though
    the instance may not be ready if storage is not configured.

    Returns:
        StorageService: The global StorageService instance

    Notes:
        - This function is synchronous for FastAPI dependency compatibility
        - The returned service may not be ready; check is_ready property
        - Safe to call multiple times; always returns the same singleton
    """
    from .service import get_storage_service as _get_storage_service

    return _get_storage_service()


async def require_storage(
    storage: Annotated[StorageService, Depends(get_storage_service)],
) -> StorageService:
    """Dependency that requires storage to be available.

    Use this dependency when storage is required for the endpoint to function.
    Automatically raises an HTTP 503 error if storage is not configured or
    not ready, providing a clear error message to the client.

    This enforces that storage must be properly configured and available,
    making it suitable for endpoints that cannot function without storage
    (e.g., file upload, download, deletion endpoints).

    Args:
        storage: Injected storage service from get_storage_service

    Returns:
        StorageService: The ready storage service instance

    Raises:
        HTTPException: 503 Service Unavailable if storage is not ready,
            with details about the error in the response body

    Example:
        >>> @router.post("/files/upload")
        >>> async def upload(
        ...     file: UploadFile,
        ...     storage: Annotated[StorageService, Depends(require_storage)],
        ... ) -> dict:
        ...     return await storage.upload_file(...)
    """
    if not storage.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "storage_unavailable",
                "message": "Storage service is not available",
            },
        )
    return storage


async def optional_storage(
    storage: Annotated[StorageService, Depends(get_storage_service)],
) -> StorageService | None:
    """Dependency that optionally provides storage.

    Use this dependency when storage is optional for the endpoint to function.
    Returns None if storage is not configured or not ready, allowing the
    endpoint to implement fallback behavior.

    This is useful for endpoints that can gracefully degrade or have
    alternative data sources when storage is unavailable (e.g., serving
    cached data, database-only operations, or providing limited functionality).

    Args:
        storage: Injected storage service from get_storage_service

    Returns:
        StorageService | None: The storage service if ready, None otherwise

    Example:
        >>> @router.get("/files/{file_id}")
        >>> async def get_file(
        ...     file_id: str,
        ...     storage: Annotated[StorageService | None, Depends(optional_storage)],
        ... ) -> dict:
        ...     if storage is None:
        ...         return {"source": "database_only", "url": None}
        ...     return await storage.get_file_metadata(file_id)
    """
    if not storage.is_ready:
        return None
    return storage


# Type aliases for cleaner route signatures
Storage = Annotated[StorageService, Depends(require_storage)]
"""Storage dependency that requires storage to be available.

This is a type alias for the require_storage dependency, providing
a cleaner and more expressive syntax for route signatures.

The dependency will automatically raise HTTP 503 if storage is not
configured or not ready, ensuring that the route handler only executes
when storage is available.

Type:
    Annotated[StorageService, Depends(require_storage)]

Example:
    >>> from example_service.infra.storage.dependencies import Storage
    >>>
    >>> @router.post("/upload")
    >>> async def upload(
    ...     file: UploadFile,
    ...     storage: Storage,
    ... ) -> dict:
    ...     return await storage.upload_file(
    ...         file_obj=file.file,
    ...         key=f"uploads/{file.filename}",
    ...         content_type=file.content_type,
    ...     )

Notes:
    - Automatically validates storage availability
    - Raises HTTP 503 with descriptive error if unavailable
    - Type checkers will correctly infer StorageService type
"""

OptionalStorage = Annotated[StorageService | None, Depends(optional_storage)]
"""Storage dependency that is optional.

This is a type alias for the optional_storage dependency, providing
a cleaner and more expressive syntax for route signatures.

The dependency returns None if storage is not configured or not ready,
allowing the route handler to implement fallback logic or graceful
degradation.

Type:
    Annotated[StorageService | None, Depends(optional_storage)]

Example:
    >>> from example_service.infra.storage.dependencies import OptionalStorage
    >>>
    >>> @router.get("/file/{file_id}")
    >>> async def get_file(
    ...     file_id: str,
    ...     storage: OptionalStorage,
    ... ) -> dict:
    ...     if storage is None:
    ...         # Fallback to database-only retrieval
    ...         return {
    ...             "id": file_id,
    ...             "source": "database",
    ...             "url": None,
    ...         }
    ...
    ...     # Use storage when available
    ...     return await storage.get_file_metadata(file_id)

Notes:
    - Returns None when storage is unavailable
    - Allows graceful degradation of functionality
    - Type checkers will correctly infer StorageService | None type
"""
