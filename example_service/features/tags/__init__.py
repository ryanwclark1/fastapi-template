"""Tags feature for organizing reminders with many-to-many relationships."""

from __future__ import annotations

from .models import Tag, reminder_tags
from .repository import TagRepository, get_tag_repository
from .schemas import TagCreate, TagResponse, TagUpdate
from .service import TagService

__all__ = [
    "Tag",
    "TagCreate",
    "TagRepository",
    "TagResponse",
    "TagService",
    "TagUpdate",
    "get_tag_repository",
    "reminder_tags",
]
