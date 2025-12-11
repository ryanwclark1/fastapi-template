# Database Base Classes Migration Guide

## Overview

The `example_service.core.database.base` module provides composable mixins and convenience base classes for SQLAlchemy models. This guide explains which base class to use and how to migrate existing models.

## Quick Reference

### For New Models

```python
# ✅ DEFAULT CHOICE: UUID v7 with timestamps
from example_service.core.database.base import UUIDv7TimestampedBase

class MyModel(UUIDv7TimestampedBase):
    __tablename__ = "my_models"
    name: Mapped[str] = mapped_column(String(255))
```

### Base Class Decision Tree

```
Need user audit tracking (created_by/updated_by)?
├─ Yes, with Integer User IDs
│  └─ Use: UUIDv7TimestampedBase + UserAuditMixin
│
└─ No user tracking needed
   ├─ Need UUIDs? (distributed, security, microservices)
   │  ├─ Need time-sortable UUIDs?
   │  │  └─ Yes → UUIDv7TimestampedBase (RECOMMENDED)
   │  └─ No → UUIDTimestampedBase
   │
   └─ Keep Integer PKs? (simple app, legacy compatibility)
      └─ TimestampedBase
```

## Available Base Classes

### UUID-Based (Recommended for New Models)

#### 1. `UUIDv7TimestampedBase` ⭐ RECOMMENDED
**Best for:** Most new models

```python
class Agent(UUIDv7TimestampedBase):
    __tablename__ = "agents"
    name: Mapped[str] = mapped_column(String(255))
```

**Provides:**
- `id: Mapped[UUID]` - Time-sortable UUID v7
- `created_at: Mapped[datetime]`
- `updated_at: Mapped[datetime]`

**Benefits:**
- ✅ Sequential UUIDs (better B-tree performance)
- ✅ Can ORDER BY id chronologically
- ✅ Extract timestamp from UUID
- ✅ Distributed-safe, no ID enumeration

#### 2. `UUIDTimestampedBase`
**Best for:** When you need random UUIDs (security-critical)

```python
class Secret(UUIDTimestampedBase):
    __tablename__ = "secrets"
    value: Mapped[str] = mapped_column(Text)
```

**Provides:**
- `id: Mapped[UUID]` - Random UUID v4
- `created_at: Mapped[datetime]`
- `updated_at: Mapped[datetime]`

**Use when:** Truly random IDs needed (not time-sortable)

#### 3. `UUIDAuditedBase`
**Best for:** UUID models with full audit trail (string-based)

```python
class Transaction(UUIDAuditedBase):
    __tablename__ = "transactions"
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
```

**Provides:**
- `id: Mapped[UUID]` - Random UUID v4
- `created_at: Mapped[datetime]`
- `updated_at: Mapped[datetime]`
- `created_by: Mapped[str | None]` - Email/username string
- `updated_by: Mapped[str | None]`

**Note:** Uses strings, not FKs. For FK-based audit, use UserAuditMixin.

### Integer-Based (Legacy/Compatibility)

#### 4. `TimestampedBase`
**Best for:** Simple apps, legacy models

```python
class User(TimestampedBase):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
```

**Provides:**
- `id: Mapped[int]` - Auto-increment integer
- `created_at: Mapped[datetime]`
- `updated_at: Mapped[datetime]`

**Use for:** User, Post, and other legacy models

#### 5. `AuditedBase`
**Best for:** Integer PK + full audit trail

```python
class LegacyRecord(AuditedBase):
    __tablename__ = "legacy_records"
    data: Mapped[str] = mapped_column(Text)
```

**Provides:**
- `id: Mapped[int]`
- `created_at: Mapped[datetime]`
- `updated_at: Mapped[datetime]`
- `created_by: Mapped[str | None]`
- `updated_by: Mapped[str | None]`

## Mixins for Advanced Composition

### UserAuditMixin ⭐ NEW
**For models needing FK-based user tracking**

```python
from example_service.core.database.base import UUIDv7TimestampedBase, UserAuditMixin
from sqlalchemy.orm import relationship

class Document(UUIDv7TimestampedBase, UserAuditMixin):
    __tablename__ = "documents"
    title: Mapped[str] = mapped_column(String(255))

    # Relationships (optional)
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_id]
    )
    updated_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[updated_by_id]
    )
```

**Provides:**
- `created_by_id: Mapped[int | None]` - FK to users.id
- `updated_by_id: Mapped[int | None]` - FK to users.id

**Important:** Assumes User model has Integer PK (from TimestampedBase).

### TenantMixin
**For multi-tenant data isolation**

```python
class File(UUIDv7TimestampedBase, TenantMixin):
    __tablename__ = "files"
    name: Mapped[str] = mapped_column(String(255))
```

**Provides:**
- `tenant_id: Mapped[str | None]` - Indexed for performance

### SoftDeleteMixin
**For reversible deletion**

```python
class Post(UUIDv7TimestampedBase, SoftDeleteMixin):
    __tablename__ = "posts"
    content: Mapped[str] = mapped_column(Text)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
```

**Provides:**
- `deleted_at: Mapped[datetime | None]`
- `deleted_by: Mapped[str | None]`
- `is_deleted` property

## Migration Patterns

### Pattern 1: Manual UUID PK → UUIDv7TimestampedBase

```python
# BEFORE:
class Agent(Base):
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255))

# AFTER:
class Agent(UUIDv7TimestampedBase):
    __tablename__ = "agents"
    name: Mapped[str] = mapped_column(String(255))
```

**Steps:**
1. Change base class from `Base` to `UUIDv7TimestampedBase`
2. Remove manual `id`, `created_at`, `updated_at` declarations
3. Create alembic migration to change UUID v4 → v7 (optional, breaking change)

### Pattern 2: Add User Audit Tracking

```python
# BEFORE:
class Agent(UUIDv7TimestampedBase):
    __tablename__ = "agents"
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
    )

# AFTER:
class Agent(UUIDv7TimestampedBase, UserAuditMixin):
    __tablename__ = "agents"
    # created_by_id and updated_by_id automatically provided!
```

### Pattern 3: Mixin Composition → Convenience Base

```python
# BEFORE:
class FeatureFlag(Base, UUIDv7PKMixin, TimestampMixin):
    __tablename__ = "feature_flags"
    name: Mapped[str] = mapped_column(String(255))

# AFTER:
class FeatureFlag(UUIDv7TimestampedBase):
    __tablename__ = "feature_flags"
    name: Mapped[str] = mapped_column(String(255))
```

## Migration Checklist for Your Codebase

### Phase 1: Low-Hanging Fruit (No Migration Needed)
- [ ] `FeatureFlag(Base, UUIDv7PKMixin, TimestampMixin)` → `FeatureFlag(UUIDv7TimestampedBase)`
- [ ] `FlagOverride(Base, UUIDv7PKMixin, TimestampMixin)` → `FlagOverride(UUIDv7TimestampedBase)`
- [ ] `EventOutbox(Base, UUIDv7PKMixin, TimestampMixin)` → `EventOutbox(UUIDv7TimestampedBase)`

### Phase 2: Add UserAuditMixin (Update FK columns only)
- [ ] `Agent` - Add UserAuditMixin, remove manual FK declarations
- [ ] `AIJob` - Add UserAuditMixin
- [ ] `TenantAIConfig` - Add UserAuditMixin

### Phase 3: Manual UUID PKs → UUIDv7TimestampedBase (26 models)
Requires migration to change `uuid.uuid4` → `uuid7()`
- [ ] Review all 26 models with manual UUID declarations
- [ ] Create migration for UUID v4 → v7 conversion
- [ ] Update model definitions

### Phase 4: Legacy Models (Keep as TimestampedBase)
**DO NOT CHANGE** - these are stable:
- ✅ `User(TimestampedBase)` - Core model, many FKs
- ✅ `Post(TimestampedBase)` - Example model
- ✅ `Webhook(TimestampedBase, TenantMixin)` - Stable
- ✅ 11 more legacy models

## Best Practices

### 1. Always Specify __tablename__
```python
class MyModel(UUIDv7TimestampedBase):
    __tablename__ = "my_models"  # ✅ Explicit
    # Not relying on auto-generated name
```

### 2. Use Type Annotations Consistently
```python
class Agent(UUIDv7TimestampedBase):
    name: Mapped[str] = mapped_column(String(255))  # ✅ Typed
    # Not: name = Column(String(255))  # ❌ Old style
```

### 3. Add Relationships When Using UserAuditMixin
```python
class Document(UUIDv7TimestampedBase, UserAuditMixin):
    __tablename__ = "documents"

    # ✅ Makes queries easier
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_id]
    )
```

### 4. Document Non-Standard Choices
```python
class Secret(UUIDTimestampedBase):  # UUID v4 (not v7)
    """Uses random UUIDs to prevent timing attacks.

    Note: Intentionally using UUID v4 instead of v7 to avoid
    time-based correlation in security-sensitive data.
    """
    __tablename__ = "secrets"
```

## Summary

**For 90% of new models, use:**
```python
class MyModel(UUIDv7TimestampedBase):
    __tablename__ = "my_models"
    # Your fields here
```

**If you need user tracking:**
```python
class MyModel(UUIDv7TimestampedBase, UserAuditMixin):
    __tablename__ = "my_models"
    # Your fields here
```

**Keep using `TimestampedBase` for:**
- Existing models with many foreign key references
- When explicitly wanting integer PKs
