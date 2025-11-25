"""Custom SQLAlchemy types for enhanced functionality.

Provides specialized column types that handle encryption, JSON, and other
data transformations transparently at the database layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import String, Text, TypeDecorator

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect


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
            raise ValueError(
                "EncryptedString encryption key not set. Pass key parameter or call mount_vault()."
            )

        # Encrypt and return as string
        encrypted_bytes = self._fernet.encrypt(value.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")

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
            raise ValueError("EncryptedString encryption key not set. Cannot decrypt without key.")

        # Decrypt and return as string
        decrypted_bytes = self._fernet.decrypt(value.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")


class EncryptedText(EncryptedString):
    """Encrypted Text type for larger encrypted content.

    Similar to EncryptedString but uses Text column type for larger data.

    Example:
            from example_service.core.database.types import EncryptedText

        class Document(TimestampedBase):
            __tablename__ = "documents"
            title: Mapped[str]
            sensitive_content: Mapped[str] = mapped_column(
                EncryptedText(key="your-secret-key")
            )
    """

    impl = Text

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        """Always use Text type for large encrypted content."""
        return dialect.type_descriptor(Text())


__all__ = [
    "EncryptedString",
    "EncryptedText",
]
