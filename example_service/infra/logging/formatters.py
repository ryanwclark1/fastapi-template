"""Custom logging formatters with trace correlation."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace


class JSONFormatter(logging.Formatter):
    """Structured JSON Lines (JSONL) formatter with UTC timestamps.

    Formats log records as JSON Lines (JSONL) - one JSON object per line,
    ready for ingestion by log aggregation systems like Loki, Elasticsearch,
    or CloudWatch Logs Insights.

    Features:
    - UTC timestamps in ISO 8601 format with millisecond precision
    - OpenTelemetry trace correlation (trace_id, span_id)
    - Automatic inclusion of context from ContextInjectingFilter
    - Optional process/thread information
    - Exception stack traces in structured format
    - No newlines in JSON (ensures valid JSONL)

    Example output:
        ```json
        {"timestamp": "2025-01-01T00:00:00.123Z", "level": "INFO", "logger": "app.api", "message": "Request received", "request_id": "abc-123"}
        ```

    Loki label extraction:
        Configure Loki to extract fields as labels:
        ```yaml
        - json:
            expressions:
              level: level
              service: service
              logger: logger
        - labels:
            level:
            service:
            logger:
        ```
    """

    def __init__(
        self,
        fmt_keys: dict[str, str] | None = None,
        static: dict[str, Any] | None = None,
        include_process_info: bool = False,
        include_thread_info: bool = False,
    ) -> None:
        """Initialize JSON formatter.

        Args:
            fmt_keys: Mapping of output keys to LogRecord attributes.
                Default: {"level": "levelname", "logger": "name", "message": "message"}
            static: Static fields to include in every log record (e.g., {"service": "api"}).
            include_process_info: Include process ID and name.
            include_thread_info: Include thread ID and name.
        """
        super().__init__()
        self.fmt_keys = fmt_keys or {
            "level": "levelname",
            "logger": "name",
            "message": "message",
        }
        self.static = static or {}
        self.include_process_info = include_process_info
        self.include_thread_info = include_thread_info

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string with trace correlation.

        Args:
            record: Log record to format.

        Returns:
            Single-line JSON string (JSONL format).
        """
        # Build data dict from format keys
        data: dict[str, Any] = {
            k: getattr(record, v, None) for k, v in self.fmt_keys.items()
        }

        # Add UTC timestamp in ISO 8601 format with 'Z' suffix
        ts = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        data["timestamp"] = ts

        # Add process info if requested
        if self.include_process_info:
            data["process_id"] = record.process
            data["process_name"] = record.processName

        # Add thread info if requested
        if self.include_thread_info:
            data["thread_id"] = record.thread
            data["thread_name"] = record.threadName

        # Add OpenTelemetry trace context for correlation
        # This enables linking logs to traces in Grafana/Tempo
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            ctx = span.get_span_context()
            # Format as 32-character hex string (128-bit trace ID)
            data["trace_id"] = format(ctx.trace_id, "032x")
            # Format as 16-character hex string (64-bit span ID)
            data["span_id"] = format(ctx.span_id, "016x")
            # Include trace flags for completeness
            data["trace_flags"] = f"{ctx.trace_flags:02x}"

        # Add exception info if present
        # Replace newlines with \n to keep JSONL format (one line per record)
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            # Ensure no actual newlines in JSON output
            data["exception"] = exception_text.replace("\n", "\\n")

        # Add stack trace if present
        if record.stack_info:
            data["stack_trace"] = record.stack_info.replace("\n", "\\n")

        # Add static fields (e.g., service name)
        if self.static:
            data.update(self.static)

        # Add extra fields from LogRecord (context, request_id, etc.)
        # Skip built-in attributes that we don't want in output
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

        # Include any extra fields (from context, LoggerAdapter, etc.)
        for key, value in record.__dict__.items():
            if key not in skip_keys and key not in data:
                data[key] = value

        # Return JSON string with ensure_ascii=False for better UTF-8 support
        # default=str ensures any non-serializable objects are converted to strings
        return json.dumps(data, ensure_ascii=False, default=str)
