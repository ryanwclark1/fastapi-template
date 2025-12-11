"""Core database package with composable base classes, mixins, and repository.

This package provides a flexible foundation for database models with
both direct SQLAlchemy usage and an optional thin repository layer.
Use whichever approach fits your needs - or mix them.

Base Classes and Mixins:
    - Base: Enhanced declarative base with auto table naming
    - IntegerPKMixin, UUIDPKMixin, UUIDv7PKMixin: Flexible primary key strategies
    - TimestampMixin: created_at, updated_at tracking
    - AuditColumnsMixin: created_by, updated_by tracking
    - SoftDeleteMixin: Soft delete support with deleted_at
    - HierarchicalMixin: Tree navigation for models with ltree paths

Convenience Bases:
    - TimestampedBase: Integer PK + timestamps (backward compatible)
    - UUIDTimestampedBase: UUID PK + timestamps
    - AuditedBase: Integer PK + timestamps + audit columns

Repository:
    - BaseRepository[T]: Generic CRUD with explicit session passing
    - TenantAwareRepository[T]: BaseRepository with optional multi-tenancy support
    - SearchResult[T]: Paginated result container

Query Filters:
    - SearchFilter: Multi-field text search with LIKE/ILIKE
    - OrderBy: Column sorting (asc/desc)
    - LimitOffset: Pagination helper
    - CollectionFilter: WHERE ... IN clauses
    - BeforeAfter: Date range filtering
    - OnBeforeAfter: Inclusive date range filtering
    - FilterGroup: Combine multiple filters

UUID Utilities:
    - generate_uuid7: Generate time-sortable UUID v7
    - short_uuid: Convert UUID to URL-safe base64 string
    - parse_uuid: Parse UUID from various formats
    - uuid_to_timestamp: Extract timestamp from UUID v7

Change Tracking:
    - has_changes: Check if ORM instance has pending changes
    - is_loaded: Check if relationship is loaded without triggering load
    - get_changed_attributes: Get dict of changed attrs with old/new values
    - get_instance_state: Get human-readable state (pending, persistent, etc.)

Validation:
    - validate_identifier: Validate SQL identifiers against injection
    - safe_table_reference: Create safely quoted table references

Custom Types - Encryption:
    - EncryptedString: Transparent encryption for sensitive data
    - EncryptedText: Encrypted Text type for larger content

Custom Types - Validated:
    - EmailType: Validated email addresses with normalization
    - URLType: Validated URLs with scheme enforcement
    - PhoneNumberType: International phone numbers in E.164 format

Custom Types - Hierarchical:
    - LtreeType: PostgreSQL ltree for hierarchical paths
    - LtreePath: Python wrapper for path manipulation

Custom Types - Ranges:
    - Range: Python representation of PostgreSQL ranges
    - DateRangeType, DateTimeRangeType: Date/datetime ranges
    - IntRangeType, NumericRangeType: Numeric ranges
    - range_contains, range_overlaps, etc.: Query helpers

Custom Types - Choices:
    - ChoiceType: SQLAlchemy type for labeled enums
    - LabeledStrEnum, LabeledIntEnum: Enums with human-readable labels
    - create_choices: Dynamic enum creation

Exceptions:
    - DatabaseError: Base exception for database operations
    - NotFoundError: Entity not found (404-like)
    - IdentifierValidationError: Invalid SQL identifier

Example (Repository approach):
    from example_service.core.database import BaseRepository, SearchResult
    from example_service.core.models import User

    class UserRepository(BaseRepository[User]):
        async def find_by_email(self, session, email: str) -> User | None:
            return await self.get_by(session, User.email, email)

    # Usage
    repo = UserRepository(User)
    user = await repo.get(session, user_id)

Example (Direct SQLAlchemy):
    from sqlalchemy import select
    from example_service.core.database import SearchFilter, OrderBy

    # Direct SQLAlchemy with filters - bypass repository when needed
    async def search_users(session: AsyncSession, query: str) -> list[User]:
        stmt = select(User)
        stmt = SearchFilter([User.name, User.email], query).apply(stmt)
        stmt = OrderBy(User.created_at, "desc").apply(stmt)

        result = await session.execute(stmt)
        return list(result.scalars().all())
"""

from __future__ import annotations

from example_service.core.database.admin_utils import (
    calculate_cache_hit_ratio,
    check_connection_limit,
    format_bytes,
    generate_confirmation_token,
    sanitize_query_text,
    validate_index_name,
    validate_table_name,
    verify_confirmation_token,
)
from example_service.core.database.base import (
    NAMING_CONVENTION,
    AuditColumnsMixin,
    AuditedBase,
    Base,
    IntegerPKMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampedBase,
    TimestampMixin,
    UUIDPKMixin,
    UUIDTimestampedBase,
    UUIDv7PKMixin,
    UUIDv7TimestampedBase,
)
from example_service.core.database.choices import (
    ChoiceType,
    LabeledChoiceMixin,
    LabeledIntEnum,
    LabeledStrEnum,
    create_choices,
    with_labels,
)
from example_service.core.database.exceptions import (
    DatabaseError,
    NotFoundError,
)
from example_service.core.database.filters import (
    BeforeAfter,
    CollectionFilter,
    FilterGroup,
    LimitOffset,
    OnBeforeAfter,
    OrderBy,
    SearchFilter,
    StatementFilter,
)
from example_service.core.database.hierarchy import (
    HierarchicalMixin,
    LtreePath,
)
from example_service.core.database.inspection import (
    get_changed_attributes,
    get_identity_key,
    get_instance_state,
    get_original_values,
    get_primary_key,
    has_changes,
    is_deleted,
    is_detached,
    is_loaded,
    is_modified,
    is_new,
    is_persistent,
)
from example_service.core.database.migration_helpers import (
    create_exclusion_constraint,
    create_extension,
    create_gist_index,
    create_gist_index_multi,
    create_ltree_indexes,
    create_no_overlap_constraint,
    drop_exclusion_constraint,
    drop_extension,
    drop_gist_index,
    drop_ltree_indexes,
    ensure_btree_gist,
)
from example_service.core.database.ranges import (
    DateRange,
    DateRangeType,
    DateTimeRangeType,
    DecimalRange,
    IntRange,
    IntRangeType,
    NumericRangeType,
    Range,
    TimestampRange,
    range_adjacent,
    range_contained_by,
    range_contains,
    range_left_of,
    range_overlaps,
    range_right_of,
)
from example_service.core.database.repository import (
    BaseRepository,
    SearchResult,
    TenantAwareRepository,
)
from example_service.core.database.types import (
    EmailType,
    EncryptedString,
    EncryptedText,
    LtreeType,
    PhoneNumberType,
    URLType,
    format_phone_international,
    format_phone_national,
)
from example_service.core.database.utils import (
    generate_uuid7,
    parse_uuid,
    short_uuid,
    uuid_to_timestamp,
)
from example_service.core.database.validation import (
    IdentifierValidationError,
    safe_table_reference,
    validate_identifier,
)
from example_service.infra.database.session import get_async_session

__all__ = [
    "NAMING_CONVENTION",
    "AuditColumnsMixin",
    "AuditedBase",
    "Base",
    "BaseRepository",
    "BeforeAfter",
    "ChoiceType",
    "CollectionFilter",
    "DatabaseError",
    "DateRange",
    "DateRangeType",
    "DateTimeRangeType",
    "DecimalRange",
    "EmailType",
    "EncryptedString",
    "EncryptedText",
    "FilterGroup",
    "HierarchicalMixin",
    "IdentifierValidationError",
    "IntRange",
    "IntRangeType",
    "IntegerPKMixin",
    "LabeledChoiceMixin",
    "LabeledIntEnum",
    "LabeledStrEnum",
    "LimitOffset",
    "LtreePath",
    "LtreeType",
    "NotFoundError",
    "NumericRangeType",
    "OnBeforeAfter",
    "OrderBy",
    "PhoneNumberType",
    "Range",
    "SearchFilter",
    "SearchResult",
    "SoftDeleteMixin",
    "StatementFilter",
    "TenantAwareRepository",
    "TenantMixin",
    "TimestampMixin",
    "TimestampRange",
    "TimestampedBase",
    "URLType",
    "UUIDPKMixin",
    "UUIDTimestampedBase",
    "UUIDv7PKMixin",
    "UUIDv7TimestampedBase",
    "calculate_cache_hit_ratio",
    "check_connection_limit",
    "create_choices",
    "create_exclusion_constraint",
    "create_extension",
    "create_gist_index",
    "create_gist_index_multi",
    "create_ltree_indexes",
    "create_no_overlap_constraint",
    "drop_exclusion_constraint",
    "drop_extension",
    "drop_gist_index",
    "drop_ltree_indexes",
    "ensure_btree_gist",
    "format_bytes",
    "format_phone_international",
    "format_phone_national",
    "generate_confirmation_token",
    "generate_uuid7",
    "get_async_session",
    "get_changed_attributes",
    "get_identity_key",
    "get_instance_state",
    "get_original_values",
    "get_primary_key",
    "has_changes",
    "is_deleted",
    "is_detached",
    "is_loaded",
    "is_modified",
    "is_new",
    "is_persistent",
    "parse_uuid",
    "range_adjacent",
    "range_contained_by",
    "range_contains",
    "range_left_of",
    "range_overlaps",
    "range_right_of",
    "safe_table_reference",
    "sanitize_query_text",
    "short_uuid",
    "uuid_to_timestamp",
    "validate_identifier",
    "validate_index_name",
    "validate_table_name",
    "verify_confirmation_token",
    "with_labels",
]
