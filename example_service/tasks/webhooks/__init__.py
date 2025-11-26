"""Webhook delivery tasks.

This module provides background tasks for webhook delivery:
- Asynchronous webhook delivery with retry logic
- Exponential backoff for failed deliveries
- Automatic retry processing
"""

from __future__ import annotations

try:
    from .tasks import deliver_webhook, process_webhook_retries
except ImportError:  # Optional dependencies missing (e.g., broker not configured)
    deliver_webhook = None  # type: ignore[assignment]
    process_webhook_retries = None  # type: ignore[assignment]
    __all__: list[str] = []
else:
    __all__ = [
        "deliver_webhook",
        "process_webhook_retries",
    ]
