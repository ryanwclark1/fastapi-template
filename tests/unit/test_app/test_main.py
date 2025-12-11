"""Tests for FastAPI application factory."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import FastAPI

from example_service.app import main as main_module

if TYPE_CHECKING:
    import pytest


def _build_settings() -> SimpleNamespace:
    app_settings = SimpleNamespace(
        title="Test Service",
        summary="Summary text",
        description="Service description",
        version="0.0.1",
        openapi_tags=[{"name": "tag"}],
        servers=[{"url": "http://api"}],
        root_path="/service",
        root_path_in_servers=False,
        debug=True,
        redirect_slashes=False,
        separate_input_output_schemas=True,
        swagger_ui_oauth2_redirect_url=None,
        swagger_ui_init_oauth=None,
        swagger_ui_parameters=None,
        get_openapi_url=lambda: "/schema",
    )
    return SimpleNamespace(app=app_settings)


def test_create_app_configures_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """App factory should create FastAPI instance and wire configuration helpers."""
    calls: list[str] = []
    middleware_settings: list[SimpleNamespace] = []

    def _record(name: str):
        def _wrapper(app: FastAPI, *args):
            calls.append(name)
            assert isinstance(app, FastAPI)

        return _wrapper

    def _record_middleware(app: FastAPI, settings: SimpleNamespace) -> None:
        calls.append("middleware")
        middleware_settings.append(settings)

    settings = _build_settings()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "configure_exception_handlers", _record("exceptions"))
    monkeypatch.setattr(main_module, "configure_documentation", _record("docs"))
    monkeypatch.setattr(main_module, "configure_middleware", _record_middleware)
    monkeypatch.setattr(main_module, "setup_routers", _record("routers"))
    monkeypatch.setattr(main_module, "instrument_app", _record("instrument"))

    app = main_module.create_app()

    assert isinstance(app, FastAPI)
    assert app.title == settings.app.title
    assert app.description == settings.app.description
    assert app.openapi_tags == settings.app.openapi_tags
    assert app.openapi_url == settings.app.get_openapi_url()
    assert app.root_path == settings.app.root_path
    assert calls == ["exceptions", "docs", "middleware", "routers", "instrument"]
    assert middleware_settings == [settings]
