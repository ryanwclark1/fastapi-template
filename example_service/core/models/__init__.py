"""Domain models for the application.

This module exports all SQLAlchemy ORM models used in the application.
Models are designed to work with psycopg through SQLAlchemy's async engine.

Import models from this module for use in your application:
    ```python
    from example_service.core.models import User, Product
    ```

For Alembic migrations, ensure models are imported in alembic/env.py:
    ```python
    from example_service.core.models import User, Product
    from example_service.infra.database.base import Base
    target_metadata = Base.metadata
    ```
"""

from __future__ import annotations

from .product import Product
from .user import User

__all__ = [
    "User",
    "Product",
]
