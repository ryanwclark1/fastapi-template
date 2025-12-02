"""Storage management feature.

This feature provides admin-level API endpoints for:
- Bucket management (create, delete, list)
- Object operations (list, upload, delete)
- ACL management (get, set)

Separate from /files/ feature which tracks files in the database.
This is for raw storage operations.
"""

from .router import router

__all__ = ["router"]
