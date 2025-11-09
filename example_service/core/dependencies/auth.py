"""Authentication dependencies for FastAPI."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials, Depends(security)
    ] | None = None,
) -> dict[str, str]:
    """Extract and validate current user from JWT token.

    Args:
        credentials: HTTP authorization credentials from header.

    Returns:
        User information extracted from token.

    Raises:
        HTTPException: If token is invalid or user not found.

    Example:
        ```python
        @router.get("/profile")
        async def get_profile(user: dict = Depends(get_current_user)):
            return user
        ```
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
        )

    # TODO: Implement JWT token validation
    # token = credentials.credentials
    # payload = decode_jwt_token(token)
    # user = await get_user_by_id(payload["user_id"])
    # if not user:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid authentication credentials"
    #     )
    # return user

    raise NotImplementedError("Authentication not configured")


def require_role(required_role: str):
    """Dependency factory for role-based access control.

    Args:
        required_role: Required role name.

    Returns:
        Dependency function that checks user role.

    Example:
        ```python
        @router.get("/admin")
        async def admin_endpoint(user: dict = Depends(require_role("admin"))):
            return {"message": "Admin access granted"}
        ```
    """

    async def role_checker(
        user: dict = Depends(get_current_user),
    ) -> dict:
        """Check if user has required role.

        Args:
            user: Current user from authentication.

        Returns:
            User if they have the required role.

        Raises:
            HTTPException: If user doesn't have required role.
        """
        user_roles = user.get("roles", [])
        if required_role not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {required_role}",
            )
        return user

    return role_checker
