"""Tests for I18n middleware locale detection and translation management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from example_service.app.middleware.i18n import I18nMiddleware, create_i18n_middleware

if TYPE_CHECKING:
    pass


# Fixtures


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app for testing.

    Returns:
        FastAPI application instance
    """
    return FastAPI()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client.

    Args:
        app: FastAPI application

    Returns:
        Test client instance
    """
    return TestClient(app)


@pytest.fixture
def translations() -> dict[str, dict[str, str]]:
    """Sample translation data.

    Returns:
        Dictionary of translations by locale
    """
    return {
        "en": {
            "hello": "Hello",
            "goodbye": "Goodbye",
            "welcome": "Welcome to our application",
        },
        "es": {
            "hello": "Hola",
            "goodbye": "Adiós",
            "welcome": "Bienvenido a nuestra aplicación",
        },
        "fr": {
            "hello": "Bonjour",
            "goodbye": "Au revoir",
            "welcome": "Bienvenue dans notre application",
        },
    }


@pytest.fixture
def translation_provider(translations: dict[str, dict[str, str]]):
    """Create a translation provider function.

    Args:
        translations: Translation data

    Returns:
        Translation provider callable
    """

    def provider(locale: str) -> dict[str, str]:
        return translations.get(locale, translations["en"])

    return provider


# Basic Locale Detection Tests


def test_default_locale_when_no_detection_sources(app: FastAPI, client: TestClient):
    """Test that default locale is used when no detection sources available."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test")
    assert response.status_code == 200
    assert response.json()["locale"] == "en"


def test_locale_from_accept_language_header(app: FastAPI, client: TestClient):
    """Test locale detection from Accept-Language header."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"Accept-Language": "es"})
    assert response.status_code == 200
    assert response.json()["locale"] == "es"


def test_locale_from_query_parameter(app: FastAPI, client: TestClient):
    """Test locale detection from query parameter."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test?lang=fr")
    assert response.status_code == 200
    assert response.json()["locale"] == "fr"


def test_locale_from_cookie(app: FastAPI, client: TestClient):
    """Test locale detection from cookie."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Set locale cookie
    client.cookies.set("locale", "es")
    response = client.get("/test")
    assert response.status_code == 200
    assert response.json()["locale"] == "es"


def test_locale_from_user_preference(app: FastAPI, client: TestClient):
    """Test locale detection from user preference."""

    class MockUser:
        preferred_language = "fr"

    # Add I18n middleware first
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    # Then add auth middleware that will run BEFORE I18n (last added = first to run)
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        request.state.user = MockUser()
        response = await call_next(request)
        return response

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test")
    assert response.status_code == 200
    assert response.json()["locale"] == "fr"


# Accept-Language Header Parsing Tests


def test_accept_language_with_quality_values(app: FastAPI, client: TestClient):
    """Test Accept-Language header parsing with quality values."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Spanish has highest quality among supported locales
    response = client.get("/test", headers={"Accept-Language": "de;q=0.9,es;q=0.8,fr;q=0.7"})
    assert response.json()["locale"] == "es"


def test_accept_language_with_region_codes(app: FastAPI, client: TestClient):
    """Test Accept-Language header with region codes (e.g., en-US)."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Should extract 'es' from 'es-MX'
    response = client.get("/test", headers={"Accept-Language": "es-MX,en-US;q=0.9"})
    assert response.json()["locale"] == "es"


def test_accept_language_complex_header(app: FastAPI, client: TestClient):
    """Test complex Accept-Language header with multiple languages."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # French should be selected (highest quality of supported)
    response = client.get(
        "/test", headers={"Accept-Language": "de-DE,fr-FR;q=0.9,en-US;q=0.8,es;q=0.7"}
    )
    assert response.json()["locale"] == "fr"


def test_accept_language_unsupported_languages(app: FastAPI, client: TestClient):
    """Test Accept-Language header with only unsupported languages."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Should fall back to default (en)
    response = client.get("/test", headers={"Accept-Language": "de-DE,it-IT,ja-JP"})
    assert response.json()["locale"] == "en"


# Priority Tests


def test_locale_priority_user_over_header(app: FastAPI, client: TestClient):
    """Test that user preference takes priority over Accept-Language."""

    class MockUser:
        preferred_language = "es"

    # Add I18n middleware first
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    # Then add auth middleware that will run BEFORE I18n (last added = first to run)
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        request.state.user = MockUser()
        response = await call_next(request)
        return response

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # User preference (es) should override header (fr)
    response = client.get("/test", headers={"Accept-Language": "fr"})
    assert response.json()["locale"] == "es"


def test_locale_priority_header_over_query(app: FastAPI, client: TestClient):
    """Test that Accept-Language header takes priority over query parameter.

    Note: This tests the actual priority order where header comes before query.
    """
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Header (es) should take priority over query (fr)
    response = client.get("/test?lang=fr", headers={"Accept-Language": "es"})
    assert response.json()["locale"] == "es"


def test_locale_priority_query_over_cookie(app: FastAPI, client: TestClient):
    """Test that query parameter takes priority over cookie."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Query (fr) should override cookie (es)
    client.cookies.set("locale", "es")
    response = client.get("/test?lang=fr")
    assert response.json()["locale"] == "fr"


# Translation Provider Tests


def test_translations_loaded(
    app: FastAPI, client: TestClient, translation_provider
):
    """Test that translations are loaded via provider."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        translation_provider=translation_provider,
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {
            "locale": request.state.locale,
            "translations": request.state.translations,
        }

    response = client.get("/test", headers={"Accept-Language": "es"})
    data = response.json()
    assert data["locale"] == "es"
    assert data["translations"]["hello"] == "Hola"
    assert data["translations"]["welcome"] == "Bienvenido a nuestra aplicación"


def test_translations_fallback_on_error(app: FastAPI, client: TestClient):
    """Test that empty dict is provided when translation loading fails."""

    def failing_provider(locale: str) -> dict[str, str]:
        raise RuntimeError("Translation loading failed")

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es"],
        translation_provider=failing_provider,
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"translations": request.state.translations}

    response = client.get("/test")
    assert response.status_code == 200
    assert response.json()["translations"] == {}


def test_no_translation_provider(app: FastAPI, client: TestClient):
    """Test that empty translations dict is provided when no provider."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"translations": request.state.translations}

    response = client.get("/test")
    assert response.json()["translations"] == {}


# Response Headers and Cookies Tests


def test_content_language_header_set(app: FastAPI, client: TestClient):
    """Test that Content-Language header is set in response."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"Accept-Language": "es"})
    assert response.headers["content-language"] == "es"


def test_locale_cookie_set(app: FastAPI, client: TestClient):
    """Test that locale cookie is set in response."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"Accept-Language": "es"})

    # Check that locale cookie was set
    assert "locale" in response.cookies
    assert response.cookies["locale"] == "es"


def test_custom_cookie_name(app: FastAPI, client: TestClient):
    """Test custom cookie name configuration."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es"],
        cookie_name="user_locale",
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"Accept-Language": "es"})
    assert "user_locale" in response.cookies
    assert response.cookies["user_locale"] == "es"


# Custom Detector Tests


def test_custom_locale_detector(app: FastAPI, client: TestClient):
    """Test custom locale detector function."""

    def custom_detector(request: Request) -> str:
        # Custom logic: check X-App-Locale header
        return request.headers.get("x-app-locale", "en")

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        locale_detector=custom_detector,
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"x-app-locale": "fr"})
    assert response.json()["locale"] == "fr"


# Selective Detection Tests


def test_disable_query_param_detection(app: FastAPI, client: TestClient):
    """Test that query parameter detection can be disabled."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        use_query_param=False,
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Query parameter should be ignored
    response = client.get("/test?lang=fr")
    assert response.json()["locale"] == "en"  # Falls back to default


def test_disable_cookie_detection(app: FastAPI, client: TestClient):
    """Test that cookie detection can be disabled."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        use_cookie=False,
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Cookie should be ignored
    client.cookies.set("locale", "fr")
    response = client.get("/test")
    assert response.json()["locale"] == "en"  # Falls back to default


def test_disable_accept_language_detection(app: FastAPI, client: TestClient):
    """Test that Accept-Language detection can be disabled."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        use_accept_language=False,
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Accept-Language header should be ignored
    response = client.get("/test", headers={"Accept-Language": "fr"})
    assert response.json()["locale"] == "en"  # Falls back to default


# Factory Function Tests


def test_create_i18n_middleware_factory(app: FastAPI, client: TestClient):
    """Test create_i18n_middleware factory function."""
    middleware_class = create_i18n_middleware(
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        cookie_max_age_days=7,
    )

    app.add_middleware(middleware_class)

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"Accept-Language": "es"})
    assert response.json()["locale"] == "es"


# Validation Tests


def test_unsupported_locale_falls_back_to_default(app: FastAPI, client: TestClient):
    """Test that unsupported locale falls back to default."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Try to request unsupported locale
    response = client.get("/test?lang=de")
    assert response.json()["locale"] == "en"  # Falls back to default


def test_empty_accept_language_header(app: FastAPI, client: TestClient):
    """Test handling of empty Accept-Language header."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    response = client.get("/test", headers={"Accept-Language": ""})
    assert response.json()["locale"] == "en"


def test_malformed_accept_language_header(app: FastAPI, client: TestClient):
    """Test handling of malformed Accept-Language header."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Malformed header should not crash, fall back to default
    response = client.get("/test", headers={"Accept-Language": "invalid;;;q=abc"})
    assert response.json()["locale"] == "en"


# Integration Tests


def test_multiple_requests_different_locales(app: FastAPI, client: TestClient):
    """Test multiple requests with different locales."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Request 1: English
    response1 = client.get("/test", headers={"Accept-Language": "en"})
    assert response1.json()["locale"] == "en"

    # Request 2: Spanish
    response2 = client.get("/test", headers={"Accept-Language": "es"})
    assert response2.json()["locale"] == "es"

    # Request 3: French
    response3 = client.get("/test", headers={"Accept-Language": "fr"})
    assert response3.json()["locale"] == "fr"


def test_locale_persistence_across_requests(app: FastAPI):
    """Test that locale cookie persists across requests."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"locale": request.state.locale}

    # Create a session-based client
    with TestClient(app) as session_client:
        # First request sets cookie via Accept-Language
        response1 = session_client.get("/test", headers={"Accept-Language": "es"})
        assert response1.json()["locale"] == "es"

        # Second request should use cookie (no header)
        response2 = session_client.get("/test")
        assert response2.json()["locale"] == "es"


def test_real_world_scenario(
    app: FastAPI, client: TestClient, translation_provider
):
    """Test real-world scenario with multiple features."""
    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        translation_provider=translation_provider,
        cookie_name="user_locale",
        query_param="lang",
    )

    @app.get("/welcome")
    async def welcome(request: Request):
        translations = request.state.translations
        return {
            "locale": request.state.locale,
            "message": translations.get("welcome", "Welcome"),
        }

    # Test with Spanish
    response = client.get("/welcome?lang=es")
    assert response.json()["locale"] == "es"
    assert "Bienvenido" in response.json()["message"]

    # Verify cookie was set
    assert response.cookies["user_locale"] == "es"

    # Verify Content-Language header
    assert response.headers["content-language"] == "es"
