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
    # Batch operations
    "BatchResult",
    "BatchUploadItem",
    # Presigned URL operations
    "PresignedDownloadUrl",
    "PresignedUploadUrl",
    "batch_delete",
    "batch_download",
    "batch_upload",
    "download_range",
    # Download operations
    "download_stream",
    "download_to_file",
    "generate_bulk_download_urls",
    "generate_download_url",
    "generate_upload_url",
    "upload_bytes",
    "upload_file_chunked",
    # Upload operations
    "upload_stream",
]
