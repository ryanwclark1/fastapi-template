"""Tests for router setup logic."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

# Provide lightweight stubs for optional dependencies when absent
try:  # pragma: no cover - real dependency available
    import strawberry  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in test env without strawberry
    strawberry = ModuleType("strawberry")
    strawberry_fastapi = ModuleType("strawberry.fastapi")

    class _DummyGraphQLRouter:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    strawberry_fastapi.GraphQLRouter = _DummyGraphQLRouter  # type: ignore[attr-defined]
    strawberry.fastapi = strawberry_fastapi  # type: ignore[attr-defined]
    strawberry.__example_stub__ = True
    sys.modules["strawberry"] = strawberry
    sys.modules["strawberry.fastapi"] = strawberry_fastapi

try:  # pragma: no cover - real dependency available
    import email_validator  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - executed in test env without email-validator
    email_validator = ModuleType("email_validator")

    class EmailNotValidError(ValueError):
        """Fallback error type matching real library API."""

    def validate_email(email: str, **_: object):
        return SimpleNamespace(email=email)

    email_validator.EmailNotValidError = EmailNotValidError  # type: ignore[attr-defined]
    email_validator.validate_email = validate_email  # type: ignore[attr-defined]
    sys.modules["email_validator"] = email_validator

# Provide a stub GraphQL router to avoid optional dependencies during import
if "example_service.features.graphql.router" not in sys.modules:  # pragma: no cover
    graphql_pkg = ModuleType("example_service.features.graphql")
    graphql_router_module = ModuleType("example_service.features.graphql.router")
    graphql_router_module.router = object()
    graphql_pkg.router = graphql_router_module.router
    sys.modules["example_service.features.graphql"] = graphql_pkg
    sys.modules["example_service.features.graphql.router"] = graphql_router_module

pytest.importorskip("dateutil.rrule", reason="Reminder router relies on python-dateutil")

from example_service.app import router as router_module


@pytest.fixture
def settings() -> SimpleNamespace:
    """Return minimal app settings for router setup."""
    return SimpleNamespace(api_prefix="/api")


def _prepare_base(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    """Patch module-level dependencies with simple sentinels."""
    monkeypatch.setattr(router_module, "get_app_settings", lambda: settings)
    monkeypatch.setattr(
        router_module, "get_websocket_settings", lambda: SimpleNamespace(enabled=False)
    )
    monkeypatch.setattr(
        router_module,
        "get_graphql_settings",
        lambda: SimpleNamespace(enabled=False, path="/graphql", playground_enabled=True),
    )
    monkeypatch.setattr(router_module, "metrics_router", object())
    monkeypatch.setattr(router_module, "reminders_router", object())
    monkeypatch.setattr(router_module, "tags_router", object())
    monkeypatch.setattr(router_module, "reminder_tags_router", object())
    monkeypatch.setattr(router_module, "health_router", object())
    monkeypatch.setattr(router_module, "files_router", object())
    monkeypatch.setattr(router_module, "webhooks_router", object())
    monkeypatch.setattr(router_module, "admin_router", object())


def test_setup_routers_without_rabbit(
    monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace
) -> None:
    """Core routers should be included even when messaging router is missing."""
    _prepare_base(monkeypatch, settings)
    monkeypatch.setattr(router_module, "get_rabbit_router", lambda: None)

    app = MagicMock()
    router_module.setup_routers(app)

    # GraphQL is disabled in _prepare_base, so it should not be included
    assert app.include_router.call_args_list == [
        call(router_module.metrics_router, tags=["observability"]),
        call(router_module.reminders_router, prefix="/api", tags=["reminders"]),
        call(router_module.tags_router, prefix="/api", tags=["tags"]),
        call(router_module.reminder_tags_router, prefix="/api", tags=["reminders", "tags"]),
        call(router_module.health_router, prefix="/api", tags=["health"]),
        call(router_module.admin_router, prefix="/api", tags=["Admin"]),
        call(router_module.files_router, prefix="/api", tags=["files"]),
        call(router_module.webhooks_router, prefix="/api", tags=["webhooks"]),
    ]


def test_setup_routers_includes_rabbit_router(
    monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace
) -> None:
    """Messaging router should be included when available."""
    _prepare_base(monkeypatch, settings)
    rabbit_router = object()
    monkeypatch.setattr(router_module, "get_rabbit_router", lambda: rabbit_router)

    app = MagicMock()
    router_module.setup_routers(app)

    assert call(rabbit_router, tags=["messaging"]) in app.include_router.call_args_list
