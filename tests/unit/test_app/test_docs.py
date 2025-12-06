"""Tests for documentation helpers."""

from __future__ import annotations

import html
import sys
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI
import pytest
from starlette.routing import Mount

from example_service.app import docs as docs_module


def test_path_helpers_normalize_and_join() -> None:
    assert docs_module._normalize_path("docs") == "/docs"
    assert docs_module._normalize_path("/docs/") == "/docs"
    assert docs_module._path_join("/docs", "swagger") == "/docs/swagger"
    assert docs_module._path_join("/", "swagger") == "/swagger"


def test_render_templates_escape_values_and_use_local_assets() -> None:
    title = '<API "X" & Co>'
    config_url = '/docs?param=<value>&quote="yes"'

    swagger_html = docs_module._render_swagger_html(title=title, config_url=config_url)
    assert f"<title>{html.escape(title)} · API Explorer</title>" in swagger_html
    assert f'data-swagger-config-url="{html.escape(config_url, quote=True)}"' in swagger_html
    assert "/_static/docs/swagger-ui-bundle.js" in swagger_html

    redoc_html = docs_module._render_redoc_html(title=title, spec_url="/spec?<x>")
    assert f"<title>{html.escape(title)} · ReDoc</title>" in redoc_html
    assert 'data-redoc-spec-url="/spec?&lt;x&gt;"' in redoc_html

    oauth_html = docs_module._render_oauth_redirect_html()
    assert "/_static/docs/docs.css" in oauth_html
    assert "/_static/docs/swagger-ui-oauth2-redirect.js" in oauth_html


def test_configure_documentation_mounts_static_and_skips_docs_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url="/openapi.json")
    patched = []
    settings = SimpleNamespace(
        disable_docs=True,
        title="Docs Disabled",
        swagger_ui_init_oauth=None,
        get_docs_url=lambda: "/docs",
        get_redoc_url=lambda: "/redoc",
        get_swagger_ui_oauth2_redirect_url=lambda: "/oauth",
        get_openapi_url=lambda: "/schema",
        get_swagger_ui_parameters=dict,
    )

    monkeypatch.setattr(docs_module, "get_app_settings", lambda: settings)
    monkeypatch.setattr(docs_module, "ensure_asyncapi_template_patched", lambda: patched.append(True))

    docs_module.configure_documentation(app)

    assert patched == [True]
    assert any(isinstance(route, Mount) and route.path == "/_static/docs" for route in app.routes)
    assert not any(route.path == "/docs" for route in app.routes)


def test_ensure_asyncapi_template_patched_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncapi_site = SimpleNamespace(get_asyncapi_html=lambda *_, **__: "original")
    spec_module = ModuleType("faststream.specification")
    asyncapi_module = ModuleType("faststream.specification.asyncapi")
    asyncapi_module.site = asyncapi_site

    monkeypatch.setitem(sys.modules, "faststream", ModuleType("faststream"))
    monkeypatch.setitem(sys.modules, "faststream.specification", spec_module)
    monkeypatch.setitem(sys.modules, "faststream.specification.asyncapi", asyncapi_module)
    monkeypatch.setattr(docs_module, "_ASYNCAPI_PATCHED", False)

    docs_module.ensure_asyncapi_template_patched()
    first = asyncapi_site.get_asyncapi_html
    docs_module.ensure_asyncapi_template_patched()

    assert callable(first)
    assert asyncapi_site.get_asyncapi_html is first
