"""S3-compatible storage backend.

Supports AWS S3, MinIO, LocalStack, and other S3-compatible services.
"""

from .backend import S3Backend

__all__ = ["S3Backend"]
