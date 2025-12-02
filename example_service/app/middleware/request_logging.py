"""Request/response logging middleware with PII masking capabilities.

This middleware is responsible for logging only. Metrics collection is handled
by MetricsMiddleware to avoid duplication.

Key Features:
- Structured request/response logging with correlation IDs
- PII masking with configurable patterns
- Request/response body logging with sensitive data redaction
- Client IP detection through proxy headers (X-Forwarded-For, X-Real-IP)
- Enhanced context enrichment (user agent, user/tenant context, request size)
- Security event detection (optional)
- Performance metrics tracking
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from starlette.middleware.base import BaseHTTPMiddleware

from example_service.infra.logging.context import set_log_context

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request, Response
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)
SLOW_REQUEST_THRESHOLD = 5.0

# Security event detection patterns
SECURITY_PATTERNS = {
    "sql_injection": re.compile(
        r"(\bunion\b.*\bselect\b|\bor\b.*=.*|\bdrop\b.*\btable\b)", re.IGNORECASE
    ),
    "xss": re.compile(r"(<script|javascript:|onerror=|onload=)", re.IGNORECASE),
    "path_traversal": re.compile(r"(\.\./|\.\.\\|%2e%2e)", re.IGNORECASE),
    "command_injection": re.compile(r"(;|\||&|\$\(|`)", re.IGNORECASE),
}

_tracking: Any
try:
    from example_service.tasks import tracking as _task_tracking

    _tracking = _task_tracking
except Exception:  # pragma: no cover - optional dependency

    class _TrackingStub:
        @staticmethod
        def track_api_call(**_: Any) -> None:
            return

        @staticmethod
        def track_slow_request(**_: Any) -> None:
            return

    _tracking = _TrackingStub()

tracking: Any = _tracking


class PIIMasker:
    """Utility class for masking PII in request/response data.

    Masks sensitive information like emails, phone numbers, credit cards,
    SSNs, API keys, and custom patterns.

    Example:
            masker = PIIMasker()
        masked_data = masker.mask_dict({
            "email": "user@example.com",
            "phone": "555-123-4567",
            "name": "John Doe"
        })
        # Result: {"email": "***@***.com", "phone": "***-***-4567", "name": "John Doe"}
    """

    # Regex patterns for common PII
    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    PHONE_PATTERN = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
    SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
    API_KEY_PATTERN = re.compile(r"\b[A-Za-z0-9]{32,}\b")

    # Common sensitive field names
    SENSITIVE_FIELDS: ClassVar[set[str]] = {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "auth",
        "credit_card",
        "creditcard",
        "card_number",
        "cvv",
        "ssn",
        "social_security",
        "tax_id",
        "driver_license",
        "x-api-key",
    }

    def __init__(
        self,
        mask_char: str = "*",
        preserve_domain: bool = True,
        preserve_last_4: bool = True,
        custom_patterns: dict[str, re.Pattern] | None = None,
        custom_fields: set[str] | None = None,
    ) -> None:
        """Initialize PII masker.

        Args:
            mask_char: Character to use for masking (default: "*")
            preserve_domain: Keep domain visible in emails (default: True)
            preserve_last_4: Keep last 4 digits visible in phone/cards (default: True)
            custom_patterns: Additional regex patterns for masking
            custom_fields: Additional sensitive field names
        """
        self.mask_char = mask_char
        self.preserve_domain = preserve_domain
        self.preserve_last_4 = preserve_last_4
        self.custom_patterns = custom_patterns or {}
        self.sensitive_fields = self.SENSITIVE_FIELDS | (custom_fields or set())

    def _mask_sensitive_field(self, field: str, value: Any) -> Any:
        """Mask value based on known sensitive field semantics."""
        if value is None:
            return None
        if not isinstance(value, str):
            return self.mask_char * 8

        if field in {"email"}:
            return self.mask_email(value)
        if field in {"phone"}:
            return self.mask_phone(value)
        if field in {"credit_card", "creditcard", "card_number"}:
            return self.mask_credit_card(value)
        if field in {"authorization", "cookie", "api_key", "x-api-key"}:
            return self.mask_char * 8
        if field in {"ssn"}:
            return self.mask_char * len(value)
        return self.mask_char * 8

    def mask_email(self, email: str) -> str:
        """Mask email address.

        Args:
            email: Email address to mask

        Returns:
            Masked email (e.g., "***@***.com" or "u***@example.com")
        """
        if "@" not in email:
            return self.mask_char * len(email)

        local, domain = email.split("@", 1)

        if self.preserve_domain:
            masked_local = (
                local[0] + self.mask_char * (len(local) - 1) if len(local) > 1 else self.mask_char
            )
            return f"{masked_local}@{domain}"
        else:
            return f"{self.mask_char * 3}@{self.mask_char * 3}.com"

    def mask_phone(self, phone: str) -> str:
        """Mask phone number.

        Args:
            phone: Phone number to mask

        Returns:
            Masked phone (e.g., "***-***-4567")
        """
        digits = re.sub(r"\D", "", phone)

        if self.preserve_last_4 and len(digits) >= 4:
            masked = self.mask_char * (len(digits) - 4) + digits[-4:]
        else:
            masked = self.mask_char * len(digits)

        # Preserve original formatting
        result = ""
        digit_idx = 0
        for char in phone:
            if char.isdigit():
                result += masked[digit_idx] if digit_idx < len(masked) else self.mask_char
                digit_idx += 1
            else:
                result += char

        return result

    def mask_credit_card(self, card: str) -> str:
        """Mask credit card number.

        Args:
            card: Credit card number to mask

        Returns:
            Masked card (e.g., "****-****-****-1234")
        """
        digits = re.sub(r"\D", "", card)

        if self.preserve_last_4 and len(digits) >= 4:
            masked = self.mask_char * (len(digits) - 4) + digits[-4:]
        else:
            masked = self.mask_char * len(digits)

        # Preserve original formatting
        result = ""
        digit_idx = 0
        for char in card:
            if char.isdigit():
                result += masked[digit_idx] if digit_idx < len(masked) else self.mask_char
                digit_idx += 1
            else:
                result += char

        return result

    def mask_string(self, value: str) -> str:
        """Mask PII patterns in a string.

        Args:
            value: String potentially containing PII

        Returns:
            String with PII masked
        """
        # Mask emails
        value = self.EMAIL_PATTERN.sub(lambda m: self.mask_email(m.group()), value)

        # Mask credit cards (before phone to avoid false positives)
        value = self.CREDIT_CARD_PATTERN.sub(lambda m: self.mask_credit_card(m.group()), value)

        # Mask phone numbers
        value = self.PHONE_PATTERN.sub(lambda m: self.mask_phone(m.group()), value)

        # Mask SSNs
        value = self.SSN_PATTERN.sub(lambda m: self.mask_char * len(m.group()), value)

        # Mask custom patterns
        for pattern in self.custom_patterns.values():
            value = pattern.sub(self.mask_char * 8, value)

        return value

    def mask_dict(
        self, data: dict[str, Any], depth: int = 0, max_depth: int = 10
    ) -> dict[str, Any]:
        """Recursively mask PII in dictionary.

        Args:
            data: Dictionary to mask
            depth: Current recursion depth
            max_depth: Maximum recursion depth

        Returns:
            Dictionary with PII masked
        """
        if depth > max_depth:
            return {"_truncated": "max_depth_exceeded"}

        masked: dict[str, Any] = {}

        for key, value in data.items():
            key_lower = key.lower()

            if value is None:
                masked[key] = None
            # Completely mask sensitive fields
            elif key_lower in self.sensitive_fields:
                masked[key] = self._mask_sensitive_field(key_lower, value)
            elif isinstance(value, str):
                masked[key] = self.mask_string(value)
            elif isinstance(value, dict):
                masked[key] = self.mask_dict(value, depth + 1, max_depth)
            elif isinstance(value, list):
                masked[key] = [
                    self.mask_dict(item, depth + 1, max_depth)
                    if isinstance(item, dict)
                    else self.mask_string(item)
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                masked[key] = value

        return masked


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for detailed request/response logging with PII masking.

    Logs request and response details while automatically masking sensitive
    information. Useful for debugging, auditing, and monitoring.

    Note:
        This middleware handles logging only. Metrics collection (API calls,
        slow requests, response sizes) is handled separately by MetricsMiddleware
        to avoid duplication.

    Attributes:
        masker: PIIMasker instance for masking sensitive data
        log_request_body: Whether to log request bodies
        log_response_body: Whether to log response bodies
        max_body_size: Maximum body size to log (bytes)
        exempt_paths: Paths to exclude from logging
        detect_security_events: Whether to detect and log security events
        sensitive_fields: Additional sensitive field names for redaction

    Example:
            app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            log_response_body=True,
            max_body_size=10000,
            detect_security_events=True
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        masker: PIIMasker | None = None,
        log_request_body: bool = True,
        log_response_body: bool = False,  # Can be expensive
        max_body_size: int = 10000,  # 10KB
        exempt_paths: list[str] | None = None,
        log_level: int = logging.INFO,
        detect_security_events: bool = False,  # Optional security detection
        sensitive_fields: list[str] | None = None,  # Additional sensitive fields
    ) -> None:
        """Initialize request logging middleware.

        Args:
            app: The ASGI application
            masker: PIIMasker instance (creates default if None)
            log_request_body: Whether to log request bodies
            log_response_body: Whether to log response bodies
            max_body_size: Maximum body size to log in bytes
            exempt_paths: Paths to exclude from detailed logging
            log_level: Logging level for request logs
            detect_security_events: Enable security event detection
            sensitive_fields: Additional sensitive field names for masking
        """
        super().__init__(app)
        self.masker = masker or PIIMasker()
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_size = max_body_size
        self.log_level = log_level
        self.detect_security_events = detect_security_events

        # Add custom sensitive fields to masker
        if sensitive_fields:
            self.masker.sensitive_fields = self.masker.sensitive_fields | set(sensitive_fields)

        self.exempt_paths = exempt_paths or [
            "/health",
            "/health/",
            "/health/ready",
            "/health/live",
            "/health/startup",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]

    def _is_exempt(self, path: str) -> bool:
        """Check if path is exempt from detailed logging.

        Args:
            path: Request path

        Returns:
            True if path is exempt
        """
        return any(path.startswith(exempt) for exempt in self.exempt_paths)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request with proxy header support.

        Checks proxy headers in order of preference:
        1. X-Forwarded-For (can contain multiple IPs, takes first)
        2. X-Real-IP
        3. X-Client-IP
        4. request.client.host (fallback)

        Args:
            request: FastAPI request

        Returns:
            Client IP address or "unknown"
        """
        # Check for common proxy headers
        for header in ["x-forwarded-for", "x-real-ip", "x-client-ip"]:
            ip = request.headers.get(header)
            if ip:
                # X-Forwarded-For can contain multiple IPs, take the first (client)
                return ip.split(",")[0].strip()

        # Fall back to client host
        if request.client:
            return request.client.host

        return "unknown"

    def _get_user_context(self, request: Request) -> dict[str, Any]:
        """Extract user and tenant context from request state.

        Args:
            request: FastAPI request

        Returns:
            Dictionary with user_id and tenant_id if available
        """
        context = {}

        # Get user context if available
        if hasattr(request.state, "user") and request.state.user:
            user = request.state.user
            if hasattr(user, "id"):
                context["user_id"] = str(user.id)
            elif hasattr(user, "user_id"):
                context["user_id"] = str(user.user_id)
            elif hasattr(user, "sub"):
                context["user_id"] = str(user.sub)

        # Get tenant context if available
        if hasattr(request.state, "tenant_id"):
            context["tenant_id"] = str(request.state.tenant_id)
        elif hasattr(request.state, "tenant") and request.state.tenant:
            tenant = request.state.tenant
            if hasattr(tenant, "id"):
                context["tenant_id"] = str(tenant.id)
            elif hasattr(tenant, "tenant_id"):
                context["tenant_id"] = str(tenant.tenant_id)

        return context

    def _detect_security_event(
        self,
        _request: Request,
        path: str,
        query_params: dict[str, Any],
        body_data: dict[str, Any] | None,
    ) -> list[str]:
        """Detect potential security threats in request.

        Args:
            request: FastAPI request
            path: Request path
            query_params: Query parameters
            body_data: Parsed body data

        Returns:
            List of detected security event types
        """
        if not self.detect_security_events:
            return []

        detected_events = []

        # Check path for suspicious patterns
        for event_type, pattern in SECURITY_PATTERNS.items():
            if pattern.search(path):
                detected_events.append(event_type)

        # Check query parameters
        query_string = str(query_params)
        for event_type, pattern in SECURITY_PATTERNS.items():
            if pattern.search(query_string) and event_type not in detected_events:
                detected_events.append(event_type)

        # Check body data
        if body_data:
            body_string = json.dumps(body_data)
            for event_type, pattern in SECURITY_PATTERNS.items():
                if pattern.search(body_string) and event_type not in detected_events:
                    detected_events.append(event_type)

        return detected_events

    def _should_log_body(self, content_type: str | None, body_size: int) -> bool:
        """Determine if body should be logged.

        Args:
            content_type: Content-Type header value
            body_size: Size of body in bytes

        Returns:
            True if body should be logged
        """
        if body_size > self.max_body_size:
            return False

        if not content_type:
            return False

        # Only log JSON and form data
        loggable_types = ["application/json", "application/x-www-form-urlencoded"]
        return any(ct in content_type.lower() for ct in loggable_types)

    async def _read_body(self, request: Request) -> tuple[bytes, dict[str, Any] | None]:
        """Read and parse request body.

        Args:
            request: FastAPI request

        Returns:
            Tuple of (raw_body, parsed_body)
        """
        body_bytes = await request.body()

        if not body_bytes:
            return body_bytes, None

        content_type = request.headers.get("content-type", "")

        try:
            if "application/json" in content_type:
                body_data = json.loads(body_bytes.decode("utf-8"))
                return body_bytes, self.masker.mask_dict(body_data)
            elif "application/x-www-form-urlencoded" in content_type:
                # Parse form data
                form_str = body_bytes.decode("utf-8")
                form_data: dict[str, str] = {}
                for param in form_str.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        form_data[key] = value
                    else:
                        form_data[param] = ""
                return body_bytes, self.masker.mask_dict(form_data)
        except Exception as e:
            logger.debug(f"Failed to parse request body: {e}")

        return body_bytes, None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Log request and response with PII masking.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response from the handler
        """
        # Skip detailed logging for exempt paths
        if self._is_exempt(request.url.path):
            response = await call_next(request)
            return response

        start_time = time.time()
        request_id = getattr(request.state, "request_id", None)
        if not request_id:
            header_request_id = request.headers.get("x-request-id")
            request_id = header_request_id or str(uuid.uuid4())
            request.state.request_id = request_id
            request.scope.setdefault("state", {})["request_id"] = request_id

        # Get enhanced client IP (with proxy support)
        client_ip = self._get_client_ip(request)

        # Add logging-specific context fields
        # Note: request_id is already set by RequestIDMiddleware
        # We only add HTTP-specific fields here for logging purposes
        set_log_context(
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
        )

        # Get user agent
        user_agent = request.headers.get("user-agent", "")

        # Get request size
        request_size = 0
        content_length_header = request.headers.get("content-length")
        if content_length_header:
            with contextlib.suppress(ValueError, TypeError):
                request_size = int(content_length_header)

        # Get user and tenant context
        user_context = self._get_user_context(request)

        # Log request details with enhanced context
        log_data: dict[str, Any] = {
            "event": "request",
            "event_type": "request_start",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": client_ip,
            "user_agent": user_agent,
            "request_size": request_size,
        }

        # Add user/tenant context if available
        log_data.update(user_context)

        # Mask sensitive headers
        headers = dict(request.headers)
        masked_headers = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in {"authorization", "cookie", "x-api-key"}:
                masked_headers[key] = self.masker.mask_char * 8
            else:
                masked_headers[key] = value

        log_data["headers"] = masked_headers

        # Log request body if enabled and detect security events
        parsed_body = None
        if self.log_request_body:
            content_type = request.headers.get("content-type")
            content_length = int(request.headers.get("content-length", 0))

            if self._should_log_body(content_type, content_length):
                body_bytes, parsed_body = await self._read_body(request)

                if parsed_body:
                    log_data["body"] = parsed_body
                    log_data["body_size"] = len(body_bytes)

                # Store body for route handler to read
                async def receive() -> dict[str, Any]:
                    return {"type": "http.request", "body": body_bytes}

                request._receive = receive

        # Detect security events if enabled
        security_events = self._detect_security_event(
            request, request.url.path, dict(request.query_params), parsed_body
        )
        if security_events:
            log_data["security_events"] = security_events
            # Log security events at WARNING level separately
            logger.warning(
                "Potential security event detected",
                extra={
                    "event": "security_event",
                    "event_type": "security_alert",
                    "request_id": request_id,
                    "path": request.url.path,
                    "client_ip": client_ip,
                    "security_events": security_events,
                    **user_context,
                },
            )

        logger.log(self.log_level, "HTTP Request", extra=log_data)

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            duration = time.time() - start_time

            error_log_data = {
                "event": "request_error",
                "event_type": "request_error",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration": round(duration, 3),
                "duration_ms": round(duration * 1000, 2),
                "client_ip": client_ip,
                "user_agent": user_agent,
                "exception": str(e),
                "exception_type": type(e).__name__,
            }
            error_log_data.update(user_context)

            logger.error(
                "Request failed",
                extra=error_log_data,
                exc_info=True,
            )

            if hasattr(tracking, "track_api_call"):
                tracking.track_api_call(
                    path=request.url.path,
                    method=request.method,
                    status_code=500,
                    duration=duration,
                    success=False,
                )
            raise

        # Calculate duration for logging purposes
        # Note: Duration metrics are tracked separately by MetricsMiddleware
        duration = time.time() - start_time

        # Log response with enhanced context
        response_log: dict[str, Any] = {
            "event": "response",
            "event_type": "request_complete",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration": round(duration, 3),
            "duration_ms": round(duration * 1000, 2),
            "client_ip": client_ip,
            "user_agent": user_agent,
            "request_size": request_size,
        }

        # Add user/tenant context
        response_log.update(user_context)

        # Add response size if available
        response_size = 0
        if hasattr(response, "headers") and "content-length" in response.headers:
            try:
                response_size = int(response.headers["content-length"])
                response_log["response_size"] = response_size
            except (ValueError, TypeError):
                pass

        # Determine log level based on status code
        if response.status_code >= 500:
            response_log_level = logging.ERROR
        elif response.status_code >= 400:
            response_log_level = logging.WARNING
        else:
            response_log_level = self.log_level

        logger.log(response_log_level, "HTTP Response", extra=response_log)

        if hasattr(tracking, "track_api_call"):
            tracking.track_api_call(
                path=request.url.path,
                method=request.method,
                status_code=response.status_code,
                duration=duration,
                success=True,
            )

        if duration >= SLOW_REQUEST_THRESHOLD and hasattr(tracking, "track_slow_request"):
            tracking.track_slow_request(
                path=request.url.path,
                method=request.method,
                duration=duration,
            )

        return response
