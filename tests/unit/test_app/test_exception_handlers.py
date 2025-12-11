"""Tests for application exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from example_service.app.exception_handlers import (
    ProblemJSONResponse,
    app_exception_handler,
    configure_exception_handlers,
    generic_exception_handler,
    not_found_error_handler,
    pydantic_validation_exception_handler,
    validation_exception_handler,
)
from example_service.core.database.exceptions import NotFoundError
from example_service.core.exceptions import AppException, RateLimitException


def _build_request(path: str = "/test") -> Request:
    """Create a minimal ASGI request for handler tests."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("test", 1234),
        "server": ("test", 80),
    }
    return Request(scope, lambda: None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception_cls", "headers_expected"),
    [
        (AppException, False),
        (RateLimitException, True),
    ],
)
async def test_app_exception_handler_handles_problem_details(
    exception_cls: type[AppException], headers_expected: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App exceptions should produce RFC 7807 responses and track metrics."""
    tracked: dict[str, Any] = {}

    def fake_track_error(**payload: Any) -> None:
        tracked.update(payload)

    monkeypatch.setattr(
        "example_service.app.exception_handlers.tracking.track_error",
        fake_track_error,
    )

    exc = exception_cls(
        status_code=429 if exception_cls is RateLimitException else 400,
        detail="oops",
        extra={"retry_after": 42} if exception_cls is RateLimitException else None,
    )
    request = _build_request()
    request.state.request_id = "req-123"

    response = await app_exception_handler(request, exc)

    assert response.status_code == exc.status_code
    body = response.json()
    assert body["detail"] == "oops"
    assert body["request_id"] == "req-123"
    assert tracked["error_type"] == exc.type
    if headers_expected:
        assert response.headers["Retry-After"] == "42"


@pytest.mark.asyncio
async def test_validation_exception_handler_formats_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validation errors should include field-level details."""
    from fastapi.exceptions import RequestValidationError

    seen_fields: list[str] = []

    def fake_track(path: str, field: str) -> None:
        seen_fields.append(field)

    monkeypatch.setattr(
        "example_service.app.exception_handlers.tracking.track_validation_error",
        fake_track,
    )

    request = _build_request("/items")
    exc = RequestValidationError(
        [
            {"loc": ("body", "name"), "msg": "field required", "type": "value_error"},
        ],
    )

    response = await validation_exception_handler(request, exc)

    assert response.status_code == 422
    payload = response.json()
    assert payload["errors"][0]["field"] == "body.name"
    assert seen_fields == ["body.name"]


@pytest.mark.asyncio
async def test_generic_exception_handler_tracks_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unhandled exceptions should be tracked and return 500."""
    tracked: dict[str, Any] = {}

    def fake_track(**payload: Any) -> None:
        tracked.update(payload)

    monkeypatch.setattr(
        "example_service.app.exception_handlers.tracking.track_unhandled_exception",
        fake_track,
    )

    request = _build_request("/boom")
    response = await generic_exception_handler(request, RuntimeError("boom"))

    assert response.status_code == 500
    assert tracked["exception_type"] == "RuntimeError"


def test_problem_json_response_parses_body() -> None:
    """ProblemJSONResponse.json should return parsed JSON payload."""
    response = ProblemJSONResponse(status_code=200, content={"foo": "bar"})
    assert response.json() == {"foo": "bar"}


def test_configure_exception_handlers_registers_handlers() -> None:
    """Integration smoke test to ensure handlers are wired on FastAPI app."""
    app = FastAPI()
    configure_exception_handlers(app)

    @app.get("/app-exc")
    def raise_app_exc() -> None:
        raise AppException(status_code=418, detail="teapot")

    @app.get("/validate")
    def raise_validation() -> None:
        msg = "boom"
        raise ValueError(msg)

    client = TestClient(app)
    resp = client.get("/app-exc")
    assert resp.status_code == 418
    resp = client.get("/validate")
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_not_found_error_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Database NotFoundError should become RFC7807 response."""
    monkeypatch.setattr(
        "example_service.app.exception_handlers.tracking.track_error",
        lambda **_: None,
    )
    request = _build_request("/posts/1")
    request.state.request_id = "req-456"
    exc = NotFoundError("Post", {"id": 1})

    response = await not_found_error_handler(request, exc)

    assert response.status_code == 404
    payload = response.json()
    assert payload["model"] == "Post"
    assert payload["request_id"] == "req-456"


@pytest.mark.asyncio
async def test_pydantic_validation_exception_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standalone Pydantic validation errors should be formatted properly."""
    from pydantic import BaseModel, ValidationError

    monkeypatch.setattr(
        "example_service.app.exception_handlers.logger.warning",
        lambda *_, **__: None,
    )

    class Model(BaseModel):
        name: str

    with pytest.raises(ValidationError) as err:
        Model(name=123)  # type: ignore[arg-type]

    request = _build_request("/pydantic")
    request.state.request_id = "req-789"
    response = await pydantic_validation_exception_handler(request, err.value)

    assert response.status_code == 422
    payload = response.json()
    assert payload["errors"][0]["field"] == "name"
    assert payload["request_id"] == "req-789"
