"""Product domain model."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import String, Numeric, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.infra.database.base import TimestampedBase


class Product(TimestampedBase):
    """Product model.

    Represents a product in the system with pricing and inventory information.
    Demonstrates foreign key relationships with User model.

    This model works seamlessly with psycopg through SQLAlchemy's async engine.

    Example:
        ```python
        from example_service.core.models import User, Product
        from example_service.infra.database.session import get_async_session
        from decimal import Decimal

        async with get_async_session() as session:
            # Create product for a user
            product = Product(
                name="Wireless Mouse",
                description="Ergonomic wireless mouse with USB receiver",
                price=Decimal("29.99"),
                stock=100,
                owner_id=user.id,
            )
            session.add(product)
            await session.commit()

            # Query products with owner
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(Product)
                .where(Product.stock > 0)
                .options(selectinload(Product.owner))
            )
            in_stock_products = result.scalars().all()

            for product in in_stock_products:
                print(f"{product.name} owned by {product.owner.email}")
        ```
    """

    __tablename__ = "products"

    # Primary key (UUID)
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="Unique product identifier (UUID)",
    )

    # Product information
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Product name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Detailed product description",
    )
    sku: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        index=True,
        comment="Stock Keeping Unit (unique product code)",
    )

    # Pricing and inventory
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Product price (2 decimal places)",
    )
    stock: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="Current stock quantity",
    )

    # Foreign key to User
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who owns/created this product",
    )

    # Relationships
    owner: Mapped["User"] = relationship(
        "User",
        back_populates="products",
    )

    def __repr__(self) -> str:
        """String representation of Product."""
        return f"<Product(id={self.id}, name={self.name}, price={self.price})>"

    @property
    def is_in_stock(self) -> bool:
        """Check if product is in stock."""
        return self.stock > 0
