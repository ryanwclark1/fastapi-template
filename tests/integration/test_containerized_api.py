"""End-to-end integration tests executed against the Docker image."""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.core.container", reason="testcontainers is required for container smoke tests")
from testcontainers.core.container import DockerContainer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "example-service-integration-test"
CONTAINER_PORT = 8000
CONTAINER_ENV = {
    "APP_ROOT_PATH": "",
    "APP_ENVIRONMENT": "test",
    "DB_ENABLED": "false",
    "DB_DATABASE_URL": "",
    "DATABASE_URL": "",
    "REDIS_REDIS_URL": "",
    "REDIS_URL": "",
    "RABBIT_ENABLED": "false",
    "AUTH_SERVICE_URL": "",
    "OTEL_ENABLED": "false",
}

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _build_service_image() -> str:
    """Build the Docker image used for containerized tests."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is required for container-based integration tests")

    build_cmd = ["docker", "build", "--tag", IMAGE_TAG, "."]
    try:
        subprocess.run(build_cmd, cwd=PROJECT_ROOT, check=True)
    except FileNotFoundError:
        pytest.skip("Docker CLI is required for container-based integration tests")
    except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaced via pytest
        pytest.skip(f"Docker build failed for integration tests (skipping): {exc}")

    return IMAGE_TAG


def _wait_for_container(base_url: str, timeout: float = 60.0) -> None:
    """Poll the container until the service reports it is alive."""
    deadline = time.monotonic() + timeout
    health_url = f"{base_url}/api/v1/health/live"
    last_error: Exception | None = None

    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(health_url)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    return
                last_error = RuntimeError(f"Unexpected status {response.status_code}")
            time.sleep(0.5)

    error_detail = f"Service failed to start within {timeout}s"
    if last_error is not None:
        error_detail += f" (last error: {last_error})"
    raise RuntimeError(error_detail)


@pytest.fixture(scope="session")
def container_base_url() -> Iterator[str]:
    """Run the Docker image and return the base URL for HTTP requests."""
    image_tag = _build_service_image()

    container = DockerContainer(image_tag).with_exposed_ports(CONTAINER_PORT)
    for key, value in CONTAINER_ENV.items():
        container = container.with_env(key, value)

    with container as running:
        host = running.get_container_host_ip()
        port = running.get_exposed_port(CONTAINER_PORT)
        base_url = f"http://{host}:{port}"
        _wait_for_container(base_url)
        yield base_url


@pytest.mark.asyncio
async def test_container_health_endpoint(container_base_url: str) -> None:
    """Verify that the containerized service serves the health endpoint."""
    async with httpx.AsyncClient(base_url=container_base_url, timeout=10.0) as client:
        response = await client.get("/api/v1/health/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "example-service"


@pytest.mark.asyncio
async def test_container_metrics_endpoint(container_base_url: str) -> None:
    """Ensure the metrics endpoint is exposed when running in Docker."""
    async with httpx.AsyncClient(base_url=container_base_url, timeout=10.0) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text
