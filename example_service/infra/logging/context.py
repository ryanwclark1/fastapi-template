"""Structured logging utilities for observability.

This module provides utilities for structured logging that integrates
with the core logging infrastructure.
"""
from __future__ import annotations

import logging
from typing import Any


class ContextAdapter(logging.LoggerAdapter):
    """Logger adapter that adds context to all log messages.

    Automatically includes context like request_id, tenant_id, user_id
    in all log messages.

    Example:
        ```python
        base_logger = logging.getLogger("app.api")
        logger = ContextAdapter(base_logger, {
            "request_id": "r-123",
            "tenant": "acme"
        })
        logger.info("Processing request")
        # Output includes request_id and tenant fields
        ```
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Process log message and add context.

        Args:
            msg: Log message.
            kwargs: Keyword arguments for logging.

        Returns:
            Tuple of (message, kwargs) with context added to extra.
        """
        # Add context from adapter to extra
        ctx = {
            k: v
            for k, v in self.extra.items()
            if v is not None and k not in ("request_id", "tenant", "user_id")
        }

        # Add specific context fields
        if "request_id" in self.extra and self.extra["request_id"]:
            ctx["request_id"] = self.extra["request_id"]
        if "tenant" in self.extra and self.extra["tenant"]:
            ctx["tenant"] = self.extra["tenant"]
        if "user_id" in self.extra and self.extra["user_id"]:
            ctx["user_id"] = self.extra["user_id"]

        # Merge with existing extra
        kwargs.setdefault("extra", {}).update(ctx)
        return msg, kwargs


def get_logger(name: str, **context: Any) -> ContextAdapter:
    """Get logger with context.

    Args:
        name: Logger name.
        **context: Context to add to all log messages.

    Returns:
        Logger adapter with context.

    Example:
        ```python
        logger = get_logger(__name__, request_id="r-123", tenant="acme")
        logger.info("User logged in", extra={"user_id": "u-456"})
        ```
    """
    base_logger = logging.getLogger(name)
    return ContextAdapter(base_logger, context)
