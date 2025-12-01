"""Serve the local GraphQL Playground assets and HTML shell."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from importlib import resources
from typing import Final

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

_ASSET_ROUTE_NAME: Final = "graphql-playground-asset"
_ASSET_ROUTE_PATH: Final = "/playground-assets/{asset_name}"
_ASSET_MEDIA_TYPES: Final = {
    "playground.css": "text/css; charset=utf-8",
    "playground-shell.css": "text/css; charset=utf-8",
    "playground.js": "application/javascript",
    "playground-init.js": "application/javascript",
    "favicon.png": "image/png",
}


@dataclass(frozen=True)
class _PlaygroundStaticUrls:
    css: str
    shell_css: str
    js: str
    init_js: str
    favicon: str


def register_playground_routes(
    router: APIRouter,
    *,
    graphql_path: str,
    title: str,
    subscriptions_enabled: bool,
) -> None:
    """Serve local assets and expose the /playground endpoint."""
    assets = _load_assets()

    @router.get(_ASSET_ROUTE_PATH, include_in_schema=False, name=_ASSET_ROUTE_NAME)
    async def graphql_playground_asset(asset_name: str) -> Response:
        return _serve_asset(asset_name, assets)

    @router.get("/playground", include_in_schema=False)
    async def graphql_playground(request: Request) -> HTMLResponse:
        static_urls = _get_static_urls(request)
        endpoint_url = _build_endpoint_url(request, graphql_path)
        subscription_url = endpoint_url if subscriptions_enabled else None
        html_template = _render_playground_html(
            title=title,
            endpoint_url=endpoint_url,
            subscription_url=subscription_url,
            static_urls=static_urls,
        )
        return HTMLResponse(html_template)


def _load_assets() -> dict[str, tuple[bytes, str]]:
    base = resources.files("example_service") / "static" / "graphql"
    if not base.exists():
        raise RuntimeError("GraphQL Playground assets are missing. Reinstall the package.")

    assets: dict[str, tuple[bytes, str]] = {}
    for name, media_type in _ASSET_MEDIA_TYPES.items():
        file_ref = base / name
        if not file_ref.exists():
            raise RuntimeError(f"Missing GraphQL Playground asset: {name}")
        assets[name] = (file_ref.read_bytes(), media_type)
    return assets


def _serve_asset(asset_name: str, assets: dict[str, tuple[bytes, str]]) -> Response:
    asset = assets.get(asset_name)
    if asset is None:
        raise HTTPException(status_code=404, detail="Playground asset not found")
    content, media_type = asset
    return Response(content=content, media_type=media_type)


def _get_static_urls(request: Request) -> _PlaygroundStaticUrls:
    return _PlaygroundStaticUrls(
        css=request.url_for(_ASSET_ROUTE_NAME, asset_name="playground.css"),
        shell_css=request.url_for(_ASSET_ROUTE_NAME, asset_name="playground-shell.css"),
        js=request.url_for(_ASSET_ROUTE_NAME, asset_name="playground.js"),
        init_js=request.url_for(_ASSET_ROUTE_NAME, asset_name="playground-init.js"),
        favicon=request.url_for(_ASSET_ROUTE_NAME, asset_name="favicon.png"),
    )


def _build_endpoint_url(request: Request, graphql_path: str) -> str:
    """Combine ASGI root_path with the configured GraphQL path."""
    normalized_path = _normalize_path(graphql_path)
    root_path = (request.scope.get("root_path") or "").rstrip("/")
    if not root_path:
        return normalized_path
    return f"{root_path}{normalized_path}"


def _normalize_path(path: str) -> str:
    path = path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _render_playground_html(
    *,
    title: str,
    endpoint_url: str,
    subscription_url: str | None,
    static_urls: _PlaygroundStaticUrls,
) -> str:
    safe_title = html.escape(title)
    config: dict[str, object] = {
        "endpoint": endpoint_url,
        "settings": {
            "request.credentials": "same-origin",
            "schema.polling.enable": False,
            "schema.polling.endpointFilter": "*",
        },
    }
    if subscription_url:
        config["subscriptionEndpoint"] = subscription_url

    config_data = html.escape(json.dumps(config), quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title} · GraphQL Playground</title>
    <link rel="icon" type="image/png" href="{static_urls.favicon}" />
    <link rel="stylesheet" href="{static_urls.css}" />
    <link rel="stylesheet" href="{static_urls.shell_css}" />
  </head>
  <body class="graphql-playground-body" data-playground-config="{config_data}">
    <div class="graphql-playground-shell">
      <div id="graphql-playground" class="docs-loading">Loading GraphQL Playground…</div>
    </div>
    <script defer src="{static_urls.js}"></script>
    <script defer src="{static_urls.init_js}"></script>
  </body>
</html>
"""


__all__ = ["register_playground_routes"]
