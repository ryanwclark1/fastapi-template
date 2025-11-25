"""Request/response logging middleware with PII masking capabilities.

This middleware is responsible for logging only. Metrics collection is handled
by MetricsMiddleware to avoid duplication.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from example_service.infra.logging.context import set_log_context

logger = logging.getLogger(__name__)


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
    SENSITIVE_FIELDS = {
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
        "auth",
        "credit_card",
        "creditcard",
        "card_number",
        "cvv",
        "ssn",
        "social_security",
        "tax_id",
        "driver_license",
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

        masked = {}

        for key, value in data.items():
            key_lower = key.lower()

            # Completely mask sensitive fields
            if key_lower in self.sensitive_fields:
                masked[key] = self.mask_char * 8
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

    Example:
            app.add_middleware(
            RequestLoggingMiddleware,
            log_request_body=True,
            log_response_body=True,
            max_body_size=10000
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
        """
        super().__init__(app)
        self.masker = masker or PIIMasker()
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_size = max_body_size
        self.log_level = log_level
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
                form_data = dict(
                    param.split("=", 1) if "=" in param else (param, "")
                    for param in form_str.split("&")
                )
                return body_bytes, self.masker.mask_dict(form_data)
        except Exception as e:
            logger.debug(f"Failed to parse request body: {e}")

        return body_bytes, None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
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
            return await call_next(request)

        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")

        # Add logging-specific context fields
        # Note: request_id is already set by RequestIDMiddleware
        # We only add HTTP-specific fields here for logging purposes
        set_log_context(
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
        )

        # Log request details
        log_data: dict[str, Any] = {
            "event": "request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }

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

        # Log request body if enabled
        if self.log_request_body:
            content_type = request.headers.get("content-type")
            content_length = int(request.headers.get("content-length", 0))

            if self._should_log_body(content_type, content_length):
                body_bytes, parsed_body = await self._read_body(request)

                if parsed_body:
                    log_data["body"] = parsed_body
                    log_data["body_size"] = len(body_bytes)

                # Store body for route handler to read
                async def receive():
                    return {"type": "http.request", "body": body_bytes}

                request._receive = receive

        logger.log(self.log_level, "HTTP Request", extra=log_data)

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            duration = time.time() - start_time

            logger.error(
                "Request failed",
                extra={
                    "event": "request_error",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration": duration,
                    "exception": str(e),
                    "exception_type": type(e).__name__,
                },
                exc_info=True,
            )
            raise

        # Calculate duration for logging purposes
        # Note: Duration metrics are tracked separately by MetricsMiddleware
        duration = time.time() - start_time

        # Log response
        response_log: dict[str, Any] = {
            "event": "response",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration": round(duration, 3),
        }

        # Add response size if available
        if hasattr(response, "headers") and "content-length" in response.headers:
            response_size = int(response.headers["content-length"])
            response_log["response_size"] = response_size

        logger.log(self.log_level, "HTTP Response", extra=response_log)

        return response
