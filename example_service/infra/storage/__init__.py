"""Object storage infrastructure.

This module provides S3-compatible storage for backups and file uploads.
"""

from __future__ import annotations

from .s3 import S3Client, get_s3_client

__all__ = [
    "S3Client",
    "get_s3_client",
]
