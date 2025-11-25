"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from example_service.app.exception_handlers import configure_exception_handlers
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
        # Core metadata
        title=settings.title,
        summary=settings.summary,
        description=settings.description,
        version=settings.version,
        # API info (OpenAPI)
        terms_of_service=settings.terms_of_service,
        contact=settings.get_contact(),
        license_info=settings.get_license_info(),
        # Documentation URLs
        docs_url=settings.get_docs_url(),
        redoc_url=settings.get_redoc_url(),
        openapi_url=settings.get_openapi_url(),
        # OpenAPI configuration
        openapi_tags=settings.openapi_tags,
        servers=settings.servers,
        root_path=settings.root_path,
        root_path_in_servers=settings.root_path_in_servers,
        # Swagger UI
        swagger_ui_oauth2_redirect_url=settings.get_swagger_ui_oauth2_redirect_url(),
        swagger_ui_init_oauth=settings.swagger_ui_init_oauth,
        swagger_ui_parameters=settings.get_swagger_ui_parameters(),
        # Behavioral settings
        debug=settings.debug,
        redirect_slashes=settings.redirect_slashes,
        separate_input_output_schemas=settings.separate_input_output_schemas,
        # Lifecycle
        lifespan=lifespan,
    )

    # Configure exception handlers (must be before middleware)
    configure_exception_handlers(app)

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
