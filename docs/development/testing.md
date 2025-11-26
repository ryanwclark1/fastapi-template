# Testing Guide

This guide summarizes the project's testing strategy and provides the commands required to run each layer locally or in CI.

## Prerequisites

- Install the development dependencies so pytest, coverage, and Testcontainers are available:
  ```bash
  uv sync --group dev
  ```
- Docker must be available and running for the containerized integration suite (`tests/integration/test_containerized_api.py`), because it builds and runs the service image inside a disposable container.

## Test Matrix

| Layer | Description | Command |
| --- | --- | --- |
| Unit | Fast feedback tests for isolated components (services, helpers, middleware units). | `uv run pytest tests/unit -m "not slow"` |
| Integration (ASGI) | Exercises the FastAPI app via the in-process `httpx.AsyncClient` fixture. Covers health routes, middleware orchestration, etc. | `uv run pytest tests/integration -m "integration and not slow" -k "not containerized"` |
| Integration (Containerized) | Builds the Docker image, runs it with Testcontainers, and hits live endpoints to verify packaging, settings, and probes. Marked as `integration` and `slow`. | `uv run pytest tests/integration/test_containerized_api.py -m "integration and slow"` |
| End-to-End | Scenario tests that drive feature flows through the public API (see `tests/e2e`). | `uv run pytest tests/e2e` |
| Full Suite | CI-quality run with coverage enabled (default `pyproject.toml` addopts). | `uv run pytest` |

> **Tip:** Combine markers to skip long-running suites during inner-loop development, e.g. `uv run pytest -m "not slow"`.

## Containerized Integration Tests

1. Ensure Docker can build the project image (requires the `Dockerfile` to be in sync with code changes).
2. Run the tests:
   ```bash
   uv run pytest tests/integration/test_containerized_api.py -m "integration and slow" -vv
   ```
3. Pytest will:
   - Build the local Docker image (`example-service-integration-test`).
   - Start it via Testcontainers with health-readiness polling.
   - Call `/api/v1/health/` and `/metrics` over HTTP.

If Docker is unavailable, the suite automatically skips with a clear message. Failures usually indicate packaging problems (missing files in the image, migrations failing on startup, wrong environment defaults, etc.).

## Coverage Notes

The default pytest configuration collects coverage for `example_service/` and writes HTML reports to `htmlcov/`. Containerized tests run against a separate process, so they do not contribute to coverage; this is expected and explained by the warning emitted during those runs.
