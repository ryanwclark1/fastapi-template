"""Files feature package."""

from .repository import FileRepository, get_file_repository
from .router import router

__all__ = [
    "router",
    "FileRepository",
    "get_file_repository",
]
