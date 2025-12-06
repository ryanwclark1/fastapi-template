"""Path generation and parsing utilities for S3 storage operations.

This module provides utilities for generating consistent, organized paths
for storing files in S3, including uploads, thumbnails, temporary files,
and path parsing utilities with comprehensive validation.

Key features:
- Filename sanitization to prevent security issues
- Path component validation to prevent directory traversal
- Organized hierarchical path structures by date
- UUID-based unique identifiers for collision prevention
- Content type detection and validation

Example:
    ```python
    from uuid import uuid4

    # Generate upload path with owner isolation
    path = generate_upload_path(owner_id="user-123", filename="document.pdf")
    # Returns: uploads/2025/11/25/uuid_document.pdf

    # Generate thumbnail path for image processing
    thumb_path = generate_thumbnail_path(file_id="abc-123", size=256)
    # Returns: thumbnails/abc-123/256.jpg

    # Generate temporary upload path
    temp_path = generate_temp_path("upload.zip")
    # Returns: temp/uuid_upload.zip

    # Parse upload path to extract metadata
    info = parse_upload_path(path)
    # Returns: {"year": "2025", "month": "11", "day": "25", ...}
    ```
"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
from uuid import uuid4


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage.

    Removes or replaces characters that could cause issues in file systems
    or S3 keys while preserving the file extension. This prevents security
    issues like path traversal, command injection, and encoding problems.

    Operations performed:
    1. Replace spaces and special characters with underscores
    2. Remove consecutive underscores and dots
    3. Strip leading/trailing underscores and dots
    4. Fallback to "unnamed_file" if result is empty
    5. Preserve original file extension

    Args:
        filename: Original filename to sanitize.

    Returns:
        Sanitized filename safe for storage.

    Example:
        ```python
        # Special characters and spaces
        sanitize_filename("my file (1).pdf")
        # Returns: "my_file_1.pdf"

        # Multiple consecutive special chars
        sanitize_filename("test___file...pdf")
        # Returns: "test_file.pdf"

        # Leading/trailing problematic chars
        sanitize_filename("...test___.pdf")
        # Returns: "test.pdf"

        # Empty after sanitization
        sanitize_filename("...")
        # Returns: "unnamed_file"

        # Unicode and extended chars
        sanitize_filename("файл документ.txt")
        # Returns: "unnamed_file.txt"
        ```
    """
    # Split filename and extension
    parts = filename.rsplit(".", 1)
    name_part = parts[0]
    ext_part = f".{parts[1]}" if len(parts) == 2 and parts[1] else ""

    # Replace spaces and special characters with underscores in name part
    # Keep only word characters (alphanumeric + _) and dashes
    safe_name = re.sub(r"[^\w\-]", "_", name_part)

    # Remove consecutive underscores
    safe_name = re.sub(r"_+", "_", safe_name)

    # Remove leading/trailing underscores
    safe_name = safe_name.strip("_")

    # Sanitize extension if present (remove any remaining special chars)
    if ext_part:
        safe_ext = re.sub(r"[^\w]", "", ext_part[1:])  # Remove the dot, sanitize, will re-add
        ext_part = f".{safe_ext}" if safe_ext else ""

    # Combine
    safe = f"{safe_name}{ext_part}" if safe_name else ext_part.lstrip(".")

    # Ensure we have a filename
    if not safe:
        # Try to preserve extension if original had one
        ext = get_file_extension(filename)
        safe = f"unnamed_file{ext}" if ext else "unnamed_file"

    return safe


def sanitize_path_component(component: str) -> str:
    """Sanitize a path component (like owner ID or folder name).

    Ensures path components are safe for use in storage paths by removing
    or replacing potentially dangerous characters while maintaining
    readability for identifiers.

    Operations performed:
    1. Replace any character that's not alphanumeric, dash, or underscore
    2. Remove consecutive underscores
    3. Strip leading/trailing underscores

    Args:
        component: Path component to sanitize (e.g., user ID, tenant ID).

    Returns:
        Sanitized component safe for path construction.

    Example:
        ```python
        # User/tenant IDs
        sanitize_path_component("user-123")
        # Returns: "user-123"

        # Special characters
        sanitize_path_component("tenant@company.com")
        # Returns: "tenant_company_com"

        # Multiple separators
        sanitize_path_component("org___dept")
        # Returns: "org_dept"

        # Leading/trailing underscores
        sanitize_path_component("_test_")
        # Returns: "test"
        ```
    """
    # Replace any character that's not alphanumeric, dash, or underscore
    safe = re.sub(r"[^\w\-]", "_", component)

    # Remove consecutive underscores
    safe = re.sub(r"_+", "_", safe)

    # Remove leading/trailing underscores
    return safe.strip("_")


def validate_path(path: str) -> None:
    """Validate storage path format and security.

    Performs comprehensive validation to prevent security issues like
    directory traversal, null byte injection, and path manipulation.

    Validation checks:
    - Reject ".." (directory traversal attempts)
    - Reject paths starting with "/" (absolute paths)
    - Reject paths ending with "/" (directory references)
    - Reject null bytes and control characters
    - Enforce maximum length (1024 characters)

    Args:
        path: Path to validate.

    Raises:
        ValueError: If path fails any validation check with descriptive message.

    Example:
        ```python
        # Valid paths pass silently
        validate_path("uploads/2025/11/25/file.pdf")  # OK

        # Directory traversal attempt
        validate_path("uploads/../../../etc/passwd")
        # Raises: ValueError("Path contains directory traversal (..) pattern")

        # Absolute path
        validate_path("/etc/passwd")
        # Raises: ValueError("Path cannot start with /")

        # Null byte injection
        validate_path("file\\x00.pdf")
        # Raises: ValueError("Path contains null bytes or control characters")

        # Too long
        validate_path("a" * 2000)
        # Raises: ValueError("Path exceeds maximum length of 1024 characters")
        ```
    """
    # Check for directory traversal
    if ".." in path:
        msg = "Path contains directory traversal (..) pattern"
        raise ValueError(msg)

    # Check for absolute paths
    if path.startswith("/"):
        msg = "Path cannot start with /"
        raise ValueError(msg)

    # Check for trailing slashes (indicates directory, not file)
    if path.endswith("/"):
        msg = "Path cannot end with /"
        raise ValueError(msg)

    # Check for null bytes or control characters (ASCII < 32)
    if any(ord(c) < 32 for c in path):
        msg = "Path contains null bytes or control characters"
        raise ValueError(msg)

    # Check reasonable length (S3 key limit is 1024 bytes)
    if len(path) > 1024:
        msg = f"Path exceeds maximum length of 1024 characters (got {len(path)})"
        raise ValueError(msg)

    # Check for empty path
    if not path or not path.strip():
        msg = "Path cannot be empty"
        raise ValueError(msg)


def generate_upload_path(
    owner_id: str | None,
    filename: str,
    prefix: str = "uploads",
    timestamp: datetime | None = None,
) -> str:
    """Generate organized path for file uploads.

    Creates a hierarchical path structure organized by date with UUID-based
    unique identifiers to prevent filename collisions and enable efficient
    organization and retrieval.

    Path format: {prefix}/{YYYY}/{MM}/{DD}/{uuid}_{sanitized_filename}

    If owner_id is provided, the format becomes:
    {prefix}/{owner_id}/{YYYY}/{MM}/{DD}/{uuid}_{sanitized_filename}

    Args:
        owner_id: Optional owner identifier (user ID, tenant ID, etc.).
                 If provided, files are organized by owner.
        filename: Original filename (will be sanitized).
        prefix: Base prefix for uploads (default: "uploads").
        timestamp: Optional timestamp (defaults to current UTC time).

    Returns:
        Generated storage path string.

    Example:
        ```python
        from datetime import datetime, UTC

        # Simple upload without owner
        path = generate_upload_path(
            owner_id=None,
            filename="report.pdf"
        )
        # Returns: uploads/2025/11/25/550e8400-e29b-41d4-a716-446655440000_report.pdf

        # Upload with owner isolation
        path = generate_upload_path(
            owner_id="user-123",
            filename="document.pdf"
        )
        # Returns: uploads/user-123/2025/11/25/uuid_document.pdf

        # Custom prefix and timestamp
        path = generate_upload_path(
            owner_id="tenant-abc",
            filename="backup.zip",
            prefix="backups",
            timestamp=datetime(2025, 1, 15, tzinfo=UTC)
        )
        # Returns: backups/tenant-abc/2025/01/15/uuid_backup.zip
        ```
    """
    # Use current UTC time if not provided
    if timestamp is None:
        timestamp = datetime.now(UTC)

    # Sanitize filename
    safe_filename = sanitize_filename(filename)

    # Generate unique identifier
    unique_id = generate_unique_key()

    # Format date components
    year = timestamp.strftime("%Y")
    month = timestamp.strftime("%m")
    day = timestamp.strftime("%d")

    # Construct path parts
    path_parts = [sanitize_path_component(prefix)]

    # Add owner isolation if provided
    if owner_id:
        path_parts.append(sanitize_path_component(owner_id))

    # Add date hierarchy
    path_parts.extend([year, month, day])

    # Add unique filename
    path_parts.append(f"{unique_id}_{safe_filename}")

    # Join and validate
    path = "/".join(path_parts)
    validate_path(path)

    return path


def generate_thumbnail_path(file_id: str, size: int) -> str:
    """Generate path for image thumbnails.

    Creates a consistent path structure for storing thumbnails at different
    sizes, organized by the original file identifier.

    Path format: thumbnails/{file_id}/{size}.jpg

    Args:
        file_id: Original file identifier (UUID or unique key).
        size: Thumbnail size in pixels (width).

    Returns:
        Generated thumbnail storage path.

    Example:
        ```python
        # Standard thumbnail sizes
        thumb_128 = generate_thumbnail_path("abc-def-123", 128)
        # Returns: thumbnails/abc-def-123/128.jpg

        thumb_256 = generate_thumbnail_path("abc-def-123", 256)
        # Returns: thumbnails/abc-def-123/256.jpg

        thumb_512 = generate_thumbnail_path("abc-def-123", 512)
        # Returns: thumbnails/abc-def-123/512.jpg
        ```
    """
    # Sanitize file ID to prevent path traversal
    safe_file_id = sanitize_path_component(file_id)

    # Construct thumbnail path
    path = f"thumbnails/{safe_file_id}/{size}.jpg"

    # Validate before returning
    validate_path(path)

    return path


def generate_temp_path(filename: str) -> str:
    """Generate path for temporary files.

    Creates a path in temporary storage with UUID prefix for files
    that will be processed and moved to permanent storage or cleaned up.

    Path format: temp/{uuid}_{sanitized_filename}

    Args:
        filename: Original filename (will be sanitized).

    Returns:
        Generated temporary storage path string.

    Example:
        ```python
        # Temporary upload
        temp_path = generate_temp_path("upload.pdf")
        # Returns: temp/550e8400-e29b-41d4-a716-446655440000_upload.pdf

        # Processing file
        temp_path = generate_temp_path("processing.zip")
        # Returns: temp/uuid_processing.zip
        ```
    """
    # Sanitize filename
    safe_filename = sanitize_filename(filename)

    # Generate unique identifier
    unique_id = generate_unique_key()

    # Construct path
    path = f"temp/{unique_id}_{safe_filename}"

    # Validate before returning
    validate_path(path)

    return path


def parse_upload_path(path: str) -> dict[str, Any] | None:
    """Parse upload path to extract components.

    Extracts metadata from upload paths including date components,
    file ID, and original filename. Supports both owner-isolated and
    non-isolated path formats.

    Supported formats:
    - {prefix}/{YYYY}/{MM}/{DD}/{uuid}_{filename}
    - {prefix}/{owner_id}/{YYYY}/{MM}/{DD}/{uuid}_{filename}

    Args:
        path: Upload path to parse.

    Returns:
        Dictionary with extracted components if valid:
            - prefix: Base prefix (e.g., "uploads")
            - owner_id: Owner identifier (if present, else None)
            - year: Year component as string
            - month: Month component as string
            - day: Day component as string
            - file_id: UUID portion of filename
            - original_filename: Sanitized filename without UUID prefix
            - full_filename: Complete filename with UUID prefix
            - date: datetime object (date only, UTC timezone)
        Returns None if path format is invalid.

    Example:
        ```python
        # Parse simple upload path
        info = parse_upload_path(
            "uploads/2025/11/25/550e8400-e29b-41d4-a716-446655440000_document.pdf"
        )
        # Returns: {
        #     "prefix": "uploads",
        #     "owner_id": None,
        #     "year": "2025",
        #     "month": "11",
        #     "day": "25",
        #     "file_id": "550e8400-e29b-41d4-a716-446655440000",
        #     "original_filename": "document.pdf",
        #     "full_filename": "550e8400-e29b-41d4-a716-446655440000_document.pdf",
        #     "date": datetime(2025, 11, 25, tzinfo=UTC)
        # }

        # Parse owner-isolated path
        info = parse_upload_path(
            "uploads/user-123/2025/01/15/uuid_file.txt"
        )
        # Returns: {..., "owner_id": "user-123", ...}

        # Invalid path
        info = parse_upload_path("invalid/path")
        # Returns: None
        ```
    """
    # Try owner-isolated format first: prefix/owner_id/YYYY/MM/DD/uuid_filename
    owner_pattern = r"^([^/]+)/([^/]+)/(\d{4})/(\d{2})/(\d{2})/([^/]+)$"
    match = re.match(owner_pattern, path)

    if match:
        prefix, owner_id, year, month, day, full_filename = match.groups()

        # Extract UUID and filename from the combined filename
        parts = full_filename.split("_", 1)
        if len(parts) != 2:
            return None

        file_id, original_filename = parts

        # Validate date components
        try:
            date = datetime(int(year), int(month), int(day), tzinfo=UTC)
        except ValueError:
            return None

        return {
            "prefix": prefix,
            "owner_id": owner_id,
            "year": year,
            "month": month,
            "day": day,
            "file_id": file_id,
            "original_filename": original_filename,
            "full_filename": full_filename,
            "date": date,
        }

    # Try non-isolated format: prefix/YYYY/MM/DD/uuid_filename
    simple_pattern = r"^([^/]+)/(\d{4})/(\d{2})/(\d{2})/([^/]+)$"
    match = re.match(simple_pattern, path)

    if match:
        prefix, year, month, day, full_filename = match.groups()

        # Extract UUID and filename
        parts = full_filename.split("_", 1)
        if len(parts) != 2:
            return None

        file_id, original_filename = parts

        # Validate date components
        try:
            date = datetime(int(year), int(month), int(day), tzinfo=UTC)
        except ValueError:
            return None

        return {
            "prefix": prefix,
            "owner_id": None,
            "year": year,
            "month": month,
            "day": day,
            "file_id": file_id,
            "original_filename": original_filename,
            "full_filename": full_filename,
            "date": date,
        }

    # Invalid format
    return None


def get_file_extension(filename: str) -> str | None:
    """Extract file extension from filename.

    Returns the file extension including the leading dot, or None if
    the filename has no extension.

    Args:
        filename: Filename to extract extension from.

    Returns:
        File extension with leading dot (e.g., ".pdf", ".jpg") or None.

    Example:
        ```python
        # Standard extensions
        get_file_extension("document.pdf")
        # Returns: ".pdf"

        get_file_extension("image.jpg")
        # Returns: ".jpg"

        # Multiple dots
        get_file_extension("archive.tar.gz")
        # Returns: ".gz"

        # No extension
        get_file_extension("README")
        # Returns: None

        # Dotfile
        get_file_extension(".gitignore")
        # Returns: None

        # Hidden file with extension
        get_file_extension(".config.yaml")
        # Returns: ".yaml"
        ```
    """
    # Split on last dot
    parts = filename.rsplit(".", 1)

    # Must have 2 parts, second part must not be empty, and first part must exist
    # Don't treat dotfiles as having extension (e.g., ".gitignore")
    if len(parts) == 2 and parts[1] and parts[0]:
        return f".{parts[1]}"

    return None


def is_image_content_type(content_type: str) -> bool:
    """Check if content type represents an image.

    Validates whether a MIME type is an image format that could be
    used for thumbnail generation or image processing.

    Supported image types:
    - image/jpeg
    - image/png
    - image/gif
    - image/webp
    - image/svg+xml
    - image/bmp
    - image/tiff

    Args:
        content_type: MIME type to check.

    Returns:
        True if content type is an image, False otherwise.

    Example:
        ```python
        # Standard image types
        is_image_content_type("image/jpeg")  # Returns: True
        is_image_content_type("image/png")   # Returns: True
        is_image_content_type("image/webp")  # Returns: True

        # Non-image types
        is_image_content_type("application/pdf")  # Returns: False
        is_image_content_type("text/plain")       # Returns: False
        is_image_content_type("video/mp4")        # Returns: False

        # Case insensitive
        is_image_content_type("Image/JPEG")  # Returns: True
        ```
    """
    # Normalize to lowercase for comparison
    content_type_lower = content_type.lower().strip()

    # Check if it starts with "image/"
    if not content_type_lower.startswith("image/"):
        return False

    # List of supported image types
    supported_types = {
        "image/jpeg",
        "image/jpg",  # Some systems use jpg instead of jpeg
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "image/bmp",
        "image/tiff",
    }

    return content_type_lower in supported_types


def generate_unique_key() -> str:
    """Generate a unique key for file identification.

    Creates a UUID-based unique identifier suitable for use in
    filenames and path components. Uses UUID4 for randomness.

    Returns:
        String representation of UUID without hyphens for compact storage.

    Example:
        ```python
        # Generate unique keys
        key1 = generate_unique_key()
        # Returns: "550e8400e29b41d4a716446655440000"

        key2 = generate_unique_key()
        # Returns: "6ba7b8109dad11d180b400c04fd430c8"

        # Keys are always unique
        assert key1 != key2
        ```
    """
    # Generate UUID4 and convert to string without hyphens
    return uuid4().hex
