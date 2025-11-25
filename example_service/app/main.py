"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from example_service.app.lifespan import lifespan
from example_service.app.middleware import configure_middleware
from example_service.app.router import setup_routers
from example_service.core.settings import get_app_settings
from example_service.infra.tracing.opentelemetry import instrument_app


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Uses modular settings from core.settings for all configuration.
    Settings are loaded once and cached via LRU cache.

    Returns:
        Configured FastAPI application instance.
    """
    settings = get_app_settings()

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description="FastAPI service template following standard architecture patterns",
        debug=settings.debug,
        docs_url=settings.get_docs_url(),
        redoc_url=settings.get_redoc_url(),
        openapi_url=settings.get_openapi_url(),
        root_path=settings.root_path,
        lifespan=lifespan,
    )

    # Configure middleware (CORS, logging, etc.)
    configure_middleware(app)

    # Setup routers
    setup_routers(app)

    # Instrument FastAPI for OpenTelemetry tracing
    # This must be called after app creation but before serving requests
    instrument_app(app)

    return app


# Application instance for uvicorn
app = create_app()
