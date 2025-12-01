"""Strawberry extensions for the GraphQL schema.

Provides:
- Query depth limiting (max depth=10)
- OpenTelemetry tracing integration
"""

from __future__ import annotations

import logging

from strawberry.extensions import QueryDepthLimiter

logger = logging.getLogger(__name__)

# Maximum query depth to prevent deeply nested queries
MAX_QUERY_DEPTH = 10


def get_extensions() -> list:
    """Get list of Strawberry extensions for the schema.

    Returns:
        List of extension instances
    """
    extensions = [
        # Limit query depth to prevent abuse
        QueryDepthLimiter(max_depth=MAX_QUERY_DEPTH),
    ]

    logger.debug(f"GraphQL extensions configured: depth limit={MAX_QUERY_DEPTH}")
    return extensions


__all__ = ["get_extensions", "MAX_QUERY_DEPTH"]
