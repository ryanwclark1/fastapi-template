"""Example external API client.

Demonstrates how to create an external service client using the BaseHTTPClient.
This can be used as a template for integrating with third-party APIs.
"""

from __future__ import annotations

import logging
from typing import Any

from example_service.infra.external.base_client import BaseHTTPClient

logger = logging.getLogger(__name__)


class ExampleAPIClient(BaseHTTPClient):
    """Client for Example External API.

    Example implementation of an external API client that demonstrates:
    - Using the BaseHTTPClient
    - Custom methods for specific endpoints
    - Error handling
    - Response transformation

    Usage:
            async with ExampleAPIClient() as client:
            data = await client.get_resource("123")
            result = await client.create_resource({"name": "test"})
    """

    def __init__(
        self,
        api_url: str = "https://api.example.com",
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize Example API client.

        Args:
            api_url: Base URL for the API.
            api_key: API key for authentication.
            timeout: Request timeout in seconds.
        """
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key

        super().__init__(
            base_url=api_url,
            timeout=timeout,
            headers=headers,
        )

    async def get_resource(self, resource_id: str) -> dict[str, Any]:
        """Get resource by ID.

        Args:
            resource_id: Resource identifier.

        Returns:
            Resource data.

        Example:
                    resource = await client.get_resource("123")
            print(resource["name"])
        """
        return await self.get(f"/resources/{resource_id}")

    async def list_resources(
        self, page: int = 1, page_size: int = 20, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """List resources with pagination.

        Args:
            page: Page number (1-indexed).
            page_size: Number of items per page.
            filters: Optional filters to apply.

        Returns:
            Paginated list of resources.

        Example:
                    result = await client.list_resources(
                page=1,
                page_size=10,
                filters={"status": "active"}
            )
            print(f"Total: {result['total']}")
            for resource in result['items']:
                print(resource['name'])
        """
        params = {
            "page": page,
            "page_size": page_size,
        }

        if filters:
            params.update(filters)

        return await self.get("/resources", params=params)

    async def create_resource(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new resource.

        Args:
            data: Resource data.

        Returns:
            Created resource data.

        Example:
                    resource = await client.create_resource({
                "name": "My Resource",
                "type": "example",
                "metadata": {"key": "value"}
            })
            print(f"Created resource: {resource['id']}")
        """
        return await self.post("/resources", json=data)

    async def update_resource(self, resource_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing resource.

        Args:
            resource_id: Resource identifier.
            data: Updated resource data.

        Returns:
            Updated resource data.

        Example:
                    resource = await client.update_resource(
                "123",
                {"name": "Updated Name"}
            )
        """
        return await self.put(f"/resources/{resource_id}", json=data)

    async def delete_resource(self, resource_id: str) -> None:
        """Delete a resource.

        Args:
            resource_id: Resource identifier.

        Example:
                    await client.delete_resource("123")
        """
        await self.delete(f"/resources/{resource_id}")

    async def health_check(self) -> bool:
        """Check if the external API is healthy.

        Returns:
            True if API is healthy, False otherwise.

        Example:
                    is_healthy = await client.health_check()
            if is_healthy:
                print("API is operational")
        """
        try:
            response = await self.get("/health")
            return response.get("status") == "ok"
        except Exception as e:
            logger.error(
                f"External API health check failed: {e}",
                extra={"exception": str(e)},
            )
            return False
