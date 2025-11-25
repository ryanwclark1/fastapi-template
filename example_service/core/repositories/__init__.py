"""Repository package for data access layer.

This package contains model-specific repositories that extend
BaseRepository with custom query methods.

Available Repositories:
    - UserRepository: User management with email/username lookups

Example:
    ```python
    from example_service.core.repositories import UserRepository

    user_repo = UserRepository(session)
    user = await user_repo.find_by_email("user@example.com")
    ```
"""
from __future__ import annotations

from example_service.core.repositories.user import UserRepository

__all__ = [
    "UserRepository",
]
