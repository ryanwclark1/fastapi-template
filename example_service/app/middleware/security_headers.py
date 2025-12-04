"""Security headers middleware for protecting against common web vulnerabilities.

This middleware adds comprehensive HTTP security headers to all responses,
protecting against common web vulnerabilities including:

- XSS (Cross-Site Scripting) attacks
- Clickjacking attacks
- MIME-type sniffing
- Information leakage
- Man-in-the-middle attacks

The middleware implements security best practices and follows OWASP guidelines
for HTTP security headers. Configuration is environment-aware, with stricter
policies in production.

Example Usage:
    from example_service.app.middleware import SecurityHeadersMiddleware

    # Add to FastAPI application
    app.add_middleware(SecurityHeadersMiddleware)

    # Or with custom configuration
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=True,
        hsts_max_age=31536000,
        enable_csp=True,
        server_header=None  # Remove Server header
    )

    # Use helper function for error handlers
    from example_service.app.middleware.security_headers import get_security_headers

    @app.exception_handler(500)
    async def server_error_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=get_security_headers(include_hsts=True, include_csp=True)
        )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    """Pure ASGI middleware to add security-related HTTP headers to responses.

    This middleware adds various security headers to protect against:
    - XSS attacks (X-XSS-Protection, Content-Security-Policy)
    - Clickjacking (X-Frame-Options)
    - MIME type sniffing (X-Content-Type-Options)
    - Information disclosure (X-Powered-By removal)
    - Man-in-the-middle attacks (Strict-Transport-Security)
    - Cross-domain policy control (X-Permitted-Cross-Domain-Policies)

    Performance: Pure ASGI implementation provides 40-50% better performance
    compared to BaseHTTPMiddleware by avoiding unnecessary request/response
    object creation and working directly with ASGI messages.

    References:
        https://owasp.org/www-project-secure-headers/
        https://securityheaders.com/

    Example:
            app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)
    """

    def __init__(
        self,
        app: ASGIApp | None = None,
        enable_hsts: bool | None = None,
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        enable_csp: bool | None = None,
        csp_directives: dict[str, str] | None = None,
        enable_frame_options: bool = True,
        frame_options: str = "DENY",
        enable_xss_protection: bool = True,
        enable_content_type_options: bool = True,
        enable_referrer_policy: bool = True,
        referrer_policy: str = "strict-origin-when-cross-origin",
        enable_permissions_policy: bool = True,
        permissions_policy: dict[str, list[str]] | None = None,
        server_header: str | None | bool = False,
        environment: str | None = None,
    ) -> None:
        """Initialize security headers middleware.

        Args:
            app: The ASGI application. Can be None for factory functions.
            enable_hsts: Whether to enable Strict-Transport-Security header.
                If None, auto-enabled in production (default: True for backward compat).
            hsts_max_age: Max age for HSTS in seconds (default: 1 year).
            hsts_include_subdomains: Include subdomains in HSTS.
            hsts_preload: Enable HSTS preload (requires max-age >= 1 year).
            enable_csp: Whether to enable Content-Security-Policy header.
                If None, auto-enabled in production (default: True for backward compat).
            csp_directives: Custom CSP directives (uses environment-aware defaults if None).
            enable_frame_options: Whether to enable X-Frame-Options header.
            frame_options: Frame options value (DENY, SAMEORIGIN).
            enable_xss_protection: Whether to enable X-XSS-Protection header.
            enable_content_type_options: Whether to enable X-Content-Type-Options header.
            enable_referrer_policy: Whether to enable Referrer-Policy header.
            referrer_policy: Referrer policy value.
            enable_permissions_policy: Whether to enable Permissions-Policy header.
            permissions_policy: Custom permissions policy directives.
            server_header: Custom Server header value. None removes it, False keeps default,
                string sets custom value (default: False for backward compat).
            environment: Environment name ('development'|'staging'|'production'|'test').
                Used for automatic strictness adjustment. Defaults to 'development' if not provided.

        Note:
            For environment-aware security, pass environment='production'.
        """
        self.app = app

        # Determine if we're in production for environment-aware defaults
        self._is_production = self._determine_production_mode(environment)
        self._environment = environment or "development"

        # HSTS configuration - auto-enable in production if not explicitly set
        self.enable_hsts = enable_hsts if enable_hsts is not None else (self._is_production or True)
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload

        # CSP configuration - auto-enable in production if not explicitly set
        self.enable_csp = enable_csp if enable_csp is not None else (self._is_production or True)
        self.csp_directives = csp_directives or self._get_default_csp()

        # Frame options
        self.enable_frame_options = enable_frame_options
        self.frame_options = frame_options

        # Other headers
        self.enable_xss_protection = enable_xss_protection
        self.enable_content_type_options = enable_content_type_options
        self.enable_referrer_policy = enable_referrer_policy
        self.referrer_policy = referrer_policy
        self.enable_permissions_policy = enable_permissions_policy
        self.permissions_policy = permissions_policy or self._default_permissions_policy()

        # Server header handling
        self.server_header = server_header

        # Validate app is provided (except for factory functions)
        if app is None:
            # This is allowed for factory functions that will set app later
            pass

        # Log initialization with environment info
        logger.info(
            "Security headers middleware initialized",
            extra={
                "hsts_enabled": self.enable_hsts,
                "csp_enabled": self.enable_csp,
                "frame_options": self.frame_options,
                "environment": self._environment,
                "is_production": self._is_production,
            },
        )

    @staticmethod
    def _determine_production_mode(environment: str | None) -> bool:
        """Determine if running in production mode.

        Args:
            environment: Environment name.

        Returns:
            True if in production mode.
        """
        if environment is not None:
            return environment.lower() == "production"
        return False

    def _get_default_csp(self) -> dict[str, str]:
        """Get environment-aware default Content-Security-Policy directives.

        Returns stricter policies in production, more permissive in development.

        Returns:
            Dictionary of CSP directive names to values.

        Note:
            Production policy is restrictive but allows common use cases.
            Development policy allows Swagger UI, ReDoc, and WebSocket connections.
        """
        if self._is_production:
            # Stricter policy for production
            return {
                "default-src": "'self'",
                # Allow AsyncAPI/Swagger bundles that rely on AJV's eval-based validators
                "script-src": "'self' 'unsafe-eval'",
                "style-src": "'self' 'unsafe-inline'",  # 'unsafe-inline' for dynamic styles
                "img-src": "'self' data: https:",
                "font-src": "'self' data:",
                "connect-src": "'self'",
                "frame-ancestors": "'none'",
                "base-uri": "'self'",
                "form-action": "'self'",
                "upgrade-insecure-requests": "",  # Directive with no value
            }
        # More permissive for development (allows Swagger UI, ReDoc, WebSocket)
        swagger_cdn = "https://cdn.jsdelivr.net"
        unpkg_cdn = "https://unpkg.com"
        google_fonts_css = "https://fonts.googleapis.com"
        google_fonts_assets = "https://fonts.gstatic.com"
        return {
            "default-src": "'self'",
            # Allow Swagger docs (jsDelivr) + AsyncAPI docs (unpkg) to load bundled assets
            "script-src": f"'self' 'unsafe-inline' 'unsafe-eval' {swagger_cdn} {unpkg_cdn}",
            "style-src": f"'self' 'unsafe-inline' {swagger_cdn} {unpkg_cdn} {google_fonts_css}",
            "img-src": "'self' data: https:",
            "font-src": f"'self' data: {swagger_cdn} {google_fonts_assets}",
            "connect-src": f"'self' ws: wss: {swagger_cdn}",  # ws/wss for WebSocket
            "frame-ancestors": "'self'",  # Allow same-origin framing in dev
            "base-uri": "'self'",
            "form-action": "'self'",
            "worker-src": "'self' blob:",
        }

    @staticmethod
    def _default_csp_directives() -> dict[str, str]:
        """Get default Content-Security-Policy directives.

        DEPRECATED: Use _get_default_csp() instead for environment-aware policies.

        These directives allow Swagger UI and ReDoc documentation to function
        by permitting 'unsafe-inline' and 'unsafe-eval'. Use strict CSP in
        production with docs disabled.

        Returns:
            Dictionary of CSP directives.
        """
        swagger_cdn = "https://cdn.jsdelivr.net"
        unpkg_cdn = "https://unpkg.com"
        google_fonts_css = "https://fonts.googleapis.com"
        google_fonts_assets = "https://fonts.gstatic.com"
        return {
            "default-src": "'self'",
            # Allow Swagger docs (jsDelivr) + AsyncAPI docs (unpkg) to load bundled assets
            "script-src": (f"'self' 'unsafe-inline' 'unsafe-eval' {swagger_cdn} {unpkg_cdn}"),
            "style-src": (f"'self' 'unsafe-inline' {swagger_cdn} {unpkg_cdn} {google_fonts_css}"),
            "img-src": "'self' data: https:",
            "font-src": f"'self' data: {swagger_cdn} {google_fonts_assets}",
            "connect-src": f"'self' {swagger_cdn}",
            "frame-ancestors": "'none'",
            "base-uri": "'self'",
            "form-action": "'self'",
            "worker-src": "'self' blob:",
        }

    @staticmethod
    def _strict_csp_directives() -> dict[str, str]:
        """Get strict Content-Security-Policy directives for production.

        These directives do NOT include 'unsafe-inline' or 'unsafe-eval',
        providing maximum XSS protection. Use when API documentation is
        disabled in production (APP_DISABLE_DOCS=true).

        Note: Swagger UI requires 'unsafe-eval' to function, so this CSP
        will break documentation pages. Only use when docs are disabled.

        Returns:
            Dictionary of strict CSP directives.
        """
        return {
            "default-src": "'self'",
            "script-src": "'self'",
            "style-src": "'self'",
            "img-src": "'self' data:",
            "font-src": "'self'",
            "connect-src": "'self'",
            "frame-ancestors": "'none'",
            "base-uri": "'self'",
            "form-action": "'self'",
            "worker-src": "'self' blob:",
        }

    @staticmethod
    def _default_permissions_policy() -> dict[str, list[str]]:
        """Get default Permissions-Policy directives.

        Denies most browser features by default for enhanced security while
        avoiding user agent warnings from unsupported directives.
        """
        return {
            "camera": [],  # Deny camera
            "display-capture": [],  # Deny display capture
            "fullscreen": ["self"],  # Allow fullscreen for same origin
            "geolocation": [],  # Deny geolocation
            "microphone": [],  # Deny microphone
            "payment": [],  # Deny payment
            "picture-in-picture": [],  # Deny picture-in-picture
            "publickey-credentials-get": [],  # Deny WebAuthn
            "screen-wake-lock": [],  # Deny screen wake lock
            "usb": [],  # Deny USB
        }

    def _build_hsts_header(self) -> str:
        """Build Strict-Transport-Security header value.

        Returns:
            HSTS header value.
        """
        parts = [f"max-age={self.hsts_max_age}"]
        if self.hsts_include_subdomains:
            parts.append("includeSubDomains")
        if self.hsts_preload:
            parts.append("preload")
        return "; ".join(parts)

    def _build_csp_header(self) -> str:
        """Build Content-Security-Policy header value from directives.

        Handles both directives with values and valueless directives
        (e.g., upgrade-insecure-requests).

        Returns:
            CSP header value string.
        """
        parts = []
        for directive, value in self.csp_directives.items():
            if value:
                parts.append(f"{directive} {value}")
            else:
                # Directive with no value (like upgrade-insecure-requests)
                parts.append(directive)
        return "; ".join(parts)

    def _build_permissions_policy_header(self) -> str:
        """Build Permissions-Policy header value.

        Controls browser features and APIs that can be used. This helps
        prevent malicious features from being enabled.

        Returns:
            Permissions-Policy header value string.

        Format:
            feature=() to deny
            feature=(self) to allow same origin
            feature=(origin1 origin2) to allow specific origins
        """
        policies = []
        for feature, allowlist in self.permissions_policy.items():
            if not allowlist:
                # Empty allowlist means deny
                policies.append(f"{feature}=()")
            else:
                # Format: feature=(origin1 origin2)
                origins = " ".join(allowlist)
                policies.append(f"{feature}=({origins})")
        return ", ".join(policies)

    def _build_security_headers(self) -> dict[str, str]:
        """Build all security headers based on enabled settings.

        Returns:
            Dictionary of header names and values to add to responses.
        """
        headers: dict[str, str] = {}

        # HTTP Strict Transport Security (HSTS)
        if self.enable_hsts:
            headers["Strict-Transport-Security"] = self._build_hsts_header()

        # Content Security Policy (CSP)
        if self.enable_csp:
            headers["Content-Security-Policy"] = self._build_csp_header()

        # X-Frame-Options - Prevents clickjacking
        if self.enable_frame_options:
            headers["X-Frame-Options"] = self.frame_options

        # X-Content-Type-Options - Prevents MIME type sniffing
        if self.enable_content_type_options:
            headers["X-Content-Type-Options"] = "nosniff"

        # X-XSS-Protection - Legacy XSS protection (mostly superseded by CSP)
        if self.enable_xss_protection:
            headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy - Controls referrer information
        if self.enable_referrer_policy:
            headers["Referrer-Policy"] = self.referrer_policy

        # Permissions-Policy - Controls browser features
        if self.enable_permissions_policy:
            headers["Permissions-Policy"] = self._build_permissions_policy_header()

        # X-Permitted-Cross-Domain-Policies - Control cross-domain policy files
        headers["X-Permitted-Cross-Domain-Policies"] = "none"

        return headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request and inject security headers into response.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        # Validate app is set
        if self.app is None:
            raise RuntimeError("SecurityHeadersMiddleware.app must be set before use")

        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Build security headers dictionary once per request
        security_headers = self._build_security_headers()

        async def send_with_security_headers(message: Message) -> None:
            """Wrap send to inject security headers and handle Server header.

            Args:
                message: ASGI message to send.
            """
            if message["type"] == "http.response.start":
                # Inject security headers into response
                headers = MutableHeaders(scope=message)

                # Add all security headers
                for key, value in security_headers.items():
                    headers.append(key, value)

                # Remove X-Powered-By header if present (information disclosure)
                if "x-powered-by" in headers:
                    del headers["x-powered-by"]

                # Handle Server header
                if self.server_header is None:
                    # None = remove Server header
                    if "server" in headers:
                        del headers["server"]
                elif self.server_header is not False:
                    # String = set custom Server header
                    # Type narrowing: at this point server_header must be str
                    assert isinstance(self.server_header, str), "server_header must be str here"
                    headers["server"] = self.server_header
                # False = keep default Server header (do nothing)

            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def create_security_headers_middleware(
    debug: bool = False,
    environment: str | None = None,
) -> SecurityHeadersMiddleware:
    """Create security headers middleware with appropriate settings.

    In debug mode or development environment, headers are relaxed to allow
    easier development. In production, stricter policies are applied.

    Args:
        debug: Whether the application is in debug mode (deprecated, use environment).
        environment: Environment name ('development'|'staging'|'production'|'test').
            If not provided, infers from debug parameter.

    Returns:
        Configured SecurityHeadersMiddleware instance.

    Example:
        from example_service.app.middleware.security_headers import (
            create_security_headers_middleware
        )

        app = FastAPI()
        settings = get_app_settings()

        # Environment-aware (recommended)
        middleware = create_security_headers_middleware(
            environment=settings.environment
        )

        # Or using debug flag (legacy)
        middleware = create_security_headers_middleware(debug=settings.debug)

        app.add_middleware(SecurityHeadersMiddleware, **vars(middleware))
    """
    # Determine environment from parameters
    if environment is None:
        environment = "development" if debug else "production"

    # Relaxed CSP for development (allows Swagger UI, ReDoc)
    if debug or environment in ("development", "test"):
        csp_directives = {
            "default-src": "'self'",
            "script-src": "'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com",
            "style-src": "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com",
            "img-src": "'self' data: https: http:",
            "font-src": "'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com",
            "connect-src": "'self' ws: wss:",
            "frame-ancestors": "'self'",
            "base-uri": "'self'",
            "form-action": "'self'",
            "worker-src": "'self' blob:",
        }
        # Don't enable HSTS in development (allows HTTP)
        enable_hsts = False
    else:
        # Use environment-aware defaults (will auto-detect production)
        csp_directives = None  # Let middleware use _get_default_csp()
        enable_hsts = None  # Let middleware auto-enable in production

    return SecurityHeadersMiddleware(
        app=None,  # Will be set by FastAPI
        enable_hsts=enable_hsts,
        hsts_max_age=31536000,  # 1 year
        hsts_include_subdomains=True,
        hsts_preload=False,  # Enable manually after testing
        enable_csp=True,
        csp_directives=csp_directives,
        enable_frame_options=True,
        frame_options="DENY",
        enable_xss_protection=True,
        enable_content_type_options=True,
        enable_referrer_policy=True,
        referrer_policy="strict-origin-when-cross-origin",
        enable_permissions_policy=True,
        permissions_policy=None,  # Use defaults
        server_header=None,  # Remove Server header
        environment=environment,
    )


def get_security_headers(
    *,
    include_hsts: bool = False,
    include_csp: bool = False,
    csp_directives: dict[str, str] | None = None,
) -> dict[str, str]:
    """Get security headers as a dictionary.

    Useful for adding headers to specific responses or error handlers where
    the middleware may not apply (e.g., early error responses, custom exception
    handlers).

    Args:
        include_hsts: Include HSTS header (only use for HTTPS responses).
        include_csp: Include CSP header.
        csp_directives: Custom CSP directives. If None and include_csp=True,
            uses production-safe defaults.

    Returns:
        Dictionary of security headers.

    Example:
        from fastapi import Response
        from fastapi.responses import JSONResponse
        from example_service.app.middleware.security_headers import (
            get_security_headers
        )

        @app.exception_handler(500)
        async def server_error_handler(request, exc):
            headers = get_security_headers(include_hsts=True, include_csp=True)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers=headers,
            )

        @app.get("/api/v1/data")
        async def get_data():
            headers = get_security_headers(include_hsts=True)
            return Response(
                content="data",
                headers=headers,
            )
    """
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Permitted-Cross-Domain-Policies": "none",
    }

    if include_hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    if include_csp:
        if csp_directives:
            # Build CSP from provided directives
            parts = []
            for directive, value in csp_directives.items():
                if value:
                    parts.append(f"{directive} {value}")
                else:
                    parts.append(directive)
            headers["Content-Security-Policy"] = "; ".join(parts)
        else:
            # Use production-safe default CSP
            headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "upgrade-insecure-requests"
            )

    return headers


__all__ = [
    "SecurityHeadersMiddleware",
    "create_security_headers_middleware",
    "get_security_headers",
]
