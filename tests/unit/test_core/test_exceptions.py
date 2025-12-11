"""Tests for core exceptions."""

from example_service.core import exceptions as exc


def test_app_exception_defaults_title() -> None:
    error = exc.AppException(status_code=400, detail="bad")
    assert error.title == "Bad Request"
    assert error.extra == {}


def test_not_found_exception_fields() -> None:
    error = exc.NotFoundException(detail="missing")
    assert error.status_code == 404
    assert error.type == "not-found"
    assert error.title == "Not Found"


def test_rate_limit_exception_custom_status() -> None:
    error = exc.RateLimitException(
        detail="slow down",
        status_code=499,
        extra={"retry_after": 30},
    )
    assert error.status_code == 499
    assert error.extra["retry_after"] == 30


def test_token_expired_error_merges_extra() -> None:
    error = exc.TokenExpiredError(token_uuid="abc", extra={"env": "test"})
    assert error.extra["token_uuid"] == "abc"
    assert error.extra["env"] == "test"


def test_insufficient_permissions_builds_detail() -> None:
    error = exc.InsufficientPermissionsError(required_permission="admin.write")
    assert "admin.write" in error.detail
    assert error.extra["required_permission"] == "admin.write"
