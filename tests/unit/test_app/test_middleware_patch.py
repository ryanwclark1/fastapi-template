"""Tests for the FastAPI middleware ordering patch."""

from __future__ import annotations

from fastapi import FastAPI
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from example_service.app.middleware.metrics import MetricsMiddleware
from example_service.app.middleware.rate_limit import RateLimitMiddleware
from example_service.app.middleware.request_id import RequestIDMiddleware


class StubLimiter:
    async def check_limit(self, **_: object) -> tuple[bool, dict]:
        return True, {"limit": 5, "remaining": 4, "reset": 30}


class DummyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


class AnotherDummyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


def _middleware_classes(app: FastAPI) -> list[type]:
    return [mw.cls for mw in app.user_middleware]


def test_known_middleware_priority_order() -> None:
    app = FastAPI()
    app.add_middleware(DummyMiddleware, name="third_dummy")
    app.add_middleware(RateLimitMiddleware, limiter=StubLimiter())
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(MetricsMiddleware)

    classes = _middleware_classes(app)
    assert classes == [
        MetricsMiddleware,
        RequestIDMiddleware,
        RateLimitMiddleware,
        DummyMiddleware,
    ]


def test_unknown_middleware_order_uses_name_hints() -> None:
    app = FastAPI()
    app.add_middleware(DummyMiddleware, name="third_layer")
    app.add_middleware(AnotherDummyMiddleware, name="second_layer")

    classes = _middleware_classes(app)
    # second_layer has higher ordinal hint, so it comes first
    assert classes[:2] == [AnotherDummyMiddleware, DummyMiddleware]


def test_rate_limit_validator_runs() -> None:
    app = FastAPI()
    with pytest.raises(ValueError, match=r"limiter is required"):
        app.add_middleware(RateLimitMiddleware)
