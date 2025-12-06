"""Input validation and sanitization utilities for GraphQL.

This module provides validation decorators, custom scalars, and sanitization
functions to prevent XSS attacks, SQL injection, and other input-based vulnerabilities.

Usage:
    from example_service.features.graphql.validators import SafeString, sanitize_html

    @strawberry.type
    class CommentType:
        # Automatically sanitized
        content: SafeString

    # Or manual sanitization:
    clean_content = sanitize_html(user_input)
"""

from __future__ import annotations

import re
from typing import NewType
from urllib.parse import urlparse

import bleach
from email_validator import EmailNotValidError
from email_validator import validate_email as validate_email_address
import strawberry

__all__ = [
    "Email",
    "SafeString",
    "SafeURL",
    "is_safe_filename",
    "sanitize_html",
    "sanitize_string",
    "validate_email",
    "validate_length",
    "validate_url",
]


# ============================================================================
# HTML/XSS Sanitization
# ============================================================================


def sanitize_html(
    text: str,
    allowed_tags: list[str] | None = None,
    allowed_attributes: dict | None = None,
    strip: bool = True,
) -> str:
    """Sanitize HTML input to prevent XSS attacks.

    Uses bleach library to remove dangerous HTML tags and attributes while
    preserving safe formatting.

    Args:
        text: Input text that may contain HTML
        allowed_tags: List of allowed HTML tags (default: basic formatting only)
        allowed_attributes: Dict of allowed attributes per tag
        strip: Whether to strip disallowed tags (vs escape them)

    Returns:
        Sanitized HTML string

    Example:
        >>> sanitize_html('<script>alert("xss")</script><p>Safe</p>')
        '<p>Safe</p>'

        >>> sanitize_html('<a href="javascript:alert()">Click</a>')
        '<a>Click</a>'
    """
    if allowed_tags is None:
        # Conservative default: only basic formatting
        allowed_tags = [
            "p",
            "br",
            "strong",
            "em",
            "u",
            "ul",
            "ol",
            "li",
            "a",
            "code",
            "pre",
        ]

    if allowed_attributes is None:
        # Only allow href on links, and validate it's not javascript: or data:
        allowed_attributes = {
            "a": ["href", "title"],
        }

    # Sanitize with bleach
    clean = bleach.clean(
        text,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=strip,
        protocols=["http", "https", "mailto"],  # Block javascript:, data:, etc.
    )

    return clean


def sanitize_string(text: str, max_length: int | None = None) -> str:
    """Sanitize plain text input by removing/escaping dangerous content.

    For plain text fields that shouldn't contain HTML at all.

    Args:
        text: Input text
        max_length: Maximum allowed length (truncate if longer)

    Returns:
        Sanitized plain text

    Example:
        >>> sanitize_string('<script>alert("xss")</script>')
        'alert("xss")'

        >>> sanitize_string('Normal text with "quotes"')
        'Normal text with "quotes"'
    """
    # Strip all HTML tags
    text = bleach.clean(text, tags=[], strip=True)

    # Normalize whitespace
    text = " ".join(text.split())

    # Truncate if needed
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip()

    return text


# ============================================================================
# Custom Scalars with Built-in Validation
# ============================================================================


SafeString = strawberry.scalar(
    NewType("SafeString", str),
    serialize=lambda v: str(v),
    parse_value=lambda v: sanitize_string(str(v)),
    description="String scalar that automatically sanitizes HTML/XSS attacks",
)
"""Custom scalar that automatically sanitizes input strings.

Use this for user-provided text that should be plain text (no HTML).

Example:
    @strawberry.input
    class CreateCommentInput:
        content: SafeString  # Automatically sanitized
        author: SafeString
"""


SafeURL = strawberry.scalar(
    NewType("SafeURL", str),
    serialize=lambda v: str(v),
    parse_value=lambda v: validate_url(str(v)),
    description="URL scalar that validates and sanitizes URLs, blocking dangerous protocols",
)
"""Custom scalar that validates URLs and blocks dangerous protocols.

Prevents javascript:, data:, file:, and other dangerous URL schemes.

Example:
    @strawberry.input
    class CreateWebhookInput:
        url: SafeURL  # Only http/https allowed

Raises:
    ValueError: If URL is invalid or uses a blocked protocol
"""


Email = strawberry.scalar(
    NewType("Email", str),
    serialize=lambda v: str(v),
    parse_value=lambda v: validate_email(str(v)),
    description="Email scalar that validates email addresses",
)
"""Custom scalar that validates email addresses.

Uses email-validator library for RFC-compliant validation.

Example:
    @strawberry.input
    class InviteUserInput:
        email: Email  # Validated email address

Raises:
    ValueError: If email is invalid
"""


# ============================================================================
# URL Validation
# ============================================================================


def validate_url(url: str, allowed_schemes: list[str] | None = None) -> str:
    """Validate and sanitize URL, blocking dangerous protocols.

    Args:
        url: URL to validate
        allowed_schemes: List of allowed URL schemes (default: http, https)

    Returns:
        Validated URL string

    Raises:
        ValueError: If URL is invalid or uses a blocked protocol

    Example:
        >>> validate_url('https://example.com/api')
        'https://example.com/api'

        >>> validate_url('javascript:alert("xss")')
        ValueError: URL scheme 'javascript' not allowed

        >>> validate_url('data:text/html,<script>alert("xss")</script>')
        ValueError: URL scheme 'data' not allowed
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")

    # Strip whitespace
    url = url.strip()

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}") from e

    # Check scheme
    if allowed_schemes is None:
        allowed_schemes = ["http", "https"]

    if not parsed.scheme:
        raise ValueError("URL must include a protocol (http:// or https://)")

    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError(
            f"URL scheme '{parsed.scheme}' not allowed. "
            f"Allowed schemes: {', '.join(allowed_schemes)}"
        )

    # Block localhost/private IPs in production
    if parsed.hostname:
        hostname_lower = parsed.hostname.lower()
        # Basic check for common private/local addresses
        blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
        if hostname_lower in blocked_hosts:
            # Note: In development, you might want to allow localhost
            # Use environment variable to control this behavior
            pass  # Allow for now, add environment check if needed

    return url


# ============================================================================
# Email Validation
# ============================================================================


def validate_email(email: str) -> str:
    """Validate email address using RFC-compliant validation.

    Args:
        email: Email address to validate

    Returns:
        Normalized email address

    Raises:
        ValueError: If email is invalid

    Example:
        >>> validate_email('user@example.com')
        'user@example.com'

        >>> validate_email('invalid.email')
        ValueError: The email address is not valid...
    """
    if not email or not isinstance(email, str):
        raise ValueError("Email must be a non-empty string")

    email = email.strip()

    try:
        # Validate and normalize
        validation = validate_email_address(email, check_deliverability=False)
        return validation.normalized
    except EmailNotValidError as e:
        raise ValueError(f"Invalid email address: {e!s}") from e


# ============================================================================
# Length Validation
# ============================================================================


def validate_length(
    value: str,
    min_length: int | None = None,
    max_length: int | None = None,
    field_name: str = "field",
) -> str:
    """Validate string length.

    Args:
        value: String to validate
        min_length: Minimum allowed length
        max_length: Maximum allowed length
        field_name: Name of field for error messages

    Returns:
        The validated string

    Raises:
        ValueError: If length is out of bounds

    Example:
        >>> validate_length('hello', min_length=3, max_length=10)
        'hello'

        >>> validate_length('hi', min_length=3)
        ValueError: field must be at least 3 characters
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    length = len(value)

    if min_length is not None and length < min_length:
        raise ValueError(f"{field_name} must be at least {min_length} characters")

    if max_length is not None and length > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")

    return value


# ============================================================================
# Filename Validation
# ============================================================================


def is_safe_filename(filename: str) -> bool:
    """Check if filename is safe (no path traversal, etc.).

    Args:
        filename: Filename to check

    Returns:
        True if filename is safe, False otherwise

    Example:
        >>> is_safe_filename('document.pdf')
        True

        >>> is_safe_filename('../../../etc/passwd')
        False

        >>> is_safe_filename('file<script>.pdf')
        False
    """
    if not filename or not isinstance(filename, str):
        return False

    # Check for path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return False

    # Check for dangerous characters
    dangerous_chars = ["<", ">", '"', "'", "&", "|", ";", "`", "$", "(", ")"]
    if any(char in filename for char in dangerous_chars):
        return False

    # Check for null bytes
    if "\x00" in filename:
        return False

    # Check length
    if len(filename) > 255:
        return False

    # Must have at least one character before extension
    return not filename.startswith(".")


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """Sanitize filename by replacing dangerous characters.

    Args:
        filename: Original filename
        replacement: Character to replace dangerous chars with

    Returns:
        Sanitized filename

    Example:
        >>> sanitize_filename('../../../etc/passwd')
        'etc_passwd'

        >>> sanitize_filename('file<script>.pdf')
        'file_script_.pdf'
    """
    # Remove path components
    filename = filename.replace("\\", "/")
    filename = filename.split("/")[-1]

    # Remove dangerous characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, filename)

    # Remove leading dots
    filename = filename.lstrip(".")

    # Ensure not empty
    if not filename:
        filename = "unnamed"

    # Truncate if too long
    if len(filename) > 255:
        name, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        max_name_len = 255 - len(ext) - 1
        filename = name[:max_name_len] + ("." + ext if ext else "")

    return filename


# ============================================================================
# Regex Patterns (for additional validation)
# ============================================================================


USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
"""Username pattern: alphanumeric, underscore, hyphen, 3-32 chars"""

SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")
"""Slug pattern: lowercase, numbers, hyphens only"""

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
"""Hex color pattern: #RRGGBB"""


def validate_username(username: str) -> str:
    """Validate username format.

    Args:
        username: Username to validate

    Returns:
        Validated username

    Raises:
        ValueError: If username format is invalid
    """
    if not USERNAME_PATTERN.match(username):
        raise ValueError(
            "Username must be 3-32 characters and contain only "
            "letters, numbers, underscores, and hyphens"
        )
    return username


def validate_slug(slug: str) -> str:
    """Validate slug format.

    Args:
        slug: Slug to validate

    Returns:
        Validated slug

    Raises:
        ValueError: If slug format is invalid
    """
    if not SLUG_PATTERN.match(slug):
        raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
    return slug


def validate_hex_color(color: str) -> str:
    """Validate hex color format.

    Args:
        color: Hex color to validate

    Returns:
        Validated hex color

    Raises:
        ValueError: If color format is invalid

    Example:
        >>> validate_hex_color('#FF5733')
        '#FF5733'

        >>> validate_hex_color('red')
        ValueError: Color must be in hex format (#RRGGBB)
    """
    if not HEX_COLOR_PATTERN.match(color):
        raise ValueError("Color must be in hex format (#RRGGBB)")
    return color.upper()


# ============================================================================
# Usage Examples
# ============================================================================

"""
Example: Using SafeString scalar in inputs
    @strawberry.input
    class CreatePostInput:
        title: SafeString  # Automatically sanitized
        content: str  # Allow HTML here, sanitize manually if needed

    @strawberry.mutation
    async def create_post(self, info: Info, input: CreatePostInput) -> Post:
        # input.title is already sanitized
        # Sanitize content if it should allow limited HTML:
        clean_content = sanitize_html(input.content)
        ...

Example: Using SafeURL scalar
    @strawberry.input
    class CreateWebhookInput:
        url: SafeURL  # Only http/https allowed, validated format
        secret: str

Example: Manual validation in resolvers
    @strawberry.mutation
    async def update_profile(
        self,
        info: Info,
        username: str,
        bio: str,
    ) -> UserPayload:
        try:
            # Validate username format
            username = validate_username(username)

            # Sanitize bio
            bio = sanitize_string(bio, max_length=500)

            # Update user...
        except ValueError as e:
            return UserError(
                code=ErrorCode.VALIDATION_ERROR,
                message=str(e),
                field="username" if "username" in str(e).lower() else "bio",
            )

Example: Validating file uploads
    @strawberry.mutation
    async def upload_file(
        self,
        info: Info,
        filename: str,
        content: Upload,
    ) -> FilePayload:
        # Validate filename
        if not is_safe_filename(filename):
            return FileError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid filename",
                field="filename",
            )

        # Or sanitize it
        safe_filename = sanitize_filename(filename)
        ...
"""
