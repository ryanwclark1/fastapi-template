"""Tests for the local GraphQL Playground assets."""
from __future__ import annotations

import html
import json
import re
import sys
from types import ModuleType, SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

# Provide a lightweight strawberry stub so optional dependency is not required for import.
if "strawberry" not in sys.modules:  # pragma: no cover - executed in CI without strawberry
    strawberry = ModuleType("strawberry")
    strawberry_fastapi = ModuleType("strawberry.fastapi")

    class _DummyGraphQLRouter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs

    strawberry_fastapi.GraphQLRouter = _DummyGraphQLRouter  # type: ignore[attr-defined]
    strawberry.fastapi = strawberry_fastapi  # type: ignore[attr-defined]
    sys.modules["strawberry"] = strawberry
    sys.modules["strawberry.fastapi"] = strawberry_fastapi

if "email_validator" not in sys.modules:  # pragma: no cover - optional dependency
    email_validator = ModuleType("email_validator")

    class EmailNotValidError(ValueError):
        """Fallback error raised by email_validator."""

    def validate_email(email: str, **_: object) -> SimpleNamespace:
        return SimpleNamespace(email=email)

    email_validator.EmailNotValidError = EmailNotValidError  # type: ignore[attr-defined]
    email_validator.validate_email = validate_email  # type: ignore[attr-defined]
    sys.modules["email_validator"] = email_validator

from example_service.features.graphql.playground import register_playground_routes


def _extract_config(html_body: str) -> dict[str, object]:
    match = re.search(r'data-playground-config="([^"]+)"', html_body)
    assert match, "Playground config attribute missing"
    return json.loads(html.unescape(match.group(1)))


def test_playground_route_serves_html_and_assets() -> None:
    router = APIRouter()
    register_playground_routes(
        router,
        graphql_path="/graphql",
        title="Example Service",
        subscriptions_enabled=True,
    )

    app = FastAPI()
    app.include_router(router, prefix="/graphql")
    client = TestClient(app)

    response = client.get("/graphql/playground")
    assert response.status_code == 200
    assert "GraphQL Playground" in response.text

    config = _extract_config(response.text)
    assert config["endpoint"] == "/graphql"
    assert config["subscriptionEndpoint"] == "/graphql"

    asset = client.get("/graphql/playground-assets/playground.js")
    assert asset.status_code == 200
    assert asset.content.startswith(b"!function")


def test_playground_route_respects_root_path_and_subscriptions_flag() -> None:
    router = APIRouter()
    register_playground_routes(
        router,
        graphql_path="/graphql",
        title="Example Service",
        subscriptions_enabled=False,
    )

    app = FastAPI()
    app.include_router(router, prefix="/graphql")
    client = TestClient(app, root_path="/service")

    response = client.get("/graphql/playground")
    assert response.status_code == 200

    config = _extract_config(response.text)
    assert config["endpoint"] == "/service/graphql"
    assert "subscriptionEndpoint" not in config
