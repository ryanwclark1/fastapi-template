"""Security headers middleware for protecting against common web vulnerabilities."""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from example_service.core.settings import get_app_settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security-related HTTP headers to responses.

    This middleware adds various security headers to protect against:
    - XSS attacks (X-XSS-Protection, Content-Security-Policy)
    - Clickjacking (X-Frame-Options)
    - MIME type sniffing (X-Content-Type-Options)
    - Information disclosure (X-Powered-By removal)
    - Man-in-the-middle attacks (Strict-Transport-Security)
    - Cross-domain policy control (X-Permitted-Cross-Domain-Policies)

    References:
        https://owasp.org/www-project-secure-headers/
        https://securityheaders.com/

    Example:
        ```python
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        enable_hsts: bool = True,
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        enable_csp: bool = True,
        csp_directives: dict[str, str] | None = None,
        enable_frame_options: bool = True,
        frame_options: str = "DENY",
        enable_xss_protection: bool = True,
        enable_content_type_options: bool = True,
        enable_referrer_policy: bool = True,
        referrer_policy: str = "strict-origin-when-cross-origin",
        enable_permissions_policy: bool = True,
        permissions_policy: dict[str, list[str]] | None = None,
    ) -> None:
        """Initialize security headers middleware.

        Args:
            app: The ASGI application.
            enable_hsts: Whether to enable Strict-Transport-Security header.
            hsts_max_age: Max age for HSTS in seconds (default: 1 year).
            hsts_include_subdomains: Include subdomains in HSTS.
            hsts_preload: Enable HSTS preload.
            enable_csp: Whether to enable Content-Security-Policy header.
            csp_directives: Custom CSP directives (default: restrictive policy).
            enable_frame_options: Whether to enable X-Frame-Options header.
            frame_options: Frame options value (DENY, SAMEORIGIN, or ALLOW-FROM uri).
            enable_xss_protection: Whether to enable X-XSS-Protection header.
            enable_content_type_options: Whether to enable X-Content-Type-Options header.
            enable_referrer_policy: Whether to enable Referrer-Policy header.
            referrer_policy: Referrer policy value.
            enable_permissions_policy: Whether to enable Permissions-Policy header.
            permissions_policy: Custom permissions policy directives.
        """
        super().__init__(app)
        self.enable_hsts = enable_hsts
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload
        self.enable_csp = enable_csp
        self.csp_directives = csp_directives or self._default_csp_directives()
        self.enable_frame_options = enable_frame_options
        self.frame_options = frame_options
        self.enable_xss_protection = enable_xss_protection
        self.enable_content_type_options = enable_content_type_options
        self.enable_referrer_policy = enable_referrer_policy
        self.referrer_policy = referrer_policy
        self.enable_permissions_policy = enable_permissions_policy
        self.permissions_policy = permissions_policy or self._default_permissions_policy()

    @staticmethod
    def _default_csp_directives() -> dict[str, str]:
        """Get default Content-Security-Policy directives.

        Returns:
            Dictionary of CSP directives.
        """
        return {
            "default-src": "'self'",
            "script-src": "'self' 'unsafe-inline' 'unsafe-eval'",  # Relaxed for API docs
            "style-src": "'self' 'unsafe-inline'",  # Relaxed for API docs
            "img-src": "'self' data: https:",
            "font-src": "'self' data:",
            "connect-src": "'self'",
            "frame-ancestors": "'none'",
            "base-uri": "'self'",
            "form-action": "'self'",
        }

    @staticmethod
    def _default_permissions_policy() -> dict[str, list[str]]:
        """Get default Permissions-Policy directives.

        Returns:
            Dictionary of permissions policy directives.
        """
        return {
            "geolocation": [],  # Deny geolocation
            "microphone": [],  # Deny microphone
            "camera": [],  # Deny camera
            "payment": [],  # Deny payment
            "usb": [],  # Deny USB
            "magnetometer": [],  # Deny magnetometer
            "gyroscope": [],  # Deny gyroscope
            "accelerometer": [],  # Deny accelerometer
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
        """Build Content-Security-Policy header value.

        Returns:
            CSP header value.
        """
        directives = []
        for directive, value in self.csp_directives.items():
            directives.append(f"{directive} {value}")
        return "; ".join(directives)

    def _build_permissions_policy_header(self) -> str:
        """Build Permissions-Policy header value.

        Returns:
            Permissions-Policy header value.
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

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Add security headers to response.

        Args:
            request: The incoming request.
            call_next: The next middleware or route handler.

        Returns:
            Response with security headers added.
        """
        # Call the next middleware/handler
        response = await call_next(request)

        # Add security headers

        # HTTP Strict Transport Security (HSTS)
        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = self._build_hsts_header()

        # Content Security Policy (CSP)
        if self.enable_csp:
            response.headers["Content-Security-Policy"] = self._build_csp_header()

        # X-Frame-Options - Prevents clickjacking
        if self.enable_frame_options:
            response.headers["X-Frame-Options"] = self.frame_options

        # X-Content-Type-Options - Prevents MIME type sniffing
        if self.enable_content_type_options:
            response.headers["X-Content-Type-Options"] = "nosniff"

        # X-XSS-Protection - Legacy XSS protection (mostly superseded by CSP)
        if self.enable_xss_protection:
            response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy - Controls referrer information
        if self.enable_referrer_policy:
            response.headers["Referrer-Policy"] = self.referrer_policy

        # Permissions-Policy - Controls browser features
        if self.enable_permissions_policy:
            response.headers["Permissions-Policy"] = (
                self._build_permissions_policy_header()
            )

        # X-Permitted-Cross-Domain-Policies - Control cross-domain policy files
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        # Remove X-Powered-By header if present (information disclosure)
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]

        return response


def create_security_headers_middleware(
    debug: bool = False,
) -> SecurityHeadersMiddleware:
    """Create security headers middleware with appropriate settings.

    In debug mode, some headers are relaxed to allow easier development.

    Args:
        debug: Whether the application is in debug mode.

    Returns:
        Configured SecurityHeadersMiddleware instance.

    Example:
        ```python
        app = FastAPI()
        settings = get_app_settings()
        middleware = create_security_headers_middleware(debug=settings.debug)
        app.add_middleware(SecurityHeadersMiddleware, **middleware_config)
        ```
    """
    # Relaxed CSP for development (allows Swagger UI, ReDoc)
    if debug:
        csp_directives = {
            "default-src": "'self'",
            "script-src": "'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
            "style-src": "'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            "img-src": "'self' data: https: http:",
            "font-src": "'self' data: https://cdn.jsdelivr.net",
            "connect-src": "'self'",
            "frame-ancestors": "'self'",
            "base-uri": "'self'",
            "form-action": "'self'",
        }
        # Don't enable HSTS in development (allows HTTP)
        enable_hsts = False
    else:
        csp_directives = SecurityHeadersMiddleware._default_csp_directives()
        enable_hsts = True

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
        permissions_policy=SecurityHeadersMiddleware._default_permissions_policy(),
    )
