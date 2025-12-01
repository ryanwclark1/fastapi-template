"""Tags feature for organizing reminders with many-to-many relationships."""

from __future__ import annotations

from .models import Tag, reminder_tags
from .router import router
from .schemas import TagCreate, TagResponse, TagUpdate

__all__ = [
    "Tag",
    "TagCreate",
    "TagResponse",
    "TagUpdate",
    "reminder_tags",
    "router",
]
