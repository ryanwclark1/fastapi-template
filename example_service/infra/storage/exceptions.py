"""Storage-specific exceptions for S3/MinIO operations.

This module defines custom exceptions for storage operations, providing
structured error handling with HTTP status codes and metadata following
RFC 7807 Problem Details for HTTP APIs.

Example:
    ```python
    from example_service.infra.storage.exceptions import (
        StorageUploadError,
        map_boto_error,
    )

    try:
        await storage_client.upload_file(path, bucket, key)
    except ClientError as e:
        raise map_boto_error(e, operation="upload", key=key)
    except StorageUploadError as e:
        logger.error(f"Upload failed: {e.detail}", extra=e.extra)
    ```
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from example_service.core.exceptions import AppException

if TYPE_CHECKING:
    from botocore.exceptions import ClientError


class StorageError(AppException):
    """Base exception for all storage-related errors.

    This exception serves as the parent class for all storage-specific
    errors, allowing for broad exception catching when needed.

    Attributes:
        status_code: HTTP status code for the error.
        detail: Human-readable error message.
        code: Error code identifier for programmatic error handling.
        type: Error type identifier (used in RFC 7807 problem details).
        title: Short, human-readable summary of the problem type.
        instance: URI reference that identifies the specific occurrence of the problem.
        extra: Additional context-specific information about the error (metadata).

    Example:
        ```python
        raise StorageError(
            message="Failed to connect to storage backend",
            code="STORAGE_CONNECTION_ERROR",
            status_code=503,
            metadata={"backend": "s3", "endpoint": "s3.amazonaws.com"}
        )
        ```
    """

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 500,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize storage error.

        Args:
            message: Human-readable error message.
            code: Error code for programmatic handling.
            status_code: HTTP status code (default: 500).
            metadata: Additional error context.
        """
        self.code = code
        self.message = message
        super().__init__(
            status_code=status_code,
            detail=message,
            type=code.lower().replace("_", "-"),
            extra=metadata or {},
        )


class StorageNotConfiguredError(StorageError):
    """Exception raised when storage is not properly configured or enabled.

    This exception is raised when attempting to use storage operations
    but the storage backend is not configured, disabled, or missing
    required configuration parameters.

    Example:
        ```python
        raise StorageNotConfiguredError(
            "Storage backend is not configured",
            metadata={"required_settings": ["S3_ENDPOINT", "S3_BUCKET"]}
        )
        ```
    """

    def __init__(
        self,
        message: str = "Storage is not configured or enabled",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize storage not configured error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (missing settings, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_NOT_CONFIGURED",
            status_code=503,
            metadata=metadata,
        )


class StorageFileNotFoundError(StorageError):
    """Exception raised when a requested file does not exist in storage.

    This exception is raised when attempting to access, download, or
    manipulate a file that doesn't exist in the storage backend.

    Example:
        ```python
        raise StorageFileNotFoundError(
            f"File not found: {key}",
            metadata={"bucket": bucket, "key": key}
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize file not found error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (bucket, key, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_NOT_FOUND",
            status_code=404,
            metadata=metadata,
        )


class StorageUploadError(StorageError):
    """Exception raised when file upload operations fail.

    This exception covers various upload failure scenarios including
    network errors, permission issues, and storage backend failures.

    Example:
        ```python
        raise StorageUploadError(
            "Failed to upload file to S3",
            metadata={
                "bucket": bucket,
                "key": key,
                "file_size": file_size,
                "error": str(original_error)
            }
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize upload error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (file info, attempt count, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_UPLOAD_ERROR",
            status_code=500,
            metadata=metadata,
        )


class StorageDownloadError(StorageError):
    """Exception raised when file download operations fail.

    This exception is raised when downloading files from storage fails
    due to network issues, permission problems, or storage errors.

    Example:
        ```python
        raise StorageDownloadError(
            "Failed to download file from S3",
            metadata={
                "bucket": bucket,
                "key": key,
                "dest": str(dest_path),
                "bytes_downloaded": bytes_received
            }
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize download error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (file info, destination, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_DOWNLOAD_ERROR",
            status_code=500,
            metadata=metadata,
        )


class StoragePermissionError(StorageError):
    """Exception raised when storage operations fail due to access permissions.

    This exception is raised when the storage client lacks necessary
    permissions to perform requested operations (read, write, delete).

    Example:
        ```python
        raise StoragePermissionError(
            "Access denied to bucket",
            metadata={
                "bucket": bucket,
                "operation": "PutObject",
                "required_permissions": ["s3:PutObject"]
            }
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize permission error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (bucket, operation, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_PERMISSION_DENIED",
            status_code=403,
            metadata=metadata,
        )


class StorageQuotaExceededError(StorageError):
    """Exception raised when storage quota limits are exceeded.

    This exception is raised when attempting operations that would
    exceed storage quota limits (size, file count, etc.).

    Example:
        ```python
        raise StorageQuotaExceededError(
            "Storage quota exceeded",
            metadata={
                "quota_limit": "100GB",
                "current_usage": "99.8GB",
                "requested_size": "500MB"
            }
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize quota exceeded error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (quota limits, usage, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_QUOTA_EXCEEDED",
            status_code=507,
            metadata=metadata,
        )


class StorageValidationError(StorageError):
    """Exception raised when file or parameter validation fails.

    This exception is raised when file types, sizes, names, or other
    parameters fail validation checks before storage operations.

    Example:
        ```python
        raise StorageValidationError(
            "Invalid file type",
            metadata={
                "allowed_types": [".jpg", ".png"],
                "provided_type": ".exe",
                "filename": "malware.exe"
            }
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize validation error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (validation rules, values, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_VALIDATION_ERROR",
            status_code=400,
            metadata=metadata,
        )


class StorageTimeoutError(StorageError):
    """Exception raised when storage operations exceed time limits.

    This exception is raised when upload, download, or other storage
    operations take longer than the configured timeout period.

    Example:
        ```python
        raise StorageTimeoutError(
            "Upload operation timed out",
            metadata={
                "operation": "upload",
                "timeout_seconds": 30,
                "elapsed_seconds": 31,
                "key": key
            }
        )
        ```
    """

    def __init__(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize timeout error.

        Args:
            message: Human-readable error message.
            metadata: Additional error context (timeout, elapsed time, etc.).
        """
        super().__init__(
            message=message,
            code="STORAGE_TIMEOUT",
            status_code=504,
            metadata=metadata,
        )


def map_boto_error(
    error: ClientError,
    operation: str,
    key: str | None = None,
) -> StorageError:
    """Map boto3 ClientError to domain-specific StorageError.

    This function translates AWS S3/boto3 errors into application-specific
    storage exceptions with appropriate HTTP status codes and metadata.

    Args:
        error: The boto3 ClientError exception to map.
        operation: The storage operation being performed (e.g., "upload", "download").
        key: Optional S3 key/object name being operated on.

    Returns:
        StorageError: Appropriate domain-specific storage exception.

    Example:
        ```python
        try:
            s3_client.get_object(Bucket=bucket, Key=key)
        except ClientError as e:
            raise map_boto_error(e, operation="download", key=key)
        ```

    Error Code Mappings:
        - NoSuchKey, NoSuchBucket -> StorageFileNotFoundError (404)
        - AccessDenied, ExpiredToken, InvalidAccessKeyId -> StoragePermissionError (403)
        - RequestTimeout, RequestTimeTooSkewed -> StorageTimeoutError (504)
        - QuotaExceeded, TooManyBuckets -> StorageQuotaExceededError (507)
        - InvalidRequest, InvalidArgument, MalformedXML -> StorageValidationError (400)
        - Others -> StorageError (500)
    """
    error_code = error.response.get("Error", {}).get("Code", "Unknown")
    error_message = error.response.get("Error", {}).get("Message", str(error))

    # Build base metadata
    metadata: dict[str, Any] = {
        "operation": operation,
        "aws_error_code": error_code,
        "aws_error_message": error_message,
        "request_id": error.response.get("RequestId"),
    }

    if key:
        metadata["key"] = key

    # Extract bucket from error response if available
    if "BucketName" in error.response.get("Error", {}):
        metadata["bucket"] = error.response["Error"]["BucketName"]  # type: ignore[typeddict-item]

    # Map AWS error codes to domain exceptions
    # Not Found Errors (404)
    if error_code in {"NoSuchKey", "NoSuchBucket"}:
        return StorageFileNotFoundError(
            message=f"{operation.capitalize()} failed: {error_message}",
            metadata=metadata,
        )

    # Permission/Authentication Errors (403)
    if error_code in {
        "AccessDenied",
        "ExpiredToken",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "InvalidToken",
        "TokenRefreshRequired",
    }:
        return StoragePermissionError(
            message=f"{operation.capitalize()} failed: {error_message}",
            metadata=metadata,
        )

    # Timeout Errors (504)
    if error_code in {
        "RequestTimeout",
        "RequestTimeTooSkewed",
        "SlowDown",
    }:
        return StorageTimeoutError(
            message=f"{operation.capitalize()} timed out: {error_message}",
            metadata=metadata,
        )

    # Quota/Limit Errors (507)
    if error_code in {
        "QuotaExceeded",
        "TooManyBuckets",
        "AccountProblem",
    }:
        return StorageQuotaExceededError(
            message=f"{operation.capitalize()} failed: {error_message}",
            metadata=metadata,
        )

    # Validation Errors (400)
    if error_code in {
        "InvalidRequest",
        "InvalidArgument",
        "MalformedXML",
        "InvalidBucketName",
        "InvalidObjectState",
        "KeyTooLongError",
        "MetadataTooLarge",
    }:
        return StorageValidationError(
            message=f"{operation.capitalize()} failed: {error_message}",
            metadata=metadata,
        )

    # Default to generic StorageError (500)
    return StorageError(
        message=f"{operation.capitalize()} failed: {error_message}",
        code="STORAGE_ERROR",
        status_code=500,
        metadata=metadata,
    )
