"""Internationalization (I18n) middleware for multi-language support.

This middleware handles locale detection from multiple sources and manages
translation context for each request. It supports:
- User preferences (authenticated user's preferred language)
- Accept-Language header parsing
- Query parameter override (?lang=es)
- Cookie-based persistence
- Configurable default fallback

The middleware stores the detected locale in request.state.locale and optionally
loads translations via a translation_provider callable.

Priority order for locale detection:
1. User preference (request.state.user.preferred_language)
2. Query parameter (?lang=es) - explicit override
3. Accept-Language header (with quality value parsing)
4. Cookie (locale cookie)
5. Default fallback

Example:
    from example_service.app.middleware.i18n import I18nMiddleware

    app.add_middleware(
        I18nMiddleware,
        default_locale="en",
        supported_locales=["en", "es", "fr"],
        translation_provider=load_translations,
    )

    @app.get("/hello")
    async def hello(request: Request):
        locale = request.state.locale
        translations = request.state.translations
        return {"message": translations.get("hello", "Hello")}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request, Response


class I18nMiddleware(BaseHTTPMiddleware):
    """Middleware to handle internationalization for each request.

    This middleware detects the appropriate locale for each request based on
    multiple sources (user preference, headers, query params, cookies) and
    makes it available throughout the request lifecycle.

    Attributes:
        default_locale: Default locale to use when detection fails
        supported_locales: List of supported locale codes
        locale_detector: Custom locale detection function
        translation_provider: Optional function to load translations
        cookie_name: Name of the locale cookie
        cookie_max_age: Cookie expiration in seconds
        query_param: Query parameter name for locale override
    """

    def __init__(
        self,
        app: Any,
        default_locale: str = "en",
        supported_locales: list[str] | None = None,
        locale_detector: Callable[[Request], str] | None = None,
        translation_provider: Callable[[str], dict[str, str]] | None = None,
        cookie_name: str = "locale",
        cookie_max_age: int = 30 * 24 * 60 * 60,  # 30 days
        query_param: str = "lang",
        use_accept_language: bool = True,
        use_user_preference: bool = True,
        use_query_param: bool = True,
        use_cookie: bool = True,
    ) -> None:
        """Initialize I18n middleware.

        Args:
            app: FastAPI application instance
            default_locale: Default locale to use (e.g., 'en', 'es', 'fr')
            supported_locales: List of supported locale codes
            locale_detector: Custom function to detect locale from request
            translation_provider: Function to provide translations for locale
            cookie_name: Name of the cookie for storing locale preference
            cookie_max_age: Cookie expiration in seconds (default: 30 days)
            query_param: Query parameter name for locale override
            use_accept_language: Enable Accept-Language header parsing
            use_user_preference: Enable user.preferred_language detection
            use_query_param: Enable query parameter detection
            use_cookie: Enable cookie-based detection
        """
        super().__init__(app)
        self.default_locale = default_locale
        self.supported_locales = supported_locales or ["en"]
        self.locale_detector = locale_detector or self._default_locale_detector
        self.translation_provider = translation_provider
        self.cookie_name = cookie_name
        self.cookie_max_age = cookie_max_age
        self.query_param = query_param
        self.use_accept_language = use_accept_language
        self.use_user_preference = use_user_preference
        self.use_query_param = use_query_param
        self.use_cookie = use_cookie

    def _default_locale_detector(self, request: Request) -> str:
        """Default locale detection from multiple sources.

        Priority order:
        1. User preference (if authenticated)
        2. Query parameter (explicit override)
        3. Accept-Language header
        4. Cookie
        5. Default fallback

        Args:
            request: FastAPI request object

        Returns:
            Detected locale code
        """
        # 1. Check user preference if available (highest priority)
        if self.use_user_preference and hasattr(request.state, "user") and request.state.user:
            user_locale: str | None = getattr(request.state.user, "preferred_language", None)
            if user_locale and user_locale in self.supported_locales:
                return str(user_locale)

        # 2. Check query parameter (explicit override should have high priority)
        if self.use_query_param:
            query_locale = request.query_params.get(self.query_param)
            if query_locale and query_locale in self.supported_locales:
                return query_locale

        # 3. Check Accept-Language header
        if self.use_accept_language:
            accept_language = request.headers.get("accept-language", "")
            if accept_language:
                locale = self._parse_accept_language(accept_language)
                if locale:
                    return locale

        # 4. Check cookie
        if self.use_cookie:
            cookie_locale = request.cookies.get(self.cookie_name)
            if cookie_locale and cookie_locale in self.supported_locales:
                return cookie_locale

        # 5. Return default fallback
        return self.default_locale

    def _parse_accept_language(self, accept_language: str) -> str | None:
        """Parse Accept-Language header and find best matching locale.

        Handles format: "en-US,es;q=0.9,fr;q=0.8"
        - Extracts language codes and quality values
        - Sorts by quality value (highest first)
        - Returns first supported locale

        Args:
            accept_language: Accept-Language header value

        Returns:
            Best matching supported locale or None if no match
        """
        # Parse language preferences with quality values
        preferences = []

        for lang_part_raw in accept_language.split(","):
            lang_part = lang_part_raw.strip()
            if not lang_part:
                continue

            # Split language and quality value (e.g., "en-US;q=0.9")
            parts = lang_part.split(";")
            lang = parts[0].strip()

            # Extract quality value (default: 1.0)
            quality = 1.0
            if len(parts) > 1:
                for param in parts[1:]:
                    if param.strip().startswith("q="):
                        try:
                            quality = float(param.strip()[2:])
                        except ValueError:
                            quality = 1.0
                        break

            # Handle language-region format (e.g., en-US -> en)
            # Try both full locale and base language code
            lang_codes = [lang.lower()]
            if "-" in lang:
                base_lang = lang.split("-")[0].lower()
                lang_codes.append(base_lang)

            preferences.append((quality, lang_codes))

        # Sort by quality value (descending)
        preferences.sort(key=lambda x: x[0], reverse=True)

        # Find first supported language
        for _quality, lang_codes in preferences:
            for lang_code in lang_codes:
                if lang_code in self.supported_locales:
                    return lang_code

        return None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request and set locale.

        Args:
            request: FastAPI request
            call_next: Next middleware in chain

        Returns:
            Response with locale information
        """
        # Detect locale for this request
        locale = self.locale_detector(request)

        # Ensure locale is supported (fallback to default if not)
        if locale not in self.supported_locales:
            locale = self.default_locale

        # Store locale in request state for easy access
        request.state.locale = locale

        # Get translations for this locale if provider is available
        if self.translation_provider:
            try:
                request.state.translations = self.translation_provider(locale)
            except Exception:
                # If translation loading fails, provide empty dict
                request.state.translations = {}
        else:
            request.state.translations = {}

        # Process request
        response = await call_next(request)

        # Set Content-Language header to inform clients of the response language
        response.headers["Content-Language"] = locale

        # Set locale cookie for future requests (30 days, accessible by JS)
        # This allows UI to read and display the current locale
        response.set_cookie(
            key=self.cookie_name,
            value=locale,
            max_age=self.cookie_max_age,
            httponly=False,  # Allow JavaScript access for UI
            samesite="lax",  # CSRF protection while allowing normal navigation
            secure=False,  # Set to True in production with HTTPS
        )

        return response


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
    """Factory function to create configured I18n middleware.

    This is a convenience function that creates a middleware class with
    pre-configured settings, useful when integrating with settings objects.

    Args:
        default_locale: Default locale to use
        supported_locales: List of supported locale codes
        translation_provider: Function to provide translations
        cookie_name: Name of the locale cookie
        cookie_max_age_days: Cookie expiration in days
        query_param: Query parameter name for locale override
        use_accept_language: Enable Accept-Language header parsing
        use_user_preference: Enable user.preferred_language detection
        use_query_param: Enable query parameter detection
        use_cookie: Enable cookie-based detection

    Returns:
        Configured I18nMiddleware class

    Example:
        from example_service.core.settings import get_i18n_settings

        i18n_settings = get_i18n_settings()
        middleware_class = create_i18n_middleware(
            default_locale=i18n_settings.default_locale,
            supported_locales=i18n_settings.supported_locales,
        )
        app.add_middleware(middleware_class)
    """

    class ConfiguredI18nMiddleware(I18nMiddleware):
        """Pre-configured I18n middleware with settings from factory."""

        def __init__(self, app: Any) -> None:
            super().__init__(
                app,
                default_locale=default_locale,
                supported_locales=supported_locales,
                translation_provider=translation_provider,
                cookie_name=cookie_name,
                cookie_max_age=cookie_max_age_days * 24 * 60 * 60,
                query_param=query_param,
                use_accept_language=use_accept_language,
                use_user_preference=use_user_preference,
                use_query_param=use_query_param,
                use_cookie=use_cookie,
            )

    return ConfiguredI18nMiddleware
