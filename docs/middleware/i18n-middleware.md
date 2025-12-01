# I18n Middleware Documentation

## Overview

The I18n (Internationalization) Middleware provides comprehensive multi-language support for FastAPI applications. It handles automatic locale detection from multiple sources and manages translation context throughout the request lifecycle.

## Features

- **Multi-source locale detection** with configurable priority
- **Accept-Language header parsing** with quality value support
- **User preference integration** for authenticated users
- **Query parameter override** for testing and sharing
- **Cookie-based persistence** for user experience
- **Translation provider integration** for dynamic content
- **Configurable via environment variables** or YAML
- **Production-ready** with proper error handling

## Installation

The I18n middleware is included in the fastapi-template. No additional dependencies are required.

## Quick Start

### Basic Setup

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

app = FastAPI()

app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],
)

@app.get("/hello")
async def hello(request: Request):
    locale = request.state.locale
    return {"locale": locale, "message": f"Hello in {locale}"}
```

### Configuration via Settings

```python
from fastapi import FastAPI
from example_service.core.settings import get_i18n_settings
from example_service.app.middleware.i18n import create_i18n_middleware

app = FastAPI()

i18n_settings = get_i18n_settings()

if i18n_settings.enabled:
    middleware_class = create_i18n_middleware(
        default_locale=i18n_settings.default_locale,
        supported_locales=i18n_settings.supported_locales,
        cookie_name=i18n_settings.cookie_name,
        cookie_max_age_days=i18n_settings.cookie_max_age_days,
    )
    app.add_middleware(middleware_class)
```

### Environment Variables

```bash
# Enable I18n middleware
I18N_ENABLED=true

# Configure locales
I18N_DEFAULT_LOCALE=en
I18N_SUPPORTED_LOCALES=["en", "es", "fr", "de", "it"]

# Cookie configuration
I18N_COOKIE_NAME=locale
I18N_COOKIE_MAX_AGE_DAYS=30

# Query parameter
I18N_QUERY_PARAM=lang

# Detection sources (all default to true)
I18N_USE_ACCEPT_LANGUAGE=true
I18N_USE_USER_PREFERENCE=true
I18N_USE_QUERY_PARAM=true
I18N_USE_COOKIE=true
```

## Locale Detection Priority

The middleware detects locales in the following priority order (highest to lowest):

1. **User Preference** - `request.state.user.preferred_language`
2. **Accept-Language Header** - Browser/client language settings
3. **Query Parameter** - `?lang=es` in URL
4. **Cookie** - Persistent locale preference
5. **Default Fallback** - Configured default locale

### Priority Example

```python
# Request with multiple locale sources:
# - User preference: es
# - Accept-Language: fr-FR,en-US;q=0.9
# - Query parameter: ?lang=de
# - Cookie: it

# Result: es (user preference wins)
```

## Accept-Language Header Parsing

The middleware properly parses Accept-Language headers with quality values:

```
Accept-Language: fr-FR,en-US;q=0.9,es;q=0.8,de;q=0.7
```

Parsing logic:
1. Extracts all language codes and quality values
2. Sorts by quality value (highest first)
3. Tries full locale (e.g., `en-US`) and base language (e.g., `en`)
4. Returns first match from supported locales

### Examples

```python
# Accept-Language: en-US,es;q=0.9,fr;q=0.8
# Supported: ["en", "es", "fr"]
# Result: en

# Accept-Language: de-DE,es;q=0.9,en;q=0.8
# Supported: ["en", "fr"]
# Result: en (highest quality of supported locales)

# Accept-Language: it-IT,de;q=0.9
# Supported: ["en", "es", "fr"]
# Result: en (fallback to default)
```

## Using Translations

### In-Memory Translation Provider

```python
TRANSLATIONS = {
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

def load_translations(locale: str) -> dict[str, str]:
    return TRANSLATIONS.get(locale, TRANSLATIONS["en"])

app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],
    translation_provider=load_translations,
)

@app.get("/welcome")
async def welcome(request: Request):
    translations = request.state.translations
    return {"message": translations.get("welcome", "Welcome")}
```

### File-Based Translation Provider

```python
import json
from pathlib import Path

def load_translations_from_file(locale: str) -> dict[str, str]:
    """Load translations from JSON files."""
    translation_file = Path(f"translations/{locale}.json")

    if translation_file.exists():
        with open(translation_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback to English
    with open("translations/en.json", "r", encoding="utf-8") as f:
        return json.load(f)

app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],
    translation_provider=load_translations_from_file,
)
```

### Database Translation Provider

```python
async def load_translations_from_db(locale: str) -> dict[str, str]:
    """Load translations from database."""
    async with get_db_session() as session:
        result = await session.execute(
            select(Translation.key, Translation.value)
            .where(Translation.locale == locale)
        )
        return dict(result.all())

# Note: For async providers, you'll need to adapt the middleware
# or use sync wrapper
```

## Custom Locale Detection

### Business Logic Detection

```python
def custom_locale_detector(request: Request) -> str:
    """Custom locale detection with business logic."""

    # 1. Check tenant-specific locale
    if hasattr(request.state, "tenant"):
        tenant_locale = getattr(request.state.tenant, "default_locale", None)
        if tenant_locale:
            return tenant_locale

    # 2. Check custom header
    if custom_locale := request.headers.get("x-app-locale"):
        return custom_locale

    # 3. Check subdomain (e.g., es.example.com)
    host = request.headers.get("host", "")
    if "." in host:
        subdomain = host.split(".")[0]
        if subdomain in ["en", "es", "fr"]:
            return subdomain

    # 4. Default to English
    return "en"

app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],
    locale_detector=custom_locale_detector,
)
```

### GeoIP-Based Detection

```python
def geoip_locale_detector(request: Request) -> str:
    """Detect locale based on client IP geolocation."""
    client_ip = request.client.host

    # Use GeoIP library to detect country
    country_code = get_country_from_ip(client_ip)

    # Map country to locale
    country_locale_map = {
        "US": "en",
        "GB": "en",
        "ES": "es",
        "MX": "es",
        "FR": "fr",
        "DE": "de",
    }

    return country_locale_map.get(country_code, "en")
```

## Request State Access

The middleware populates `request.state` with locale information:

```python
@app.get("/api/info")
async def get_info(request: Request):
    # Access detected locale
    locale = request.state.locale  # e.g., "es"

    # Access translations (if provider configured)
    translations = request.state.translations  # dict[str, str]

    return {
        "locale": locale,
        "message": translations.get("info_message", "Information"),
    }
```

## Response Headers and Cookies

### Content-Language Header

The middleware automatically sets the `Content-Language` header on all responses:

```
Content-Language: es
```

This informs clients of the response language for proper handling.

### Locale Cookie

The middleware sets a locale cookie for persistence:

```
Set-Cookie: locale=es; Max-Age=2592000; Path=/; SameSite=Lax
```

Cookie properties:
- **Name**: Configurable (default: `locale`)
- **Max-Age**: Configurable in days (default: 30 days)
- **HttpOnly**: `false` (allows JavaScript access for UI)
- **SameSite**: `lax` (CSRF protection)
- **Secure**: `false` (set to `true` in production with HTTPS)

## User Preference Integration

For authenticated users, the middleware can read preferred language from the user object:

```python
# User model with preferred_language
class User(BaseModel):
    id: int
    email: str
    preferred_language: str = "en"

# Authentication middleware sets request.state.user
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Authenticate user
    user = await get_current_user(request)
    request.state.user = user

    response = await call_next(request)
    return response

# I18n middleware reads user.preferred_language
app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],
    use_user_preference=True,  # Enable user preference detection
)

@app.post("/profile/language")
async def update_language(language: str, request: Request):
    """Update user's preferred language."""
    user = request.state.user
    await update_user_language(user.id, language)

    return {
        "message": "Language preference updated",
        "language": language,
    }
```

## Selective Detection

You can disable specific detection sources for security or business requirements:

```python
app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],

    # Disable query parameter (prevent URL manipulation)
    use_query_param=False,

    # Enable only specific sources
    use_accept_language=True,
    use_cookie=True,
    use_user_preference=True,
)
```

## Middleware Order

The I18n middleware should be placed appropriately in the middleware chain:

```python
# Recommended order
app.add_middleware(CORSMiddleware, ...)       # 1. CORS (outermost)
app.add_middleware(RateLimitMiddleware, ...)  # 2. Rate limiting
app.add_middleware(SecurityMiddleware, ...)   # 3. Security headers
app.add_middleware(AuthMiddleware, ...)       # 4. Authentication
app.add_middleware(I18nMiddleware, ...)       # 5. I18n (after auth)
app.add_middleware(RequestIDMiddleware, ...)  # 6. Request ID
app.add_middleware(LoggingMiddleware, ...)    # 7. Logging
```

**Important**: I18n middleware should run after authentication middleware if you want to use user preferences.

## Testing

### Testing Locale Detection

```python
from fastapi.testclient import TestClient

def test_locale_from_header():
    client = TestClient(app)
    response = client.get(
        "/hello",
        headers={"Accept-Language": "es-ES,en;q=0.9"}
    )
    assert response.json()["locale"] == "es"

def test_locale_from_query():
    client = TestClient(app)
    response = client.get("/hello?lang=fr")
    assert response.json()["locale"] == "fr"

def test_locale_from_cookie():
    client = TestClient(app)
    client.cookies.set("locale", "de")
    response = client.get("/hello")
    assert response.json()["locale"] == "de"

def test_locale_priority():
    """User preference should override header."""
    client = TestClient(app)
    # Mock user with Spanish preference
    # Query parameter: de
    # Header: fr
    response = client.get(
        "/hello?lang=de",
        headers={"Accept-Language": "fr"}
    )
    # Should use user preference (es) if authenticated
```

### Testing Translation Provider

```python
def test_translations_loaded():
    client = TestClient(app)
    response = client.get(
        "/welcome",
        headers={"Accept-Language": "es"}
    )
    assert "Bienvenido" in response.json()["message"]

def test_translation_fallback():
    """Test fallback when translation missing."""
    client = TestClient(app)
    response = client.get(
        "/nonexistent",
        headers={"Accept-Language": "es"}
    )
    # Should fall back to English translation
    assert response.status_code == 200
```

## Production Considerations

### Performance

- **Translation Caching**: Cache translations to avoid repeated loading
- **Lazy Loading**: Load translations on-demand for better startup time
- **CDN Integration**: Serve translations from CDN for distributed systems

```python
from functools import lru_cache

@lru_cache(maxsize=10)
def load_translations_cached(locale: str) -> dict[str, str]:
    """Cached translation loading for better performance."""
    return load_translations_from_file(locale)
```

### Security

- **Input Validation**: Only accept supported locales
- **Disable Query Params**: Consider disabling query parameter detection in production
- **Secure Cookies**: Enable `secure` flag for HTTPS deployments

```python
app.add_middleware(
    I18nMiddleware,
    default_locale="en",
    supported_locales=["en", "es", "fr"],
    use_query_param=False,  # More secure
)
```

### Monitoring

Log locale usage for analytics:

```python
import logging

logger = logging.getLogger(__name__)

def logging_locale_detector(request: Request) -> str:
    """Custom detector with logging."""
    locale = default_locale_detector(request)

    logger.info(
        "Locale detected",
        extra={
            "locale": locale,
            "user_id": getattr(request.state.user, "id", None),
            "path": request.url.path,
        }
    )

    return locale
```

## Integration Examples

### With Pydantic Response Models

```python
from pydantic import BaseModel

class LocalizedResponse(BaseModel):
    message: str
    locale: str

@app.get("/status", response_model=LocalizedResponse)
async def get_status(request: Request):
    translations = request.state.translations
    return LocalizedResponse(
        message=translations.get("status_ok", "Status OK"),
        locale=request.state.locale,
    )
```

### With GraphQL

```python
import strawberry
from strawberry.fastapi import GraphQLRouter

@strawberry.type
class Query:
    @strawberry.field
    def hello(self, info) -> str:
        request = info.context["request"]
        translations = request.state.translations
        return translations.get("hello", "Hello")

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)

app.include_router(graphql_app, prefix="/graphql")
```

### With Background Tasks

```python
from fastapi import BackgroundTasks

async def send_email(user_email: str, locale: str):
    """Send localized email."""
    translations = load_translations(locale)
    subject = translations.get("email_subject", "Email Subject")
    # Send email with localized content
    await email_service.send(user_email, subject, ...)

@app.post("/subscribe")
async def subscribe(
    email: str,
    background_tasks: BackgroundTasks,
    request: Request,
):
    locale = request.state.locale
    background_tasks.add_task(send_email, email, locale)

    translations = request.state.translations
    return {
        "message": translations.get("subscribed", "Subscribed successfully"),
    }
```

## Troubleshooting

### Locale Not Detected

1. **Check middleware order**: I18n middleware must run after authentication
2. **Verify supported locales**: Ensure requested locale is in `supported_locales`
3. **Check header format**: Accept-Language header must follow standard format
4. **Enable debug logging**: Log detection process to identify issues

### Translations Not Loading

1. **Verify provider function**: Ensure translation provider returns dict
2. **Check file paths**: Verify translation files exist and are readable
3. **Handle exceptions**: Add error handling to translation provider
4. **Test provider separately**: Unit test translation loading logic

### Cookie Not Set

1. **Check response**: Verify middleware runs after endpoint handler
2. **HTTPS requirement**: Some browsers require HTTPS for cookies
3. **SameSite attribute**: Adjust SameSite setting for cross-site scenarios
4. **Cookie size**: Ensure locale code doesn't exceed cookie size limits

## Advanced Topics

### Multi-Region Support

```python
# Support region-specific locales
supported_locales = [
    "en-US", "en-GB",  # English variants
    "es-ES", "es-MX",  # Spanish variants
    "fr-FR", "fr-CA",  # French variants
]

app.add_middleware(
    I18nMiddleware,
    default_locale="en-US",
    supported_locales=supported_locales,
)
```

### Fallback Chain

```python
def load_translations_with_fallback(locale: str) -> dict[str, str]:
    """Load translations with region fallback."""
    # Try full locale (e.g., en-US)
    if translations := try_load(locale):
        return translations

    # Try base language (e.g., en)
    if "-" in locale:
        base_locale = locale.split("-")[0]
        if translations := try_load(base_locale):
            return translations

    # Fallback to default
    return load_translations("en")
```

### Dynamic Locale Loading

```python
async def load_translations_async(locale: str) -> dict[str, str]:
    """Asynchronously load translations from external service."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://translations.example.com/{locale}.json"
        )
        return response.json()
```

## API Reference

### I18nMiddleware

```python
class I18nMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        default_locale: str = "en",
        supported_locales: list[str] | None = None,
        locale_detector: Callable[[Request], str] | None = None,
        translation_provider: Callable[[str], dict[str, str]] | None = None,
        cookie_name: str = "locale",
        cookie_max_age: int = 30 * 24 * 60 * 60,
        query_param: str = "lang",
        use_accept_language: bool = True,
        use_user_preference: bool = True,
        use_query_param: bool = True,
        use_cookie: bool = True,
    ) -> None:
        """Initialize I18n middleware."""
```

### create_i18n_middleware

```python
def create_i18n_middleware(
    default_locale: str = "en",
    supported_locales: list[str] | None = None,
    translation_provider: Callable[[str], dict[str, str]] | None = None,
    cookie_name: str = "locale",
    cookie_max_age_days: int = 30,
    query_param: str = "lang",
    use_accept_language: bool = True,
    use_user_preference: bool = True,
    use_query_param: bool = True,
    use_cookie: bool = True,
) -> type[I18nMiddleware]:
    """Factory function to create configured I18n middleware."""
```

### I18nSettings

```python
class I18nSettings(BaseSettings):
    enabled: bool = False
    default_locale: str = "en"
    supported_locales: list[str] = ["en", "es", "fr"]
    cookie_name: str = "locale"
    cookie_max_age_days: int = 30
    query_param: str = "lang"
    use_accept_language: bool = True
    use_user_preference: bool = True
    use_query_param: bool = True
    use_cookie: bool = True
```

## References

- [RFC 7231 - Accept-Language](https://tools.ietf.org/html/rfc7231#section-5.3.5)
- [ISO 639-1 Language Codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)
- [Content-Language Header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Language)
- [FastAPI Middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [Starlette Middleware](https://www.starlette.io/middleware/)

## Complete Usage Examples

The following examples demonstrate various ways to use the I18n middleware in your FastAPI applications.

### Example 1: Basic Setup with Default Configuration

The simplest setup with default middleware configuration.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_basic_setup() -> FastAPI:
    """Basic I18n middleware setup with defaults.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
    )

    @app.get("/hello")
    async def hello(request: Request):
        locale = request.state.locale
        return {"locale": locale, "message": f"Hello in {locale}"}

    return app
```

### Example 2: Using Factory Function with Settings

Create a middleware instance using the factory function for cleaner configuration.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import create_i18n_middleware

def example_with_factory(
    default_locale: str = "en",
    supported_locales: list[str] | None = None,
) -> FastAPI:
    """I18n middleware using factory function.

    Args:
        default_locale: Default locale
        supported_locales: List of supported locales

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    # Create middleware class with pre-configured settings
    middleware_class = create_i18n_middleware(
        default_locale=default_locale,
        supported_locales=supported_locales or ["en", "es", "fr"],
        cookie_max_age_days=30,
        query_param="lang",
    )

    app.add_middleware(middleware_class)

    @app.get("/status")
    async def status(request: Request):
        return {
            "locale": request.state.locale,
            "translations_available": bool(request.state.translations),
        }

    return app
```

### Example 3: Custom Translation Provider

Integrate a translation system with in-memory translations.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_with_translations() -> FastAPI:
    """I18n middleware with custom translation provider.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    # Simple in-memory translation provider
    TRANSLATIONS = {
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

    def load_translations(locale: str) -> dict[str, str]:
        """Load translations for the given locale.

        Args:
            locale: Locale code

        Returns:
            Dictionary of translations
        """
        return TRANSLATIONS.get(locale, TRANSLATIONS["en"])

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        translation_provider=load_translations,
    )

    @app.get("/welcome")
    async def welcome(request: Request):
        translations = request.state.translations
        return {"message": translations.get("welcome", "Welcome")}

    @app.get("/greet/{name}")
    async def greet(name: str, request: Request):
        translations = request.state.translations
        greeting = translations.get("hello", "Hello")
        return {"message": f"{greeting}, {name}!"}

    return app
```

### Example 4: Custom Locale Detector

Implement custom locale detection logic based on business requirements.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_with_custom_detector() -> FastAPI:
    """I18n middleware with custom locale detection logic.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    def custom_locale_detector(request: Request) -> str:
        """Custom locale detection with business logic.

        Args:
            request: FastAPI request

        Returns:
            Detected locale code
        """
        # Check for tenant-specific locale
        if hasattr(request.state, "tenant"):
            tenant_locale = getattr(request.state.tenant, "default_locale", None)
            if tenant_locale:
                return tenant_locale

        # Check custom header
        if custom_locale := request.headers.get("x-app-locale"):
            return custom_locale

        # Check subdomain (e.g., es.example.com)
        host = request.headers.get("host", "")
        if "." in host:
            subdomain = host.split(".")[0]
            if subdomain in ["en", "es", "fr"]:
                return subdomain

        # Default to English
        return "en"

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        locale_detector=custom_locale_detector,
    )

    @app.get("/info")
    async def info(request: Request):
        return {
            "locale": request.state.locale,
            "detection_method": "custom",
        }

    return app
```

### Example 5: Integration with Settings System

Load configuration from environment variables and settings.

```python
from fastapi import FastAPI, Request
from example_service.core.settings import get_i18n_settings
from example_service.app.middleware.i18n import create_i18n_middleware

def example_with_settings_integration() -> FastAPI:
    """I18n middleware integrated with settings system.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    # Load settings from environment/config
    i18n_settings = get_i18n_settings()

    if i18n_settings.enabled:
        middleware_class = create_i18n_middleware(
            default_locale=i18n_settings.default_locale,
            supported_locales=i18n_settings.supported_locales,
            cookie_name=i18n_settings.cookie_name,
            cookie_max_age_days=i18n_settings.cookie_max_age_days,
            query_param=i18n_settings.query_param,
            use_accept_language=i18n_settings.use_accept_language,
            use_user_preference=i18n_settings.use_user_preference,
            use_query_param=i18n_settings.use_query_param,
            use_cookie=i18n_settings.use_cookie,
        )
        app.add_middleware(middleware_class)

    @app.get("/config")
    async def config(request: Request):
        return {
            "i18n_enabled": i18n_settings.enabled,
            "current_locale": getattr(request.state, "locale", None),
            "supported_locales": i18n_settings.supported_locales,
        }

    return app
```

### Example 6: User Preferences with Database Storage

Integrate with user authentication to store and retrieve language preferences.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_with_user_preferences() -> FastAPI:
    """I18n middleware with user preference storage.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    # Mock user with preferred language
    class MockUser:
        def __init__(self, preferred_language: str = "en"):
            self.preferred_language = preferred_language

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr", "de", "it"],
        use_user_preference=True,  # Enable user preference detection
    )

    @app.get("/profile")
    async def profile(request: Request):
        # In real app, user would come from authentication middleware
        # For demo, we'll simulate it
        request.state.user = MockUser(preferred_language="es")

        return {
            "user_locale": request.state.user.preferred_language,
            "detected_locale": request.state.locale,
        }

    @app.post("/profile/locale")
    async def update_locale(locale: str, request: Request):
        """Update user's preferred locale.

        Args:
            locale: New locale preference
            request: FastAPI request

        Returns:
            Updated locale information
        """
        # In real app, update database
        if hasattr(request.state, "user"):
            request.state.user.preferred_language = locale

        return {
            "message": "Locale preference updated",
            "new_locale": locale,
        }

    return app
```

### Example 7: Selective Locale Detection

Disable specific detection sources for security or business needs.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_selective_detection() -> FastAPI:
    """I18n middleware with selective locale detection.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        # Disable query parameter detection (more secure)
        use_query_param=False,
        # Only use Accept-Language header and cookie
        use_accept_language=True,
        use_cookie=True,
        use_user_preference=False,
    )

    @app.get("/secure")
    async def secure_endpoint(request: Request):
        return {
            "locale": request.state.locale,
            "note": "Locale cannot be overridden via query parameter",
        }

    return app
```

### Example 8: Testing Locale Detection Priority

Demonstrate and test the locale detection priority system.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_test_locale_priority() -> FastAPI:
    """Demonstrate locale detection priority.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr", "de"],
    )

    @app.get("/test-priority")
    async def test_priority(request: Request):
        """Test locale detection priority.

        Priority order:
        1. User preference
        2. Accept-Language header
        3. Query parameter (?lang=es)
        4. Cookie (locale)
        5. Default (en)
        """
        detection_info = {
            "detected_locale": request.state.locale,
            "user_preference": getattr(
                getattr(request.state, "user", None), "preferred_language", None
            ),
            "accept_language": request.headers.get("accept-language"),
            "query_param": request.query_params.get("lang"),
            "cookie": request.cookies.get("locale"),
            "default": "en",
        }
        return detection_info

    return app
```

### Example 9: Real-World API with Translations

Complete example showing a realistic API with multi-language support.

```python
from fastapi import FastAPI, Request
from example_service.app.middleware.i18n import I18nMiddleware

def example_real_world_api() -> FastAPI:
    """Real-world API example with I18n support.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI()

    # Translation data
    MESSAGES = {
        "en": {
            "user_created": "User created successfully",
            "user_updated": "User updated successfully",
            "user_deleted": "User deleted successfully",
            "validation_error": "Validation error",
            "not_found": "Resource not found",
        },
        "es": {
            "user_created": "Usuario creado exitosamente",
            "user_updated": "Usuario actualizado exitosamente",
            "user_deleted": "Usuario eliminado exitosamente",
            "validation_error": "Error de validación",
            "not_found": "Recurso no encontrado",
        },
        "fr": {
            "user_created": "Utilisateur créé avec succès",
            "user_updated": "Utilisateur mis à jour avec succès",
            "user_deleted": "Utilisateur supprimé avec succès",
            "validation_error": "Erreur de validation",
            "not_found": "Ressource introuvable",
        },
    }

    def get_translations(locale: str) -> dict[str, str]:
        return MESSAGES.get(locale, MESSAGES["en"])

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        translation_provider=get_translations,
    )

    @app.post("/users")
    async def create_user(request: Request):
        translations = request.state.translations
        return {
            "status": "success",
            "message": translations.get("user_created", "User created"),
        }

    @app.get("/users/{user_id}")
    async def get_user(user_id: int, request: Request):
        translations = request.state.translations
        # Simulate user not found
        if user_id > 100:
            return {
                "status": "error",
                "message": translations.get("not_found", "Not found"),
            }
        return {"status": "success", "user_id": user_id}

    return app
```

## Support

For issues, questions, or contributions, please refer to the project repository.
