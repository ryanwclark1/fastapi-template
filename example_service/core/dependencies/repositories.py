"""Dependency injection for repositories.

Provides FastAPI Depends() functions for injecting repository
instances into endpoints. Repositories automatically receive
the database session.

Example:
    ```python
    from fastapi import APIRouter, Depends
    from example_service.core.dependencies.repositories import get_user_repository
    from example_service.core.repositories import UserRepository

    router = APIRouter()

    @router.get("/users/{user_id}")
    async def get_user(
        user_id: int,
        user_repo: UserRepository = Depends(get_user_repository),
    ):
        user = await user_repo.get_by_id(user_id)
        return {"id": user.id, "email": user.email}
    ```
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.database import get_db_session
from example_service.core.repositories import UserRepository


async def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRepository:
    """Provide UserRepository instance.

    Args:
        session: Database session (injected automatically)

    Returns:
        UserRepository with active session

    Example:
        ```python
        @router.post("/users")
        async def create_user(
            data: UserCreate,
            repo: UserRepository = Depends(get_user_repository),
        ):
            user = User(**data.dict())
            user = await repo.create(user)
            return user
        ```
    """
    return UserRepository(session)


__all__ = [
    "get_user_repository",
]
