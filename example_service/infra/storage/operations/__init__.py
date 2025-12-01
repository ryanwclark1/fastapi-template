"""Storage operation modules.

Provides specialized operations for streaming, batch processing,
and presigned URL generation.
"""

from .batch import (
    BatchResult,
    BatchUploadItem,
    batch_delete,
    batch_download,
    batch_upload,
)
from .download import download_range, download_stream, download_to_file
from .presigned import (
    PresignedDownloadUrl,
    PresignedUploadUrl,
    generate_bulk_download_urls,
    generate_download_url,
    generate_upload_url,
)
from .upload import upload_bytes, upload_file_chunked, upload_stream

__all__ = [
    # Upload operations
    "upload_stream",
    "upload_file_chunked",
    "upload_bytes",
    # Download operations
    "download_stream",
    "download_to_file",
    "download_range",
    # Batch operations
    "BatchResult",
    "BatchUploadItem",
    "batch_upload",
    "batch_download",
    "batch_delete",
    # Presigned URL operations
    "PresignedDownloadUrl",
    "PresignedUploadUrl",
    "generate_download_url",
    "generate_upload_url",
    "generate_bulk_download_urls",
]
