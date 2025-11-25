# Database Quick Reference

Quick copy-paste examples for common database patterns.

## Import Statements

```python
# Base classes and mixins
from example_service.core.database import (
    Base,
    IntegerPKMixin,
    UUIDPKMixin,
    TimestampMixin,
    AuditColumnsMixin,
    SoftDeleteMixin,
    TimestampedBase,        # Convenience: Integer PK + Timestamps
    UUIDTimestampedBase,    # Convenience: UUID PK + Timestamps
    AuditedBase,            # Convenience: Integer PK + Timestamps + Audit
)

# Repository
from example_service.core.database import (
    BaseRepository,
    SearchResult,
    NotFoundError,
    RepositoryError,
)

# Existing repository
from example_service.core.repositories import UserRepository
```

## Model Definitions

### Simple Model (Integer PK + Timestamps)
```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from example_service.core.database import TimestampedBase

class Product(TimestampedBase):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
```

### UUID Model
```python
from example_service.core.database import UUIDTimestampedBase

class Document(UUIDTimestampedBase):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
```

### Model with Audit Trail
```python
from example_service.core.database import (
    Base,
    IntegerPKMixin,
    TimestampMixin,
    AuditColumnsMixin,
)

class Transaction(Base, IntegerPKMixin, TimestampMixin, AuditColumnsMixin):
    __tablename__ = "transactions"

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # Automatically has:
    # - id (integer PK)
    # - created_at, updated_at
    # - created_by, updated_by
```

### Model with Soft Delete
```python
from example_service.core.database import (
    Base,
    IntegerPKMixin,
    TimestampMixin,
    SoftDeleteMixin,
)

class Comment(Base, IntegerPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "comments"

    text: Mapped[str] = mapped_column(Text)

    # Has: id, created_at, updated_at, deleted_at, is_deleted
```

## Repository Creation

### Generic Repository (No Custom Methods)
```python
from example_service.core.database import BaseRepository
from example_service.core.models.product import Product

# Direct instantiation
product_repo = BaseRepository(Product, session)
```

### Custom Repository
```python
# core/repositories/product.py
from sqlalchemy import select
from example_service.core.database import BaseRepository
from example_service.core.models.product import Product

class ProductRepository(BaseRepository[Product]):
    def __init__(self, session: AsyncSession):
        super().__init__(Product, session)

    async def find_by_name(self, name: str) -> Product | None:
        stmt = select(Product).where(Product.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_in_price_range(
        self,
        min_price: Decimal,
        max_price: Decimal,
    ) -> list[Product]:
        stmt = select(Product).where(
            Product.price >= min_price,
            Product.price <= max_price,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
```

## Dependency Injection

### Repository DI Function
```python
# core/dependencies/repositories.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from example_service.core.dependencies.database import get_db_session
from example_service.core.repositories.product import ProductRepository

async def get_product_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ProductRepository:
    return ProductRepository(session)
```

### Using in Endpoint
```python
from fastapi import APIRouter, Depends
from example_service.core.repositories.product import ProductRepository
from example_service.core.dependencies.repositories import get_product_repository

router = APIRouter()

@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    product_repo: ProductRepository = Depends(get_product_repository),
):
    product = await product_repo.get_by_id(product_id)
    return {"id": product.id, "name": product.name}
```

## CRUD Operations

### Create
```python
product = Product(name="Widget", price=Decimal("19.99"))
product = await repo.create(product)
print(product.id)  # Auto-generated
```

### Read
```python
# Get by ID (raises NotFoundError if not found)
product = await repo.get_by_id(123)

# Get by ID (returns None if not found)
product = await repo.get(123)
if product is None:
    print("Not found")
```

### Update
```python
product = await repo.get_by_id(123)
product.price = Decimal("24.99")
product = await repo.update(product)
```

### Delete
```python
product = await repo.get_by_id(123)
await repo.delete(product)
```

### Soft Delete
```python
# Soft delete (model must have SoftDeleteMixin)
product = await repo.soft_delete(product)
print(product.is_deleted)  # True

# Restore
product = await repo.restore(product)
print(product.is_deleted)  # False
```

## Querying

### List All
```python
products = await repo.list_all()
for product in products:
    print(product.name)
```

### Pagination
```python
result = await repo.search(limit=10, offset=20)

print(f"Page {result.page} of {result.total_pages}")
print(f"Total items: {result.total}")
print(f"Has next: {result.has_next}")

for product in result.items:
    print(product.name)
```

### Filtering
```python
# Build filter
stmt = select(Product).where(Product.price < 50)

# Execute with pagination
result = await repo.search(
    filters=stmt,
    limit=10,
    offset=0,
)
```

### Sorting
```python
result = await repo.search(
    order_by=[Product.created_at.desc()],
    limit=10,
)
```

### Eager Loading
```python
from sqlalchemy.orm import selectinload

user = await user_repo.get_by_id(
    123,
    options=[selectinload(User.posts)]
)
# user.posts is now loaded, no additional query
```

## Error Handling

### Not Found
```python
from example_service.core.database import NotFoundError
from fastapi import HTTPException

try:
    product = await repo.get_by_id(999)
except NotFoundError:
    raise HTTPException(status_code=404, detail="Product not found")
```

### Repository Error
```python
from example_service.core.database import RepositoryError

try:
    product = await repo.create(product)
except RepositoryError as e:
    print(f"Error: {e.message}")
    print(f"Details: {e.details}")
```

## Feature Service Pattern

### Service with Multiple Repos
```python
# features/orders/service.py
from example_service.core.services.base import BaseService

class OrderService(BaseService):
    def __init__(
        self,
        order_repo: OrderRepository,
        product_repo: ProductRepository,
        user_repo: UserRepository,
    ):
        self.order_repo = order_repo
        self.product_repo = product_repo
        self.user_repo = user_repo

    async def create_order(
        self,
        user_id: int,
        product_ids: list[int],
    ) -> Order:
        # Validate user
        user = await self.user_repo.get_by_id(user_id)

        # Validate products
        products = []
        for pid in product_ids:
            product = await self.product_repo.get_by_id(pid)
            products.append(product)

        # Calculate total
        total = sum(p.price for p in products)

        # Create order
        order = Order(user_id=user_id, total=total)
        order = await self.order_repo.create(order)

        return order
```

### Service DI
```python
# core/dependencies/services.py
async def get_order_service(
    order_repo: OrderRepository = Depends(get_order_repository),
    product_repo: ProductRepository = Depends(get_product_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> OrderService:
    return OrderService(order_repo, product_repo, user_repo)
```

### Using Service in Endpoint
```python
@router.post("/orders")
async def create_order(
    data: OrderCreate,
    order_service: OrderService = Depends(get_order_service),
    current_user: User = Depends(get_current_user),
):
    order = await order_service.create_order(
        user_id=current_user.id,
        product_ids=data.product_ids,
    )
    return OrderSchema.from_orm(order)
```

## Testing

### Repository Test
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from example_service.core.repositories import ProductRepository
from example_service.core.models.product import Product

@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_create_product(session):
    repo = ProductRepository(session)

    product = Product(name="Test", price=Decimal("10.00"))
    created = await repo.create(product)

    assert created.id is not None
    assert created.name == "Test"
```

### Mock Repository Test
```python
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_order_service():
    # Mock repositories
    order_repo = AsyncMock(spec=OrderRepository)
    product_repo = AsyncMock(spec=ProductRepository)
    user_repo = AsyncMock(spec=UserRepository)

    # Setup mock responses
    user_repo.get_by_id.return_value = User(id=1)
    product_repo.get_by_id.return_value = Product(id=1, price=Decimal("10.00"))

    # Test service
    service = OrderService(order_repo, product_repo, user_repo)
    order = await service.create_order(user_id=1, product_ids=[1])

    assert order_repo.create.called
```

## Common Patterns

### Search Endpoint
```python
@router.get("/products")
async def search_products(
    name: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    page: int = 1,
    page_size: int = 20,
    repo: ProductRepository = Depends(get_product_repository),
):
    # Build filters
    stmt = select(Product)
    if name:
        stmt = stmt.where(Product.name.ilike(f"%{name}%"))
    if min_price:
        stmt = stmt.where(Product.price >= min_price)
    if max_price:
        stmt = stmt.where(Product.price <= max_price)

    # Paginate
    offset = (page - 1) * page_size
    result = await repo.search(
        filters=stmt,
        limit=page_size,
        offset=offset,
        order_by=[Product.created_at.desc()],
    )

    return {
        "items": [ProductSchema.from_orm(p) for p in result.items],
        "total": result.total,
        "page": result.page,
        "total_pages": result.total_pages,
    }
```

### Audit Trail
```python
# Model with audit columns
transaction = Transaction(amount=Decimal("100.00"))
transaction.created_by = current_user.email
await repo.create(transaction)

# On update
transaction.amount = Decimal("150.00")
transaction.updated_by = current_user.email
await repo.update(transaction)
```

### Soft Delete Filter
```python
# Only non-deleted
stmt = select(Product).where(Product.deleted_at.is_(None))
products = await repo.search(filters=stmt)

# Only deleted
stmt = select(Product).where(Product.deleted_at.is_not(None))
deleted_products = await repo.search(filters=stmt)
```
