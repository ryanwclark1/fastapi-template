"""Shared middleware constants."""

# Paths exempt from rate limiting, request logging, and other middleware processing
# These paths are typically for health checks, metrics, and API documentation
EXEMPT_PATHS = [
    "/health",
    "/health/",
    "/health/ready",
    "/health/live",
    "/health/startup",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
]
