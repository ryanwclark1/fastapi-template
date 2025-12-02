"""Tests for I18nMiddleware locale detection."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Scope

from example_service.app.middleware.i18n import I18nMiddleware


def _make_scope(headers=None, query_string: bytes = b"", cookies=None) -> Scope:
    return {
        "type": "http",
        "path": "/",
        "method": "GET",
        "headers": headers or [],
        "query_string": query_string,
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
        "cookies": cookies or {},
    }


@pytest.mark.asyncio
async def test_i18n_prefers_user_and_sets_headers_and_cookie():
    translations = {"hello": "hola"}
    middleware = I18nMiddleware(
        app=None,
        default_locale="en",
        supported_locales=["en", "es"],
        translation_provider=lambda locale: translations if locale == "es" else {},
    )

    user = type("User", (), {"preferred_language": "es"})()
    scope = _make_scope()
    request = Request(scope)
    request.state.user = user

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert request.state.locale == "es"
    assert request.state.translations == translations
    assert response.headers["Content-Language"] == "es"
    assert "locale" in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_i18n_uses_accept_language_fallback():
    middleware = I18nMiddleware(app=None, supported_locales=["en", "fr"], default_locale="en")
    scope = _make_scope(headers=[(b"accept-language", b"fr-CA, en;q=0.8")])
    request = Request(scope)

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    assert request.state.locale == "fr"
    assert response.headers["Content-Language"] == "fr"
