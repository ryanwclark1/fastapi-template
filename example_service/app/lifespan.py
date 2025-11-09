"""Application lifespan management."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from example_service.infra.logging.config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle.

    Handles startup and shutdown events for the application.

    Args:
        app: FastAPI application instance.

    Yields:
        None during application runtime.
    """
    # Startup
    configure_logging()
    logger.info("Application starting", extra={"service": "example-service"})

    # TODO: Initialize database connections
    # TODO: Initialize cache connections
    # TODO: Initialize message broker connections

    yield

    # Shutdown
    logger.info("Application shutting down", extra={"service": "example-service"})

    # TODO: Close database connections
    # TODO: Close cache connections
    # TODO: Close message broker connections
