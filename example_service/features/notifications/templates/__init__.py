"""Template rendering infrastructure for notifications.

Provides Jinja2-based template rendering for multi-channel notifications.
Supports email (subject, plain text, HTML), webhooks (JSON payloads),
and WebSocket (event types and payloads).
"""

from __future__ import annotations

from example_service.features.notifications.templates.renderer import (
    TemplateRenderer,
    TemplateRenderError,
)
from example_service.features.notifications.templates.service import (
    NotificationTemplateService,
)

__all__ = [
    "NotificationTemplateService",
    "TemplateRenderError",
    "TemplateRenderer",
]
