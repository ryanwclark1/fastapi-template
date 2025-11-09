"""Custom logging formatters."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter with UTC timestamps.

    Formats log records as JSON Lines (JSONL) for machine parsing
    and log aggregation systems like Loki.

    Example output:
        ```json
        {"timestamp": "2025-01-01T00:00:00.123Z", "level": "INFO", "logger": "app.api", "message": "Request received"}
        ```
    """

    def __init__(
        self,
        fmt_keys: dict[str, str] | None = None,
        static: dict[str, Any] | None = None,
    ) -> None:
        """Initialize JSON formatter.

        Args:
            fmt_keys: Mapping of output keys to LogRecord attributes.
            static: Static fields to include in every log record.
        """
        super().__init__()
        self.fmt_keys = fmt_keys or {
            "level": "levelname",
            "logger": "name",
            "message": "message",
        }
        self.static = static or {}

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string.

        Args:
            record: Log record to format.

        Returns:
            JSON string representation of log record.
        """
        # Build data dict from format keys
        data: dict[str, Any] = {
            k: getattr(record, v, None) for k, v in self.fmt_keys.items()
        }

        # Add UTC timestamp in ISO format with 'Z' suffix
        ts = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        data["timestamp"] = ts

        # Add exception info if present
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        # Add static fields
        if self.static:
            data.update(self.static)

        # Add extra fields from LogRecord
        # Skip built-in attributes
        skip_keys = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "taskName",
        }

        for key, value in record.__dict__.items():
            if key not in skip_keys and key not in data:
                data[key] = value

        return json.dumps(data, ensure_ascii=False, default=str)
