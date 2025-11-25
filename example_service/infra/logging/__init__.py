"""Logging infrastructure.

Provides structured logging with JSON formatting, async queue handling,
and context-aware logging adapters.
"""
from example_service.infra.logging.config import configure_logging
from example_service.infra.logging.context import ContextAdapter, get_logger
from example_service.infra.logging.formatters import JSONFormatter

__all__ = ["configure_logging", "ContextAdapter", "get_logger", "JSONFormatter"]
