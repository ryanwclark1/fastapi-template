"""User repository with custom query methods.

Demonstrates how to extend BaseRepository with model-specific
queries while maintaining the standard CRUD interface.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from example_service.core.database import BaseRepository
from example_service.core.models.user import User

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class UserRepository(BaseRepository[User]):
    """User-specific repository with custom query methods.

    Extends BaseRepository to add domain-specific queries like
    finding users by email, listing active users, etc.

    Inherits all standard CRUD operations:
    - get(id) / get_by_id(id)
    - create(user)
    - update(user)
    - delete(user)
    - search(filters, limit, offset)
    - list_all()

    Example:
        ```python
        # Using inherited methods
        user = await user_repo.get_by_id(123)
        user.full_name = "New Name"
        await user_repo.update(user)

        # Using custom methods
        user = await user_repo.find_by_email("user@example.com")
        active_users = await user_repo.find_active_users()
        ```
    """

    def __init__(self, session: AsyncSession):
        """Initialize user repository.

        Args:
            session: Async database session
        """
        super().__init__(User, session)

    # ========================================================================
    # Custom Query Methods
    # ========================================================================

    async def find_by_email(self, email: str) -> User | None:
        """Find user by email address.

        Args:
            email: User email address

        Returns:
            User if found, None otherwise

        Example:
            ```python
            user = await repo.find_by_email("john@example.com")
            if user:
                print(f"Found user: {user.username}")
            ```
        """
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_username(self, username: str) -> User | None:
        """Find user by username.

        Args:
            username: Username to search for

        Returns:
            User if found, None otherwise

        Example:
            ```python
            user = await repo.find_by_username("john_doe")
            ```
        """
        stmt = select(User).where(User.username == username)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_active_users(self) -> Sequence[User]:
        """Get all active users.

        Returns:
            List of active users (is_active=True)

        Example:
            ```python
            active_users = await repo.find_active_users()
            print(f"Active users: {len(active_users)}")
            ```
        """
        stmt = select(User).where(User.is_active == True)  # noqa: E712
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_superusers(self) -> Sequence[User]:
        """Get all superuser accounts.

        Returns:
            List of superusers (is_superuser=True)

        Example:
            ```python
            admins = await repo.find_superusers()
            ```
        """
        stmt = select(User).where(User.is_superuser == True)  # noqa: E712
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_with_posts(self, user_id: int) -> User | None:
        """Find user with posts eagerly loaded.

        Useful when you need to access user.posts without additional queries.

        Args:
            user_id: User ID

        Returns:
            User with posts loaded, or None if not found

        Example:
            ```python
            user = await repo.find_with_posts(123)
            if user:
                for post in user.posts:
                    print(post.title)
            ```
        """
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.posts))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def search_by_name(
        self,
        search_term: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ):
        """Search users by full name (case-insensitive partial match).

        Args:
            search_term: Search term to match against full_name
            limit: Maximum results per page
            offset: Number of results to skip

        Returns:
            SearchResult with matching users

        Example:
            ```python
            # Search for users with "john" in their name
            result = await repo.search_by_name("john", limit=10)
            for user in result.items:
                print(user.full_name)
            ```
        """
        ilike_term = f"%{search_term}%"
        stmt = select(User).where(User.full_name.ilike(ilike_term))

        return await self.search(
            filters=stmt,
            limit=limit,
            offset=offset,
            order_by=[User.created_at.desc()],
        )

    # ========================================================================
    # Business Logic Helpers
    # ========================================================================

    async def email_exists(self, email: str) -> bool:
        """Check if email is already registered.

        Args:
            email: Email address to check

        Returns:
            True if email exists, False otherwise

        Example:
            ```python
            if await repo.email_exists("new@example.com"):
                raise ValueError("Email already registered")
            ```
        """
        user = await self.find_by_email(email)
        return user is not None

    async def username_exists(self, username: str) -> bool:
        """Check if username is already taken.

        Args:
            username: Username to check

        Returns:
            True if username exists, False otherwise

        Example:
            ```python
            if await repo.username_exists("john_doe"):
                raise ValueError("Username already taken")
            ```
        """
        user = await self.find_by_username(username)
        return user is not None
