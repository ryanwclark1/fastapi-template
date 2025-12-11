"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from example_service.app.docs import configure_documentation
from example_service.app.exception_handlers import configure_exception_handlers
from example_service.app.lifespan import lifespan
from example_service.app.middleware import configure_middleware
from example_service.app.router import setup_routers
from example_service.core.settings import (
    get_graphql_settings,
    get_settings,
    get_websocket_settings,
)
from example_service.infra.tracing.opentelemetry import instrument_app


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Uses unified settings from core.settings for all configuration.
    Settings are loaded once and cached via LRU cache.

    Returns:
        Configured FastAPI application instance.
    """
    settings = get_settings()
    app_settings = settings.app

    app = FastAPI(
        # Core metadata
        title=app_settings.title,
        summary=app_settings.summary,
        description=app_settings.description,
        version=app_settings.version,
        # Documentation URLs
        docs_url=None,
        redoc_url=None,
        openapi_url=app_settings.get_openapi_url(),
        # OpenAPI configuration
        openapi_tags=app_settings.openapi_tags,
        servers=app_settings.servers,
        root_path=app_settings.root_path,
        root_path_in_servers=app_settings.root_path_in_servers,
        # Swagger UI
        swagger_ui_oauth2_redirect_url=None,
        swagger_ui_init_oauth=None,
        swagger_ui_parameters=None,
        # Behavioral settings
        debug=app_settings.debug,
        redirect_slashes=app_settings.redirect_slashes,
        separate_input_output_schemas=app_settings.separate_input_output_schemas,
        # Lifecycle
        lifespan=lifespan,
    )

    # Configure exception handlers (must be before middleware)
    configure_exception_handlers(app)

    # Serve documentation with CSP-friendly assets
    configure_documentation(app, app_settings)

    # Configure middleware (centralized configuration with proper ordering)
    configure_middleware(app, settings)

    # Setup routers
    graphql_settings = get_graphql_settings()
    websocket_settings = get_websocket_settings()
    setup_routers(app, app_settings, graphql_settings, websocket_settings)

    # Instrument FastAPI for OpenTelemetry tracing
    # This must be called after app creation but before serving requests
    instrument_app(app)

    return app


# Application instance for uvicorn
app = create_app()
