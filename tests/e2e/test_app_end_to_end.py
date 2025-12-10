"""End-to-end tests for the FastAPI stack including messaging router."""

from __future__ import annotations

import importlib
import os

from faststream.rabbit.testing import TestRabbitBroker
from httpx import ASGITransport, AsyncClient
import pytest

from example_service.core.settings.loader import clear_all_caches

pytestmark = pytest.mark.anyio


@pytest.fixture
async def e2e_stack(monkeypatch):
    """Spin up the full app with middleware and Rabbit router (patched in-memory)."""
    original_rabbit_enabled = os.environ.get("RABBIT_ENABLED")
    monkeypatch.setenv("RABBIT_ENABLED", "true")
    clear_all_caches()

    broker_module = importlib.reload(
        importlib.import_module("example_service.infra.messaging.broker")
    )
    handlers_module = importlib.reload(
        importlib.import_module("example_service.infra.messaging.handlers")
    )
    importlib.reload(importlib.import_module("example_service.app.router"))
    main_module = importlib.reload(importlib.import_module("example_service.app.main"))

    assert broker_module.router is not None, "Rabbit router should be configured for e2e tests"
    app = main_module.create_app()

    test_broker = TestRabbitBroker(broker_module.router.broker)

    async with (
        test_broker,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield {
            "client": client,
            "broker": broker_module.router.broker,
            "handlers": handlers_module,
        }

    # Restore original settings/modules for the rest of the suite
    if original_rabbit_enabled is None:
        os.environ.pop("RABBIT_ENABLED", None)
    else:
        os.environ["RABBIT_ENABLED"] = original_rabbit_enabled

    clear_all_caches()
    importlib.reload(importlib.import_module("example_service.infra.messaging.broker"))
    importlib.reload(importlib.import_module("example_service.infra.messaging.handlers"))
    importlib.reload(importlib.import_module("example_service.app.router"))
    importlib.reload(importlib.import_module("example_service.app.main"))


async def test_health_endpoint_and_asyncapi_docs_available(e2e_stack):
    """Full-stack request hits middleware chain while messaging router is initialized."""
    client = e2e_stack["client"]
    broker = e2e_stack["broker"]

    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert "content-security-policy" in response.headers
    assert "x-request-id" in response.headers
    assert "x-process-time" in response.headers
    assert broker.subscribers, "Messaging router should register subscribers"


async def test_in_memory_broker_processes_echo_flow(e2e_stack):
    """Publishing to the echo queue propagates through subscribers via the in-memory broker."""
    broker = e2e_stack["broker"]
    handlers = e2e_stack["handlers"]

    handlers.handle_echo_request.refresh(with_mock=True)
    handlers.handle_echo_response.refresh(with_mock=True)

    payload = {
        "event_type": "e2e.echo",
        "data": {"value": "ping"},
    }

    # Import exchanges module to get DOMAIN_EVENTS_EXCHANGE
    from example_service.infra.messaging import exchanges

    # Publish through the exchange, not directly to the queue
    await broker.publish(
        payload,
        queue=handlers.ECHO_SERVICE_QUEUE,
        exchange=exchanges.DOMAIN_EVENTS_EXCHANGE,
    )
    await handlers.handle_echo_response.wait_call(timeout=3.0)

    assert handlers.handle_echo_request.mock.call_count == 1
    response_payload = handlers.handle_echo_response.mock.call_args[0][0]
    assert response_payload["original"]["data"]["value"] == "ping"
    assert response_payload["service"] == "echo-service"
