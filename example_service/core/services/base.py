"""Base service class for business logic."""

from __future__ import annotations

import logging

from example_service.infra.logging import get_lazy_logger


class BaseService:
    """Base class for all service classes.

    Provides common functionality like logging and error handling
    for business logic services.

    Loggers:
        - self.logger: Standard logger for INFO/WARNING/ERROR (always evaluated)
        - self._lazy: Lazy logger for DEBUG (zero overhead when DEBUG disabled)

    Example:
            class UserService(BaseService):
            def __init__(self, repository: UserRepository):
                super().__init__()
                self.repository = repository

            async def get_user(self, user_id: str) -> User:
                self.logger.info("Fetching user", extra={"user_id": user_id})
                return await self.repository.find(user_id)

            async def complex_operation(self):
                # Use lazy logger for DEBUG with expensive string formatting
                self._lazy.debug(lambda: f"State: {expensive_computation()}")
    """

    def __init__(self) -> None:
        """Initialize base service with loggers."""
        class_name = self.__class__.__name__
        # Standard logger for INFO/WARNING/ERROR
        self.logger = logging.getLogger(class_name)
        # Lazy logger for DEBUG (zero overhead when DEBUG disabled)
        self._lazy = get_lazy_logger(class_name)
