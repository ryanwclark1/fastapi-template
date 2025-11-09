"""RFC 7807 Problem Details schema for error responses."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details for HTTP APIs.

    Provides a standardized way to carry machine-readable details
    of errors in HTTP responses.

    See: https://datatracker.ietf.org/doc/html/rfc7807

    Example:
        ```python
        return JSONResponse(
            status_code=404,
            content=ProblemDetails(
                type="user-not-found",
                title="User Not Found",
                status=404,
                detail="User with ID abc123 does not exist",
                instance="/api/v1/users/abc123"
            ).model_dump()
        )
        ```
    """

    type: str = Field(
        default="about:blank",
        description="URI reference identifying the problem type",
    )
    title: str = Field(description="Short, human-readable summary of the problem")
    status: int = Field(description="HTTP status code")
    detail: str | None = Field(
        default=None, description="Human-readable explanation specific to this occurrence"
    )
    instance: str | None = Field(
        default=None, description="URI reference identifying the specific occurrence"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "type": "validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "Email address is invalid",
                "instance": "/api/v1/users",
            }
        }
