"""Object storage infrastructure.

This module provides S3-compatible storage for backups and file uploads.
"""

from __future__ import annotations

from .client import (
    FileNotFoundError,
    InvalidFileError,
    StorageClient,
    StorageClientError,
    get_storage_client,
)
from .path import (
    generate_temp_path,
    generate_thumbnail_path,
    generate_unique_key,
    generate_upload_path,
    get_file_extension,
    is_image_content_type,
    parse_upload_path,
    sanitize_filename,
    sanitize_path_component,
    validate_path,
)
from .s3 import S3Client, get_s3_client

__all__ = [
    # Client
    "S3Client",
    "get_s3_client",
    "StorageClient",
    "StorageClientError",
    "FileNotFoundError",
    "InvalidFileError",
    "get_storage_client",
    # Path utilities
    "sanitize_filename",
    "sanitize_path_component",
    "validate_path",
    "generate_upload_path",
    "generate_thumbnail_path",
    "generate_temp_path",
    "parse_upload_path",
    "get_file_extension",
    "is_image_content_type",
    "generate_unique_key",
]
