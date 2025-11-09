"""Router registry and setup."""
from __future__ import annotations

from typing import TYPE_CHECKING

from example_service.features.items.router import router as items_router
from example_service.features.status.router import router as status_router

if TYPE_CHECKING:
    from fastapi import FastAPI


def setup_routers(app: FastAPI) -> None:
    """Register all feature routers with the application.

    Args:
        app: FastAPI application instance.
    """
    # Include feature routers
    app.include_router(status_router, prefix="/api/v1")
    app.include_router(items_router, prefix="/api/v1")

    # TODO: Add more feature routers here
    # app.include_router(users_router, prefix="/api/v1")
