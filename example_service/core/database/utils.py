"""Database utility functions.

Provides UUID v7 generation (time-sortable), short UUID encoding,
and parsing utilities.

UUID v7 Benefits:
    - Time-sortable: IDs created later are lexicographically greater
    - Better index locality: Sequential inserts cluster in B-tree
    - Timestamp extractable: Can derive creation time from ID
    - Still globally unique: Safe for distributed systems

Example:
    from example_service.core.database.utils import (
        generate_uuid7,
        short_uuid,
        parse_uuid,
        uuid_to_timestamp,
    )

    # Generate time-sortable UUID
    id1 = generate_uuid7()
    id2 = generate_uuid7()
    assert str(id1) < str(id2)  # Chronologically ordered

    # Create short URL-safe ID
    short_id = short_uuid()  # "2nGEqV1dQvS0yXE7JYjH5g"

    # Parse various formats
    uid = parse_uuid("550e8400-e29b-41d4-a716-446655440000")
    uid = parse_uuid("550e8400e29b41d4a716446655440000")  # No hyphens
    uid = parse_uuid(short_id)  # Short format

    # Extract timestamp from UUID v7
    created_at = uuid_to_timestamp(id1)
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from datetime import UTC, datetime


def generate_uuid7() -> uuid.UUID:
    """Generate a UUID v7 (time-sortable).

    UUID v7 encodes Unix timestamp in milliseconds in the first 48 bits,
    providing natural time-ordering while maintaining uniqueness.

    Returns:
        UUID v7 instance

    Example:
        >>> id1 = generate_uuid7()
        >>> id2 = generate_uuid7()
        >>> str(id1) < str(id2)  # Later IDs sort after earlier ones
        True
    """
    # Get current timestamp in milliseconds
    timestamp_ms = int(time.time() * 1000)

    # Generate random bytes for the rest
    random_bytes = os.urandom(10)

    # Construct UUID bytes according to RFC 9562:
    # - Bits 0-47: Unix timestamp in milliseconds (big-endian)
    # - Bits 48-51: Version (7)
    # - Bits 52-63: Random
    # - Bits 64-65: Variant (10)
    # - Bits 66-127: Random
    uuid_bytes = bytearray(16)

    # First 6 bytes: timestamp (48 bits)
    uuid_bytes[0:6] = timestamp_ms.to_bytes(6, byteorder="big")

    # Byte 6: version (7) in high nibble + random in low nibble
    uuid_bytes[6] = (random_bytes[0] & 0x0F) | 0x70

    # Byte 7: random
    uuid_bytes[7] = random_bytes[1]

    # Byte 8: variant (10) in high 2 bits + random in low 6 bits
    uuid_bytes[8] = (random_bytes[2] & 0x3F) | 0x80

    # Bytes 9-15: random
    uuid_bytes[9:16] = random_bytes[3:10]

    return uuid.UUID(bytes=bytes(uuid_bytes))


def short_uuid(uid: uuid.UUID | None = None, *, length: int = 22) -> str:
    """Convert UUID to URL-safe base64 short string.

    Produces a 22-character string from a full UUID, suitable for
    URLs and user-facing identifiers.

    Args:
        uid: UUID to encode (generates new UUID v4 if None)
        length: Output length (22 for full UUID precision)

    Returns:
        Base64 URL-safe encoded string

    Example:
        >>> short_uuid()  # Generate new short ID
        '2nGEqV1dQvS0yXE7JYjH5g'
        >>> short_uuid(uuid.uuid4())  # Encode existing UUID
        'VQ6EAOKbQdSnFkRmVUQAAA'
    """
    if uid is None:
        uid = uuid.uuid4()

    encoded = base64.urlsafe_b64encode(uid.bytes).rstrip(b"=")
    return encoded.decode("ascii")[:length]


def parse_uuid(value: str | uuid.UUID | bytes) -> uuid.UUID:
    """Parse UUID from various formats.

    Handles:
        - Standard UUID string (with/without hyphens)
        - Short base64 encoded UUIDs (22 chars)
        - Raw bytes (16 bytes)
        - UUID objects (passthrough)

    Args:
        value: UUID in any supported format

    Returns:
        UUID object

    Raises:
        ValueError: If value cannot be parsed as UUID

    Example:
        >>> parse_uuid("550e8400-e29b-41d4-a716-446655440000")
        UUID('550e8400-e29b-41d4-a716-446655440000')
        >>> parse_uuid("550e8400e29b41d4a716446655440000")  # No hyphens
        UUID('550e8400-e29b-41d4-a716-446655440000')
    """
    if isinstance(value, uuid.UUID):
        return value

    if isinstance(value, bytes):
        if len(value) == 16:
            return uuid.UUID(bytes=value)
        raise ValueError(f"Invalid UUID bytes length: {len(value)}")

    # String handling
    value = value.strip()

    # Try standard UUID format first (32 hex chars or 36 with hyphens)
    if len(value) in (32, 36):
        try:
            return uuid.UUID(value)
        except ValueError:
            pass

    # Try base64 short format (typically 22 chars)
    if len(value) <= 24:
        try:
            # Pad to multiple of 4 for base64
            padding = 4 - (len(value) % 4) if len(value) % 4 else 0
            padded = value + "=" * padding
            decoded = base64.urlsafe_b64decode(padded)
            if len(decoded) == 16:
                return uuid.UUID(bytes=decoded)
        except Exception:
            pass

    raise ValueError(f"Cannot parse UUID from: {value!r}")


def uuid_to_timestamp(uid: uuid.UUID) -> datetime | None:
    """Extract timestamp from UUID v7.

    Only works with UUID v7 (time-sortable). Returns None for other versions.

    Args:
        uid: UUID to extract timestamp from

    Returns:
        datetime (UTC) if UUID v7, None otherwise

    Example:
        >>> uid = generate_uuid7()
        >>> ts = uuid_to_timestamp(uid)
        >>> ts  # datetime close to now
        datetime.datetime(2024, 1, 15, 12, 30, 45, 123000, tzinfo=datetime.timezone.utc)
    """
    # Check version (bits 48-51, which is nibble at position 12 in hex)
    version = uid.version
    if version != 7:
        return None

    # Extract timestamp from first 48 bits
    # UUID bytes: timestamp is in bytes 0-5 (big-endian)
    timestamp_ms = int.from_bytes(uid.bytes[:6], byteorder="big")

    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


__all__ = [
    "generate_uuid7",
    "short_uuid",
    "parse_uuid",
    "uuid_to_timestamp",
]
