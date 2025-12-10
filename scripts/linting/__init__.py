"""Custom linting tools for enforcing code conventions.

These tools are designed to be run as pre-commit hooks or manually
to ensure code follows established patterns.

Available checks:
    - no_http_exception: Ensures feature routers use AppException instead of HTTPException
    - logging_checks: Ensures services follow standard logging patterns
    - openapi_checks: Ensures API endpoints have proper documentation
"""
