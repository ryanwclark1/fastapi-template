"""Base service class for business logic."""

from __future__ import annotations

import logging
from abc import ABC


class BaseService(ABC):
    """Base class for all service classes.

    Provides common functionality like logging and error handling
    for business logic services.

    Example:
            class UserService(BaseService):
            def __init__(self, repository: UserRepository):
                super().__init__()
                self.repository = repository

            async def get_user(self, user_id: str) -> User:
                self.logger.info("Fetching user", extra={"user_id": user_id})
                return await self.repository.find(user_id)
    """

    def __init__(self):
        """Initialize base service with logger."""
        self.logger = logging.getLogger(self.__class__.__name__)
