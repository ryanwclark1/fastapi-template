"""Custom SQLAlchemy types for enhanced functionality.

Provides specialized column types that handle encryption, XML, network types,
hierarchical data, and validated types transparently at the database layer.

Types included:
- EncryptedString: Transparent Fernet encryption for sensitive strings
- EncryptedText: Encrypted Text for larger content
- XMLType: PostgreSQL native XML column with optional validation
- INETType: PostgreSQL INET type for IP addresses (IPv4/IPv6)
- CIDRType: PostgreSQL CIDR type for network addresses
- MACAddrType: PostgreSQL MACADDR type for hardware addresses
- LtreeType: PostgreSQL ltree type for hierarchical data
- EmailType: Validated email addresses with normalization
- URLType: Validated URLs with scheme enforcement
- PhoneNumberType: International phone numbers in E.164 format
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sqlalchemy import String, Text, TypeDecorator, types
from sqlalchemy.types import TypeEngine

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.engine import Dialect
    from sqlalchemy.sql.expression import ColumnElement

logger = logging.getLogger(__name__)


class EncryptedString(TypeDecorator):
    """Transparent string encryption/decryption using Fernet.

    Automatically encrypts values before storing in database and decrypts
    when retrieving. Requires cryptography library.

    Example:
            from example_service.core.database.types import EncryptedString

        class User(TimestampedBase):
            __tablename__ = "users"
            email: Mapped[str]
            ssn: Mapped[str] = mapped_column(
                EncryptedString(key="your-secret-key-here")
            )

        # Usage - encryption is automatic:
        user = User(email="test@example.com", ssn="123-45-6789")
        session.add(user)
        await session.commit()

        # Decryption is automatic:
        user = await session.get(User, 1)
        print(user.ssn)  # "123-45-6789" (decrypted)

    Note:
        - Requires `cryptography` package: `pip install cryptography`
        - Key should be 32 url-safe base64-encoded bytes
        - Generate with: `from cryptography.fernet import Fernet; Fernet.generate_key()`
        - Store key in environment variable, not in code!
    """

    impl = String
    cache_ok = True

    def __init__(
        self,
        key: str | bytes | None = None,
        *,
        max_length: int = 255,
        **kwargs: Any,
    ):
        """Initialize encrypted string type.

        Args:
            key: Encryption key (Fernet key). Should be from environment variable.
            max_length: Maximum length for underlying String column
            **kwargs: Additional arguments for String type
        """
        super().__init__(**kwargs)
        self.key = key
        self.max_length = max_length
        self._fernet: Any = None

        if key is not None:
            self._init_fernet(key)

    def _init_fernet(self, key: str | bytes) -> None:
        """Initialize Fernet cipher with key."""
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:
            msg = (
                "EncryptedString requires 'cryptography' package. "
                "Install with: pip install cryptography"
            )
            raise ImportError(msg) from e

        if isinstance(key, str):
            key = key.encode("utf-8")

        self._fernet = Fernet(key)

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        """Load appropriate type based on dialect.

        Args:
            dialect: Database dialect

        Returns:
            Appropriate column type for dialect
        """
        # MySQL has strict length limits
        if dialect.name == "mysql":
            return dialect.type_descriptor(Text())

        # Oracle defaults to 4000 byte VARCHAR2
        if dialect.name == "oracle":
            return dialect.type_descriptor(String(4000))

        return dialect.type_descriptor(String(self.max_length))

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Encrypt value before storing in database.

        Args:
            value: Plain text value
            dialect: Database dialect

        Returns:
            Encrypted value or None
        """
        _ = dialect
        if value is None:
            return None

        if self._fernet is None:
            msg = "EncryptedString encryption key not set. Pass key parameter or call mount_vault()."
            raise ValueError(msg)

        # Encrypt and return as string
        encrypted_bytes = self._fernet.encrypt(value.encode("utf-8"))
        return str(encrypted_bytes.decode("utf-8"))

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Decrypt value after retrieving from database.

        Args:
            value: Encrypted value from database
            dialect: Database dialect

        Returns:
            Decrypted plain text or None
        """
        _ = dialect
        if value is None:
            return None

        if self._fernet is None:
            msg = "EncryptedString encryption key not set. Cannot decrypt without key."
            raise ValueError(msg)

        # Decrypt and return as string
        decrypted_bytes = self._fernet.decrypt(value.encode("utf-8"))
        return str(decrypted_bytes.decode("utf-8"))


def encrypt_value(value: str, key: str | bytes) -> str:
    """Encrypt a value using Fernet encryption.

    Args:
        value: Plain text value to encrypt
        key: Fernet encryption key

    Returns:
        Encrypted value as string
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        msg = "encrypt_value requires 'cryptography' package. Install with: pip install cryptography"
        raise ImportError(msg) from e

    if isinstance(key, str):
        key = key.encode("utf-8")

    fernet = Fernet(key)
    encrypted_bytes = fernet.encrypt(value.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_value(value: str, key: str | bytes) -> str:
    """Decrypt a value using Fernet decryption.

    Args:
        value: Encrypted value to decrypt
        key: Fernet encryption key

    Returns:
        Decrypted plain text value
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        msg = "decrypt_value requires 'cryptography' package. Install with: pip install cryptography"
        raise ImportError(msg) from e

    if isinstance(key, str):
        key = key.encode("utf-8")

    fernet = Fernet(key)
    decrypted_bytes = fernet.decrypt(value.encode("utf-8"))
    return decrypted_bytes.decode("utf-8")


class EncryptedText(EncryptedString):
    """Encrypted Text type for larger encrypted content.

    Similar to EncryptedString but uses Text column type for larger data.

    Example:
        >>> from example_service.core.database.types import EncryptedText
        >>>
        >>> class Document(TimestampedBase):
        ...     __tablename__ = "documents"
        ...     title: Mapped[str]
        ...     sensitive_content: Mapped[str] = mapped_column(EncryptedText(key="your-secret-key"))
    """

    impl = Text

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        """Always use Text type for large encrypted content."""
        return dialect.type_descriptor(Text())


# =============================================================================
# PostgreSQL-Specific Types
# =============================================================================


class XMLType(types.UserDefinedType[str]):
    """PostgreSQL native XML column type with optional validation.

    Uses PostgreSQL's native XML type which provides:
    - Well-formedness validation on insert (PostgreSQL validates XML structure)
    - XPath query support: ``xpath('//element', xml_column)``
    - XML functions: ``xmlparse()``, ``xmlserialize()``, ``xmlelement()``

    Common use cases:
    - SAML metadata and assertions
    - SOAP message storage
    - Configuration files in XML format
    - RSS/Atom feed content
    - Legacy system integration

    Example:
        >>> from example_service.core.database.types import XMLType
        >>>
        >>> class SAMLConfig(Base):
        ...     __tablename__ = "saml_configs"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
        ...     idp_metadata: Mapped[str] = mapped_column(XMLType())
        ...     # With Python-side validation before insert:
        ...     sp_metadata: Mapped[str] = mapped_column(XMLType(validate=True))
        >>>
        >>> # Usage:
        >>> config = SAMLConfig(idp_metadata='<?xml version="1.0"?><metadata>...</metadata>')
        >>> session.add(config)
        >>> await session.commit()
        >>>
        >>> # Query with XPath (raw SQL):
        >>> result = await session.execute(
        ...     text("SELECT xpath('//EntityDescriptor/@entityID', idp_metadata) FROM saml_configs")
        ... )

    Note:
        - **PostgreSQL only**: This type uses PostgreSQL's native XML type.
          Other databases will store as TEXT without XML validation.
        - PostgreSQL validates XML on insert - malformed XML raises an error.
        - For cross-database compatibility, use TEXT with application-level validation.
    """

    cache_ok = True

    def __init__(self, validate: bool = False) -> None:
        """Initialize XML type.

        Args:
            validate: If True, validate XML in Python before sending to database.
                     Useful for getting clearer error messages than PostgreSQL's.
                     Requires ``lxml`` or uses stdlib ``xml.etree``.
        """
        self._validate = validate

    def get_col_spec(self, **kw: Any) -> str:
        """Return the PostgreSQL column type specification.

        Returns:
            "XML" for PostgreSQL native XML type.
        """
        _ = kw  # Unused
        return "XML"

    def bind_processor(self, dialect: Any) -> Callable[[Any], Any] | None:
        """Process value before sending to database.

        If validation is enabled, validates XML structure before insert.
        Otherwise, passes through unchanged.

        Args:
            dialect: Database dialect

        Returns:
            Processor function or None for pass-through
        """
        _ = dialect  # Unused

        if not self._validate:
            # Pass-through - let PostgreSQL validate
            return None

        def process(value: Any) -> Any:
            if value is None:
                return None

            if not isinstance(value, str):
                value = str(value)

            # Validate XML structure
            self._validate_xml(value)
            return value

        return process

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[Any], Any] | None:
        """Process value received from database.

        Returns XML as string (pass-through).

        Args:
            dialect: Database dialect
            coltype: Column type

        Returns:
            None for pass-through (no transformation needed)
        """
        _ = dialect, coltype  # Unused
        # Pass-through - return as string
        return None

    def _validate_xml(self, value: str) -> None:
        """Validate XML string is well-formed.

        Args:
            value: XML string to validate

        Raises:
            ValueError: If XML is malformed
        """
        try:
            # Try lxml first (faster, better error messages)
            from lxml import etree  # type: ignore[import-untyped]

            etree.fromstring(value.encode("utf-8"))
        except ImportError:
            # Fall back to stdlib
            # Note: XML is from database (trusted source), not user input
            import xml.etree.ElementTree as ET

            try:
                ET.fromstring(value)  # noqa: S314
            except ET.ParseError as e:
                raise ValueError(f"Invalid XML: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid XML: {e}") from e


class INETType(types.UserDefinedType[str]):
    """PostgreSQL INET type for IP addresses (IPv4 and IPv6).

    Uses PostgreSQL's native INET type which provides:
    - Validation of IP address format
    - Support for CIDR notation (e.g., "192.168.1.0/24")
    - Network operators: ``<<``, ``>>``, ``&&`` for subnet containment
    - Functions: ``host()``, ``network()``, ``netmask()``, ``masklen()``

    Common use cases:
    - Audit logs with client IP addresses
    - Rate limiting by IP
    - Access control lists
    - Network configuration storage

    Example:
        >>> from example_service.core.database.types import INETType
        >>>
        >>> class AuditLog(Base):
        ...     __tablename__ = "audit_logs"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
        ...     client_ip: Mapped[str | None] = mapped_column(INETType())
        ...     action: Mapped[str]
        >>>
        >>> # Usage:
        >>> log = AuditLog(client_ip="192.168.1.100", action="login")
        >>> session.add(log)
        >>>
        >>> # Query logs from a subnet (raw SQL):
        >>> result = await session.execute(
        ...     text("SELECT * FROM audit_logs WHERE client_ip << '192.168.1.0/24'")
        ... )

    Note:
        - **PostgreSQL only**: Other databases will store as VARCHAR.
        - Accepts both IPv4 and IPv6 addresses.
        - Supports CIDR notation for network ranges.
        - For Python IP manipulation, use ``ipaddress`` module on retrieved values.
    """

    cache_ok = True

    def __init__(self, validate: bool = False) -> None:
        """Initialize INET type.

        Args:
            validate: If True, validate IP address format in Python before insert.
                     Uses stdlib ``ipaddress`` module.
        """
        self._validate = validate

    def get_col_spec(self, **kw: Any) -> str:
        """Return the PostgreSQL column type specification.

        Returns:
            "INET" for PostgreSQL native INET type.
        """
        _ = kw  # Unused
        return "INET"

    def bind_processor(self, dialect: Any) -> Callable[[Any], Any] | None:
        """Process value before sending to database.

        If validation is enabled, validates IP address format.

        Args:
            dialect: Database dialect

        Returns:
            Processor function or None for pass-through
        """
        _ = dialect  # Unused

        if not self._validate:
            return None

        def process(value: Any) -> Any:
            if value is None:
                return None

            if not isinstance(value, str):
                value = str(value)

            self._validate_inet(value)
            return value

        return process

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[Any], Any] | None:
        """Process value received from database.

        Returns IP address as string (pass-through).

        Args:
            dialect: Database dialect
            coltype: Column type

        Returns:
            None for pass-through
        """
        _ = dialect, coltype  # Unused
        return None

    def _validate_inet(self, value: str) -> None:
        """Validate IP address or CIDR notation.

        Args:
            value: IP address string to validate

        Raises:
            ValueError: If IP address format is invalid
        """
        import ipaddress

        try:
            # Try as network (CIDR notation)
            if "/" in value:
                ipaddress.ip_network(value, strict=False)
            else:
                # Try as single address
                ipaddress.ip_address(value)
        except ValueError as e:
            raise ValueError(f"Invalid IP address '{value}': {e}") from e


class CIDRType(types.UserDefinedType[str]):
    """PostgreSQL CIDR type for network addresses with prefix length.

    Similar to INET but requires valid network addresses (host bits must be zero).
    Use CIDR when storing network ranges, INET when storing host addresses.

    Example:
        >>> from example_service.core.database.types import CIDRType
        >>>
        >>> class AllowedNetwork(Base):
        ...     __tablename__ = "allowed_networks"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
        ...     network: Mapped[str] = mapped_column(CIDRType())
        ...     description: Mapped[str]
        >>>
        >>> # Valid: "192.168.1.0/24" (network address)
        >>> # Invalid: "192.168.1.100/24" (host address - use INET instead)

    Note:
        - **PostgreSQL only**: Other databases will store as VARCHAR.
        - CIDR enforces that host bits are zero (strict network notation).
        - Use INET if you need to store arbitrary IP/prefix combinations.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        """Return the PostgreSQL column type specification."""
        _ = kw
        return "CIDR"

    def bind_processor(self, dialect: Any) -> Callable[[Any], Any] | None:
        """Pass-through processor."""
        _ = dialect
        return None

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[Any], Any] | None:
        """Pass-through processor."""
        _ = dialect, coltype
        return None


class MACAddrType(types.UserDefinedType[str]):
    """PostgreSQL MACADDR type for MAC addresses.

    Uses PostgreSQL's native MACADDR type for storing hardware addresses.
    Useful for network device tracking, DHCP management, etc.

    Example:
        >>> from example_service.core.database.types import MACAddrType
        >>>
        >>> class NetworkDevice(Base):
        ...     __tablename__ = "network_devices"
        ...     id: Mapped[int] = mapped_column(primary_key=True)
        ...     mac_address: Mapped[str] = mapped_column(MACAddrType())
        ...     hostname: Mapped[str | None]

    Note:
        - **PostgreSQL only**: Other databases will store as VARCHAR.
        - Accepts various formats: "08:00:2b:01:02:03", "08-00-2b-01-02-03"
        - PostgreSQL normalizes to lowercase colon-separated format.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        """Return the PostgreSQL column type specification."""
        _ = kw
        return "MACADDR"

    def bind_processor(self, dialect: Any) -> Callable[[Any], Any] | None:
        """Pass-through processor."""
        _ = dialect
        return None

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[Any], Any] | None:
        """Pass-through processor."""
        _ = dialect, coltype
        return None


# =============================================================================
# Hierarchical Data Types
# =============================================================================


class LtreeType(types.UserDefinedType[str]):
    """PostgreSQL ltree type for hierarchical path data.

    Uses PostgreSQL's native ltree extension for materialized path storage.
    Paths are dot-separated strings like "electronics.computers.laptops".

    PostgreSQL ltree provides:
    - Efficient ancestor/descendant queries using @> and <@ operators
    - Pattern matching with lquery (e.g., "*.laptops.*")
    - Subtree operations (subpath, nlevel, index)

    Use cases:
    - Category hierarchies (product catalogs)
    - Organizational charts
    - File system representations
    - Threaded comments
    - Permission inheritance

    Example:
        >>> from example_service.core.database.types import LtreeType
        >>> from example_service.core.database import Base, IntegerPKMixin
        >>>
        >>> class Category(Base, IntegerPKMixin):
        ...     __tablename__ = "categories"
        ...     name: Mapped[str] = mapped_column(String(255))
        ...     path: Mapped[str] = mapped_column(LtreeType())
        >>>
        >>> # Create categories
        >>> electronics = Category(name="Electronics", path="electronics")
        >>> computers = Category(name="Computers", path="electronics.computers")
        >>> laptops = Category(name="Laptops", path="electronics.computers.laptops")
        >>>
        >>> # Query descendants of electronics
        >>> stmt = select(Category).where(Category.path.descendant_of("electronics"))
        >>>
        >>> # Query with lquery pattern
        >>> stmt = select(Category).where(Category.path.match("*.computers.*"))

    Note:
        - **PostgreSQL only**: Requires ltree extension
        - Create extension in migration: CREATE EXTENSION IF NOT EXISTS ltree
        - Add GiST index for performance: CREATE INDEX ... USING GIST (path)
        - Other databases will store as TEXT without query operators
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL column type specification."""
        _ = kw
        return "LTREE"

    def bind_processor(self, dialect: Any) -> Callable[[Any], Any] | None:
        """Process value before sending to database."""
        _ = dialect

        def process(value: Any) -> Any:
            if value is None:
                return None
            # Handle LtreePath wrapper objects
            if hasattr(value, "__str__"):
                return str(value)
            return value

        return process

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[Any], Any] | None:
        """Process value received from database - wrap in LtreePath."""
        _ = dialect, coltype

        def process(value: Any) -> Any:
            if value is None:
                return None
            # Import here to avoid circular imports
            from example_service.core.database.hierarchy.ltree import LtreePath

            return LtreePath(value)

        return process

    class comparator_factory(TypeEngine.Comparator[str]):
        """Custom comparator for ltree-specific operations.

        SQLAlchemy 2.0+ uses TypeEngine.Comparator as the base class for
        custom type comparators. This provides ltree-specific operators
        for hierarchical queries.
        """

        def ancestor_of(self, other: str) -> ColumnElement[bool]:
            """Check if this path is an ancestor of other.

            Uses PostgreSQL @> operator.
            Example: "a.b" @> "a.b.c" returns True (a.b is ancestor of a.b.c)

            Args:
                other: Path to check against

            Returns:
                SQLAlchemy column expression for WHERE clause
            """
            return self.op("@>")(other)  # type: ignore[return-value]

        def descendant_of(self, other: str) -> ColumnElement[bool]:
            """Check if this path is a descendant of other.

            Uses PostgreSQL <@ operator.
            Example: "a.b.c" <@ "a.b" returns True (a.b.c descends from a.b)

            Args:
                other: Path to check against

            Returns:
                SQLAlchemy column expression for WHERE clause
            """
            return self.op("<@")(other)  # type: ignore[return-value]

        def match(self, pattern: str) -> ColumnElement[bool]:  # type: ignore[override]
            """Match against lquery pattern.

            Uses PostgreSQL ~ operator with lquery.
            Patterns support:
            - * matches any single label
            - *.path matches path at any depth
            - {a,b} matches a OR b

            Example: "*.computers.*" matches any path containing "computers"

            Args:
                pattern: lquery pattern string

            Returns:
                SQLAlchemy column expression for WHERE clause
            """
            return self.op("~")(pattern)  # type: ignore[return-value]

        def match_any(self, patterns: list[str]) -> ColumnElement[bool]:
            """Match against any of the lquery patterns.

            Uses PostgreSQL ? operator with lquery array.

            Args:
                patterns: List of lquery patterns

            Returns:
                SQLAlchemy column expression for WHERE clause
            """
            from sqlalchemy import Text, cast
            from sqlalchemy.dialects.postgresql import ARRAY

            return self.op("?")(cast(patterns, ARRAY(Text())))  # type: ignore[return-value]


# =============================================================================
# Validated Types
# =============================================================================


class EmailType(TypeDecorator[str]):
    """Validated email address storage with normalization.

    Uses email-validator (same as Pydantic EmailStr) for RFC-compliant
    validation. Automatically normalizes emails on storage.

    PostgreSQL: VARCHAR(254) per RFC 5321 maximum

    Example:
        >>> from example_service.core.database.types import EmailType
        >>>
        >>> class User(Base, IntegerPKMixin):
        ...     __tablename__ = "users"
        ...     email: Mapped[str] = mapped_column(EmailType(), unique=True)
        >>>
        >>> # Validation and normalization happen automatically:
        >>> user = User(email="John.Doe@EXAMPLE.COM")
        >>> # Stored as: "john.doe@example.com"

    Note:
        - Requires `email-validator` package (included with pydantic[email])
        - Raises ValueError if email format is invalid
        - Normalization lowercases the entire email by default
    """

    impl = String(254)
    cache_ok = True

    def __init__(
        self,
        validate: bool = True,
        normalize: bool = True,
        check_deliverability: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize EmailType.

        Args:
            validate: Validate email format on bind (default: True)
            normalize: Normalize email (lowercase) on bind (default: True)
            check_deliverability: Check DNS MX records (default: False, slow)
            **kwargs: Additional TypeDecorator arguments
        """
        super().__init__(**kwargs)
        self._validate = validate
        self._normalize = normalize
        self._check_deliverability = check_deliverability

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Validate and normalize email before storing.

        Args:
            value: Email address to store
            dialect: Database dialect

        Returns:
            Normalized email or None

        Raises:
            ValueError: If email format is invalid
        """
        _ = dialect
        if value is None:
            return None

        if not self._validate and not self._normalize:
            return value

        try:
            from email_validator import EmailNotValidError
            from email_validator import validate_email as validate_email_address
        except ImportError as e:
            msg = (
                "EmailType requires 'email-validator' package. "
                "Install with: pip install email-validator"
            )
            raise ImportError(msg) from e

        try:
            result = validate_email_address(
                value,
                check_deliverability=self._check_deliverability,
            )
            return result.normalized if self._normalize else value
        except EmailNotValidError as e:
            raise ValueError(f"Invalid email address: {e}") from e

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Pass-through on read."""
        _ = dialect
        return value


class URLType(TypeDecorator[str]):
    """Validated URL storage with scheme enforcement.

    Validates URL structure and optionally restricts allowed schemes.
    Uses Python's stdlib urllib.parse for validation.

    PostgreSQL: VARCHAR(2048) by default (practical URL limit), TEXT for longer

    Example:
        >>> from example_service.core.database.types import URLType
        >>>
        >>> class Webhook(Base, IntegerPKMixin):
        ...     __tablename__ = "webhooks"
        ...     callback_url: Mapped[str] = mapped_column(
        ...         URLType(allowed_schemes=["https"]),  # HTTPS only
        ...         nullable=False,
        ...     )
        >>>
        >>> webhook = Webhook(callback_url="https://example.com/hook")
        >>> # Invalid schemes will raise ValueError

    Note:
        - Validates URL format on bind (insert/update)
        - Raises ValueError if URL format is invalid or scheme not allowed
        - Does not validate that URL is reachable (no HTTP request)
    """

    impl = String
    cache_ok = True

    def __init__(
        self,
        max_length: int = 2048,
        allowed_schemes: list[str] | None = None,
        require_host: bool = True,
        validate: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize URLType.

        Args:
            max_length: Maximum URL length (default: 2048)
            allowed_schemes: Allowed URL schemes (default: http, https)
            require_host: Require hostname in URL (default: True)
            validate: Validate URL format on bind (default: True)
            **kwargs: Additional TypeDecorator arguments
        """
        super().__init__(**kwargs)
        self.max_length = max_length
        self.allowed_schemes = allowed_schemes or ["http", "https"]
        self._require_host = require_host
        self._validate = validate

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        """Load appropriate type based on max_length."""
        if self.max_length > 2048:
            return dialect.type_descriptor(Text())
        return dialect.type_descriptor(String(self.max_length))

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Validate URL before storing.

        Args:
            value: URL to store
            dialect: Database dialect

        Returns:
            Validated URL or None

        Raises:
            ValueError: If URL format is invalid or scheme not allowed
        """
        _ = dialect
        if value is None:
            return None

        if not self._validate:
            return value

        value = value.strip()

        if len(value) > self.max_length:
            raise ValueError(f"URL exceeds maximum length of {self.max_length}")

        try:
            parsed = urlparse(value)
        except Exception as e:
            raise ValueError(f"Invalid URL format: {e}") from e

        if not parsed.scheme:
            msg = "URL must include a scheme (e.g., https://)"
            raise ValueError(msg)

        if parsed.scheme.lower() not in [s.lower() for s in self.allowed_schemes]:
            raise ValueError(
                f"URL scheme '{parsed.scheme}' not allowed. "
                f"Allowed: {', '.join(self.allowed_schemes)}"
            )

        if self._require_host and not parsed.netloc:
            msg = "URL must include a host"
            raise ValueError(msg)

        return value

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Pass-through on read."""
        _ = dialect
        return value


class PhoneNumberType(TypeDecorator[str]):
    """International phone number storage in E.164 format.

    Uses phonenumbers library (Google's libphonenumber) for validation
    and normalization. Stores in E.164 format (+12125551234) for
    consistent querying.

    PostgreSQL: VARCHAR(16) - E.164 max is 15 digits + '+'

    Example:
        >>> from example_service.core.database.types import PhoneNumberType
        >>>
        >>> class Contact(Base, IntegerPKMixin):
        ...     __tablename__ = "contacts"
        ...     phone: Mapped[str | None] = mapped_column(
        ...         PhoneNumberType(default_region="US"),
        ...         nullable=True,
        ...     )
        >>>
        >>> # Various input formats accepted:
        >>> contact.phone = "(212) 555-1234"  # -> +12125551234
        >>> contact.phone = "+44 20 7946 0958"  # -> +442079460958

    Note:
        - Requires `phonenumbers` package: pip install phonenumbers
        - Stores in E.164 format (compact, unambiguous)
        - Use format_phone_* helpers for display formatting
    """

    impl = String(16)
    cache_ok = True

    def __init__(
        self,
        default_region: str = "US",
        validate: bool = True,
        strict: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize PhoneNumberType.

        Args:
            default_region: Default region for parsing local numbers (e.g., "US", "GB")
            validate: Validate phone number format (default: True)
            strict: Require valid phone number for region (default: False)
            **kwargs: Additional TypeDecorator arguments
        """
        super().__init__(**kwargs)
        self._default_region = default_region
        self._validate = validate
        self._strict = strict

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Validate and convert phone number to E.164 format.

        Args:
            value: Phone number in any format
            dialect: Database dialect

        Returns:
            E.164 formatted phone number or None

        Raises:
            ValueError: If phone number format is invalid
            ImportError: If phonenumbers package not installed
        """
        _ = dialect
        if value is None:
            return None

        try:
            import phonenumbers
        except ImportError as e:
            msg = (
                "PhoneNumberType requires 'phonenumbers' package. "
                "Install with: pip install phonenumbers"
            )
            raise ImportError(msg) from e

        value = value.strip()
        if not value:
            return None

        try:
            parsed = phonenumbers.parse(value, self._default_region)
        except phonenumbers.NumberParseException as e:
            raise ValueError(f"Invalid phone number: {e}") from e

        if self._validate and self._strict and not phonenumbers.is_valid_number(parsed):
            msg = "Phone number is not valid for region"
            raise ValueError(msg)

        # Return E.164 format
        return str(
            phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        )

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Pass-through on read (returns E.164 format)."""
        _ = dialect
        return value


# =============================================================================
# Phone Number Formatting Utilities
# =============================================================================


def format_phone_national(e164: str, region: str = "US") -> str:
    """Format E.164 phone number for national display.

    Args:
        e164: Phone number in E.164 format (+12125551234)
        region: Region for formatting (default: US)

    Returns:
        Nationally formatted number (e.g., "(212) 555-1234")

    Example:
        >>> format_phone_national("+12125551234")
        '(212) 555-1234'
    """
    import phonenumbers

    parsed = phonenumbers.parse(e164, region)
    return str(
        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
    )


def format_phone_international(e164: str) -> str:
    """Format E.164 phone number for international display.

    Args:
        e164: Phone number in E.164 format (+12125551234)

    Returns:
        Internationally formatted number (e.g., "+1 212-555-1234")

    Example:
        >>> format_phone_international("+12125551234")
        '+1 212-555-1234'
    """
    import phonenumbers

    parsed = phonenumbers.parse(e164)
    return str(
        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    )


__all__ = [
    "CIDRType",
    "EmailType",
    "EncryptedString",
    "EncryptedText",
    "INETType",
    "LtreeType",
    "MACAddrType",
    "PhoneNumberType",
    "URLType",
    "XMLType",
    "format_phone_international",
    "format_phone_national",
]
