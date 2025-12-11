"""Core utility functions for the application.

This module provides reusable utility functions for common patterns
across the application, including ACL checking, error handling, and
data transformations.

Utilities Organization:
    - acl: ACL permission checking utilities

Example:
    ```python
    from example_service.core.utils.acl import require_permission, require_owner_or_admin

    @router.delete("/resources/{resource_id}")
    async def delete_resource(
        resource_id: str,
        user: AuthUserDep,
        request: Request,
    ):
        require_permission(user, "resources.delete", request.url.path)
        await service.delete(resource_id)
    ```
"""

from __future__ import annotations

from example_service.core.utils.acl import (
    require_any_permission,
    require_owner_or_admin,
    require_permission,
)

__all__ = [
    # ACL utilities
    "require_any_permission",
    "require_owner_or_admin",
    "require_permission",
]
