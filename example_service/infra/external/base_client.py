"""Base HTTP client for external API integrations.

Provides a base class for external service clients with:
- Connection pooling
- Retry logic with exponential backoff
- Request/response logging
- Timeout configuration
- Error handling
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from example_service.core.settings import get_app_settings
from example_service.utils.retry import retry

logger = logging.getLogger(__name__)


class BaseHTTPClient:
    """Base HTTP client for external API integrations.

    Provides common functionality for making HTTP requests to external services
    with retry logic, timeout handling, and structured logging.

    Example:
        ```python
        class WeatherAPIClient(BaseHTTPClient):
            def __init__(self):
                super().__init__(
                    base_url="https://api.weather.com",
                    timeout=10.0
                )

            async def get_weather(self, city: str) -> dict:
                return await self.get(f"/weather/{city}")
        ```
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize HTTP client.

        Args:
            base_url: Base URL for the API.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.
            headers: Default headers to include in all requests.
        """
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_headers = headers or {}

        # Create async client with connection pooling
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers=self.default_headers,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
            ),
        )

    async def close(self) -> None:
        """Close the HTTP client and release connections."""
        await self.client.aclose()

    async def __aenter__(self) -> BaseHTTPClient:
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and close client."""
        await self.close()

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )
    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make GET request to external API.

        Args:
            path: API endpoint path.
            params: Query parameters.
            headers: Additional headers for this request.
            **kwargs: Additional arguments passed to httpx.

        Returns:
            JSON response data.

        Raises:
            httpx.HTTPError: On HTTP errors.
            httpx.TimeoutException: On timeout.
        """
        logger.info(
            f"GET request to {self.base_url}{path}",
            extra={"path": path, "params": params},
        )

        response = await self.client.get(path, params=params, headers=headers, **kwargs)

        logger.info(
            f"GET response from {self.base_url}{path}",
            extra={
                "path": path,
                "status_code": response.status_code,
                "duration_ms": response.elapsed.total_seconds() * 1000,
            },
        )

        response.raise_for_status()
        return response.json()

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )
    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make POST request to external API.

        Args:
            path: API endpoint path.
            json: JSON body data.
            data: Form data.
            headers: Additional headers for this request.
            **kwargs: Additional arguments passed to httpx.

        Returns:
            JSON response data.

        Raises:
            httpx.HTTPError: On HTTP errors.
            httpx.TimeoutException: On timeout.
        """
        logger.info(
            f"POST request to {self.base_url}{path}",
            extra={"path": path, "has_json": json is not None, "has_data": data is not None},
        )

        response = await self.client.post(
            path, json=json, data=data, headers=headers, **kwargs
        )

        logger.info(
            f"POST response from {self.base_url}{path}",
            extra={
                "path": path,
                "status_code": response.status_code,
                "duration_ms": response.elapsed.total_seconds() * 1000,
            },
        )

        response.raise_for_status()
        return response.json()

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )
    async def put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make PUT request to external API.

        Args:
            path: API endpoint path.
            json: JSON body data.
            headers: Additional headers for this request.
            **kwargs: Additional arguments passed to httpx.

        Returns:
            JSON response data.

        Raises:
            httpx.HTTPError: On HTTP errors.
            httpx.TimeoutException: On timeout.
        """
        logger.info(
            f"PUT request to {self.base_url}{path}",
            extra={"path": path},
        )

        response = await self.client.put(path, json=json, headers=headers, **kwargs)

        logger.info(
            f"PUT response from {self.base_url}{path}",
            extra={
                "path": path,
                "status_code": response.status_code,
                "duration_ms": response.elapsed.total_seconds() * 1000,
            },
        )

        response.raise_for_status()
        return response.json()

    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )
    async def delete(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Make DELETE request to external API.

        Args:
            path: API endpoint path.
            headers: Additional headers for this request.
            **kwargs: Additional arguments passed to httpx.

        Returns:
            JSON response data if available, None otherwise.

        Raises:
            httpx.HTTPError: On HTTP errors.
            httpx.TimeoutException: On timeout.
        """
        logger.info(
            f"DELETE request to {self.base_url}{path}",
            extra={"path": path},
        )

        response = await self.client.delete(path, headers=headers, **kwargs)

        logger.info(
            f"DELETE response from {self.base_url}{path}",
            extra={
                "path": path,
                "status_code": response.status_code,
                "duration_ms": response.elapsed.total_seconds() * 1000,
            },
        )

        response.raise_for_status()

        # DELETE may return no content
        if response.status_code == 204:
            return None

        try:
            return response.json()
        except Exception:
            return None
