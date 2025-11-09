"""Logging configuration setup."""
from __future__ import annotations

import atexit
import json
import logging
import logging.config
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Any

# Global queue and listener for async logging
_log_queue: Queue[logging.LogRecord] | None = None
_listener: QueueListener | None = None


def configure_logging(
    config_path: str | Path = "logging.json",
    overrides: dict[str, Any] | None = None,
) -> None:
    """Configure logging from JSON config file.

    Sets up QueueHandler/QueueListener if queue handler is present in config
    for non-blocking async logging.

    Args:
        config_path: Path to logging.json configuration file.
        overrides: Optional overrides to merge into loaded config.

    Example:
        ```python
        # In app/lifespan.py
        configure_logging()
        ```
    """
    global _log_queue, _listener

    path = Path(config_path)

    # If config file doesn't exist, use default configuration
    if not path.exists():
        _configure_default_logging()
        return

    # Load config from JSON file
    config = json.loads(path.read_text(encoding="utf-8"))
    if overrides:
        config.update(overrides)

    # Create queue if queue handler is present
    if "queue" in config.get("handlers", {}):
        _log_queue = Queue()
        config["handlers"]["queue"]["queue"] = _log_queue

    # Apply configuration
    logging.config.dictConfig(config)

    # Setup QueueListener if queue was created
    if _log_queue is not None:
        # Get handlers from root logger (created by dictConfig)
        root = logging.getLogger()
        actual_handlers = [h for h in root.handlers if not isinstance(h, QueueHandler)]

        # Create QueueListener with the handlers
        if actual_handlers:
            _listener = QueueListener(
                _log_queue, *actual_handlers, respect_handler_level=True
            )
            _listener.start()
            atexit.register(_listener.stop)

            # Remove handlers from root since QueueListener handles them
            for h in actual_handlers:
                root.removeHandler(h)


def _configure_default_logging() -> None:
    """Configure default logging when no config file exists.

    Sets up console logging with JSON formatter and file logging
    with rotation.
    """
    global _log_queue, _listener

    from example_service.infra.logging.formatters import JSONFormatter

    # Create log directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Create queue for async logging
    _log_queue = Queue()

    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        JSONFormatter(
            fmt_keys={"level": "levelname", "logger": "name", "message": "message"},
            static={"service": "example-service"},
        )
    )

    file_handler = RotatingFileHandler(
        log_dir / "example-service.log.jsonl",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        JSONFormatter(
            fmt_keys={"level": "levelname", "logger": "name", "message": "message"},
            static={"service": "example-service"},
        )
    )

    # Create QueueListener
    _listener = QueueListener(
        _log_queue, console_handler, file_handler, respect_handler_level=True
    )
    _listener.start()
    atexit.register(_listener.stop)

    # Configure root logger with QueueHandler
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(_log_queue))
