"""Enhanced base database model classes with composable mixins.

This module provides a flexible foundation for SQLAlchemy models with:
- Multiple primary key strategies (Integer, UUID v4/v7)
- Timestamp tracking (created_at, updated_at)
- User audit tracking (created_by, updated_by)
- Soft delete support (deleted_at)
- Automatic table name generation

Models can mix and match capabilities by inheriting from specific mixins.

Examples:
    Simple model with integer PK and timestamps:
    class User(Base, IntegerPKMixin, TimestampMixin):
        __tablename__ = "users"
        email: Mapped[str] = mapped_column(String(255), unique=True)

    UUID model with full audit trail:
    class Document(Base, UUIDPKMixin, TimestampMixin, AuditColumnsMixin):
        __tablename__ = "documents"
        title: Mapped[str] = mapped_column(String(255))

    Soft-deletable model:
    class Post(Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin):
        __tablename__ = "posts"
        content: Mapped[str] = mapped_column(Text)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql import func

# Consistent naming convention for database constraints
# Ensures predictable names for migrations and schema management
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Enhanced declarative base with automatic table naming.

    Provides:
    - Consistent constraint naming via NAMING_CONVENTION
    - Automatic table name generation from class name (lowercase)
    - Metadata registry for all models

    The automatic table naming can be overridden by setting __tablename__
    explicitly on the model class.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """Auto-derive table name from class name (lowercase).

        Examples:
            User -> users (you must add 's' manually via __tablename__)
            UserProfile -> userprofile
            PaymentTransaction -> paymenttransaction

        For complex table names, override __tablename__ explicitly.
        """
        return cls.__name__.lower()


# ============================================================================
# Primary Key Mixins
# ============================================================================


class IntegerPKMixin:
    """Integer auto-increment primary key.

    Best for:
    - Small to medium applications
    - Single database deployments
    - When sequential IDs are acceptable
    - Simpler joins and foreign keys

    Provides:
        id: Auto-incrementing integer primary key
    """

    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
        comment="Auto-incrementing integer primary key",
    )


class UUIDPKMixin:
    """UUID v4 primary key.

    Best for:
    - Distributed systems
    - Preventing ID enumeration attacks
    - Merging data from multiple sources
    - Public-facing IDs in APIs

    Provides:
        id: UUID v4 primary key (random)

    Note: UUID v4 is not time-sortable. For time-ordered UUIDs,
    use UUIDv7PKMixin instead.
    """

    __allow_unmapped__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 primary key",
    )


class UUIDv7PKMixin:
    """UUID v7 primary key (time-sortable).

    UUID v7 encodes Unix timestamp in the first 48 bits, providing:
    - Natural time-ordering (later IDs sort after earlier ones)
    - Better B-tree index locality for sequential inserts
    - Extractable creation timestamp
    - Global uniqueness (safe for distributed systems)

    Best for:
    - High-volume insert scenarios
    - When chronological ordering by ID is useful
    - Distributed systems with time correlation needs
    - Event sourcing and audit logs

    Provides:
        id: UUID v7 primary key (time-ordered)

    Example:
        class AuditLog(Base, UUIDv7PKMixin, TimestampMixin):
            __tablename__ = "audit_logs"
            action: Mapped[str] = mapped_column(String(255))

        # IDs are naturally ordered by creation time
        log1 = AuditLog(action="create")
        log2 = AuditLog(action="update")
        assert str(log1.id) < str(log2.id)  # True if log1 created first
    """

    __allow_unmapped__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=lambda: _generate_uuid7(),
        comment="UUID v7 primary key (time-sortable)",
    )


def _generate_uuid7() -> uuid.UUID:
    """Generate UUID v7 for default value.

    Inline implementation to avoid circular imports.
    For full UUID utilities, use core.database.utils.
    """
    import os
    import time

    timestamp_ms = int(time.time() * 1000)
    random_bytes = os.urandom(10)

    uuid_bytes = bytearray(16)
    uuid_bytes[0:6] = timestamp_ms.to_bytes(6, byteorder="big")
    uuid_bytes[6] = (random_bytes[0] & 0x0F) | 0x70  # Version 7
    uuid_bytes[7] = random_bytes[1]
    uuid_bytes[8] = (random_bytes[2] & 0x3F) | 0x80  # Variant
    uuid_bytes[9:16] = random_bytes[3:10]

    return uuid.UUID(bytes=bytes(uuid_bytes))


# ============================================================================
# Audit and Tracking Mixins
# ============================================================================


class TimestampMixin:
    """Timestamp tracking for create and update operations.

    Provides automatic tracking of when records are created and modified.
    Uses both Python-side defaults (for test environments) and database
    server defaults (for direct SQL inserts).

    Provides:
        created_at: Timestamp of record creation (immutable)
        updated_at: Timestamp of last modification (auto-updates)

    The timestamps are timezone-aware (UTC) and use server_default
    to ensure consistency even when records are created outside ORM.
    """

    __allow_unmapped__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp of record creation",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        comment="Timestamp of last update",
    )


class AuditColumnsMixin:
    """User audit tracking for create and update operations.

    Tracks WHO made changes to records. Requires application-level
    context to set user information (not automatically populated).

    Provides:
        created_by: User ID/email who created the record
        updated_by: User ID/email who last modified the record

    Usage:
            # In your repository or service:
        user = User(email="user@example.com")
        user.created_by = current_user.email
        session.add(user)
        await session.commit()

        # On update:
        user.name = "New Name"
        user.updated_by = current_user.email

    Note: These fields are nullable to support anonymous or system operations.
    """

    __allow_unmapped__ = True

    created_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="User who created this record",
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="User who last modified this record",
    )


class SoftDeleteMixin:
    """Soft delete support for logical (reversible) deletion.

    Instead of physically removing records from the database, sets
    a deleted_at timestamp. This allows:
    - Recovery of accidentally deleted data
    - Audit trails of deletions (including WHO deleted)
    - Maintaining referential integrity
    - Historical analysis including deleted records

    Provides:
        deleted_at: Timestamp of deletion (None if not deleted)
        deleted_by: User who performed the deletion
        is_deleted: Property to check if record is deleted

    Usage:
            # Soft delete with audit:
        user.deleted_at = datetime.now(UTC)
        user.deleted_by = current_user.email
        await session.commit()

        # Check if deleted:
        if user.is_deleted:
            print(f"User was deleted by {user.deleted_by}")

        # Query non-deleted records:
        stmt = select(User).where(User.deleted_at.is_(None))

        # Recover deleted record:
        user.deleted_at = None
        user.deleted_by = None
        await session.commit()

    Note: Queries must explicitly filter out soft-deleted records
    using `.where(Model.deleted_at.is_(None))` or use a query helper.
    The BaseRepository supports this via include_deleted parameter.
    """

    __allow_unmapped__ = True

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of soft deletion",
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="User who performed the soft deletion",
    )

    @property
    def is_deleted(self) -> bool:
        """Check if this record has been soft-deleted.

        Returns:
            True if deleted_at is set, False otherwise.
        """
        return self.deleted_at is not None


class TenantMixin:
    """Multi-tenancy support for tenant-scoped data isolation.

    Provides tenant association for models that need to be isolated
    per tenant. All queries should include tenant_id filtering to
    prevent data leakage between tenants.

    Provides:
        tenant_id: String column (indexed for performance)

    Usage:
        class File(TimestampedBase, TenantMixin):
            __tablename__ = "files"
            name: Mapped[str] = mapped_column(String(255))

        # Query with tenant scope:
        stmt = select(File).where(File.tenant_id == current_tenant_id)

        # Create with tenant:
        file = File(name="doc.pdf", tenant_id=current_tenant_id)

    Note: Repositories and services should enforce tenant filtering.
    Consider using a TenantAwareRepository base class for automatic
    tenant scoping in queries.

    Design Notes:
        - No foreign key constraint: tenant_id can be any identifier
          (database ID, OIDC claim, external auth service ID, etc.)
        - Nullable: supports single-tenant mode (None = no tenant filtering)
        - Indexed: ensures efficient queries when filtering by tenant
        - Application-level validation: enforce tenant ownership in services
    """

    __allow_unmapped__ = True

    tenant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )


# ============================================================================
# Convenience Base Classes (Common Combinations)
# ============================================================================


class TimestampedBase(Base, IntegerPKMixin, TimestampMixin):
    """Convenience base with integer PK and timestamps.

    Equivalent to the original TimestampedBase from the legacy infra database module.
    Provided for backward compatibility and common use case.

    Example:
            class User(TimestampedBase):
            __tablename__ = "users"
            email: Mapped[str] = mapped_column(String(255), unique=True)
    """

    __abstract__ = True


class UUIDTimestampedBase(Base, UUIDPKMixin, TimestampMixin):
    """Convenience base with UUID PK and timestamps.

    Recommended for new models in distributed systems or
    when you need non-sequential, globally unique IDs.

    Example:
            class Document(UUIDTimestampedBase):
            __tablename__ = "documents"
            title: Mapped[str] = mapped_column(String(255))
    """

    __abstract__ = True


class AuditedBase(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin):
    """Convenience base with full audit trail.

    Includes integer PK, timestamps, and user tracking.
    Best for models where compliance or audit requirements exist.

    Example:
            class Transaction(AuditedBase):
            __tablename__ = "transactions"
            amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    """

    __abstract__ = True


__all__ = [
    "NAMING_CONVENTION",
    "AuditColumnsMixin",
    "AuditedBase",
    # Core base
    "Base",
    # Primary key mixins
    "IntegerPKMixin",
    "SoftDeleteMixin",
    # Multi-tenancy
    "TenantMixin",
    # Audit mixins
    "TimestampMixin",
    # Convenience bases
    "TimestampedBase",
    "UUIDPKMixin",
    "UUIDTimestampedBase",
]
