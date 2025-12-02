"""Storage backends package.

Provides protocol-based abstraction for multiple storage backends.
"""

from example_service.core.settings.storage import StorageBackendType

from .factory import create_storage_backend
from .protocol import (
    BucketInfo,
    ObjectMetadata,
    StorageBackend,
    TenantContext,
    UploadResult,
)

__all__ = [
    "BucketInfo",
    "ObjectMetadata",
    "StorageBackend",
    "StorageBackendType",
    "TenantContext",
    "UploadResult",
    "create_storage_backend",
]
