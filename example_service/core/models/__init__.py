"""Database models package.

Import all models here to make them available to Alembic for auto-generation.
"""

from .post import Post
from .user import User

__all__ = ["User", "Post"]
