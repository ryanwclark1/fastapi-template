"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from example_service.app.lifespan import lifespan
from example_service.app.middleware import configure_middleware
from example_service.app.router import setup_routers


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Example Service API",
        version="0.1.0",
        description="Service template following standard architecture",
        lifespan=lifespan,
    )

    # Configure middleware
    configure_middleware(app)

    # Setup routers
    setup_routers(app)

    return app


# Application instance for uvicorn
app = create_app()
