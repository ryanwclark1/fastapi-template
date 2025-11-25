"""Tests for router setup logic."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from example_service.app import router as router_module


@pytest.fixture
def settings() -> SimpleNamespace:
    """Return minimal app settings for router setup."""
    return SimpleNamespace(api_prefix="/api")


def _prepare_base(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    """Patch module-level dependencies with simple sentinels."""
    monkeypatch.setattr(router_module, "get_app_settings", lambda: settings)
    monkeypatch.setattr(router_module, "metrics_router", object())
    monkeypatch.setattr(router_module, "reminders_router", object())
    monkeypatch.setattr(router_module, "health_router", object())
    monkeypatch.setattr(router_module, "admin_router", object())


def test_setup_routers_without_rabbit(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    """Core routers should be included even when messaging router is missing."""
    _prepare_base(monkeypatch, settings)
    monkeypatch.setattr(router_module, "get_rabbit_router", lambda: None)

    app = MagicMock()
    router_module.setup_routers(app)

    assert app.include_router.call_args_list == [
        call(router_module.metrics_router, tags=["observability"]),
        call(router_module.reminders_router, prefix="/api", tags=["reminders"]),
        call(router_module.health_router, prefix="/api", tags=["health"]),
        call(router_module.admin_router, prefix="/api", tags=["Admin"]),
    ]


def test_setup_routers_includes_rabbit_router(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    """Messaging router should be included when available."""
    _prepare_base(monkeypatch, settings)
    rabbit_router = object()
    monkeypatch.setattr(router_module, "get_rabbit_router", lambda: rabbit_router)

    app = MagicMock()
    router_module.setup_routers(app)

    assert call(rabbit_router, tags=["messaging"]) in app.include_router.call_args_list
