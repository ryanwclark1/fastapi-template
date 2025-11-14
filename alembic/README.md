# Alembic Database Migrations

This directory contains database migration scripts for managing schema changes using Alembic with **psycopg** (psycopg3) as the PostgreSQL driver.

## Quick Start

### 1. Create Initial Migration

Generate the first migration based on your models:

```bash
# Auto-generate migration from models
alembic revision --autogenerate -m "initial migration"

# Review the generated migration file in alembic/versions/
# Make any necessary adjustments
```

### 2. Apply Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Apply a specific migration
alembic upgrade <revision_id>

# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision_id>
```

### 3. Check Migration Status

```bash
# Show current database version
alembic current

# Show migration history
alembic history --verbose

# Show pending migrations
alembic heads
```

## psycopg Integration

This template uses **psycopg (psycopg3)** instead of asyncpg. The connection string format is:

```
postgresql+psycopg://user:password@host:port/database
```

### Configuration

Alembic is configured to use async operations with psycopg through SQLAlchemy's async engine:

- **Driver**: `postgresql+psycopg://` (SQLAlchemy dialect for psycopg)
- **Pool**: `NullPool` (Alembic creates temporary connections)
- **Async**: Uses `async_engine_from_config` for async operations

### Environment Variables

Set your database URL:

```bash
# .env file
DB_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/example_service
```

Alembic automatically reads this from settings (see `alembic/env.py:29`).

## Example Models

The template includes two example models to demonstrate the pattern:

### User Model

```python
from example_service.core.models import User

# UUID primary key
# Email (unique, indexed)
# Password (hashed)
# Profile fields (name, avatar)
# Status flags (active, verified, superuser)
# Timestamps (created_at, updated_at)
```

### Product Model

```python
from example_service.core.models import Product

# UUID primary key
# Product info (name, description, SKU)
# Pricing (Decimal for currency)
# Inventory (stock count)
# Foreign key to User (owner_id)
# Timestamps (created_at, updated_at)
```

## Common Workflows

### Creating a New Model

1. **Create model file** in `example_service/core/models/`:

```python
# example_service/core/models/order.py
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from example_service.infra.database.base import TimestampedBase

class Order(TimestampedBase):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    user: Mapped["User"] = relationship("User")
```

2. **Export model** in `example_service/core/models/__init__.py`:

```python
from .order import Order

__all__ = ["User", "Product", "Order"]
```

3. **Import in Alembic** (already configured in `alembic/env.py`):

```python
from example_service.core.models import User, Product, Order  # Add Order
```

4. **Generate migration**:

```bash
alembic revision --autogenerate -m "add order model"
```

5. **Review and apply**:

```bash
# Review the generated file
cat alembic/versions/<revision>_add_order_model.py

# Apply migration
alembic upgrade head
```

### Modifying an Existing Model

1. **Edit the model** (e.g., add a field):

```python
class User(TimestampedBase):
    # ... existing fields ...

    phone_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="User phone number",
    )
```

2. **Generate migration**:

```bash
alembic revision --autogenerate -m "add phone number to user"
```

3. **Review the generated migration**:

```python
# alembic/versions/xxx_add_phone_number_to_user.py
def upgrade():
    op.add_column('users', sa.Column('phone_number', sa.String(20), nullable=True))

def downgrade():
    op.drop_column('users', 'phone_number')
```

4. **Apply**:

```bash
alembic upgrade head
```

### Data Migrations

For data migrations (not just schema), create an empty revision:

```bash
alembic revision -m "migrate user data"
```

Edit the generated file:

```python
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Use op.execute() for data changes
    op.execute(
        "UPDATE users SET is_verified = true WHERE created_at < '2024-01-01'"
    )

def downgrade():
    # Reverting data changes is often not possible
    pass
```

## Best Practices

### 1. Always Review Auto-Generated Migrations

Alembic's autogenerate is smart but not perfect:

- Review each migration before applying
- Check for missing operations (renames, complex changes)
- Verify downgrade logic works correctly

### 2. Use Transactions

All migrations run in a transaction by default. For large data migrations:

```python
def upgrade():
    # Use batch operations for large datasets
    op.execute("UPDATE users SET status = 'active' WHERE status IS NULL")
```

### 3. Test Migrations

Always test migrations:

```bash
# Test upgrade
alembic upgrade head

# Test downgrade
alembic downgrade -1

# Test re-upgrade
alembic upgrade head
```

### 4. Version Control

- Commit migration files to git
- Never edit applied migrations (create a new one)
- Keep migrations small and focused

### 5. Production Deployments

```bash
# Before deployment, check for pending migrations
alembic current
alembic heads

# Apply migrations during deployment
alembic upgrade head

# Or use a pre-deployment script
python -m alembic upgrade head
```

## Troubleshooting

### "Target database is not up to date"

```bash
# Check current version
alembic current

# Check history
alembic history

# Stamp database to specific revision if needed
alembic stamp head
```

### "Can't locate revision identified by 'xxx'"

Migration file is missing. Check:

1. All migration files are in `alembic/versions/`
2. Files are properly formatted
3. Git hasn't excluded migration files

### Connection Issues

Ensure your database URL is correct:

```bash
# Test connection
python -c "from example_service.core.settings import settings; print(settings.database_url)"

# Check alembic can connect
alembic current
```

## Advanced Usage

### Multiple Database Branches

```bash
# Create a branch
alembic revision -m "feature branch" --branch-label feature

# Merge branches
alembic merge -m "merge feature" <rev1> <rev2>
```

### Custom Revision Template

Edit `alembic/script.py.mako` to customize migration templates.

### Offline Migrations

Generate SQL instead of applying:

```bash
alembic upgrade head --sql > migration.sql
```

## Integration with psycopg Native Pool

If you're using the psycopg native pool (`psycopg_pool`), Alembic still uses SQLAlchemy's engine. This is by design:

- **Alembic**: Uses SQLAlchemy with psycopg for migrations
- **Application**: Can use either SQLAlchemy pool OR psycopg native pool
- **Both**: Use the same psycopg driver under the hood

No conflicts - they work together seamlessly!

## Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [psycopg Documentation](https://www.psycopg.org/psycopg3/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
