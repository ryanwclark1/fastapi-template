"""Custom documentation pages with CSP-friendly assets."""

from __future__ import annotations

import html
import json
import logging
from importlib import resources
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from example_service.core.settings import get_app_settings

logger = logging.getLogger(__name__)

_DOCS_STATIC_URL = "/_static/docs"
_ASYNCAPI_PATCHED = False


def ensure_asyncapi_template_patched() -> None:
    """Guarantee the AsyncAPI template uses local, CSP-safe assets."""
    _patch_asyncapi_template()


def configure_documentation(app: FastAPI) -> None:
    """Configure documentation routes with local assets.

    Always mount the static docs assets so AsyncAPI pages can render even when
    HTTP docs are disabled.
    """
    static_directory = _resolve_static_directory()
    app.mount(
        _DOCS_STATIC_URL,
        StaticFiles(directory=static_directory),
        name="docs-static",
    )

    ensure_asyncapi_template_patched()

    settings = get_app_settings()
    if settings.disable_docs:
        logger.info("API documentation disabled via configuration")
        return

    docs_url = settings.get_docs_url()
    redoc_url = settings.get_redoc_url()
    oauth_redirect_url = settings.get_swagger_ui_oauth2_redirect_url()

    if docs_url:
        _register_swagger_ui(app, docs_url, oauth_redirect_url)
    if redoc_url:
        _register_redoc(app, redoc_url)
    if oauth_redirect_url:
        _register_oauth_redirect(app, oauth_redirect_url)


def _register_swagger_ui(app: FastAPI, docs_url: str, oauth_redirect: str | None) -> None:
    settings = get_app_settings()
    path = _normalize_path(docs_url)
    config_url = _path_join(path, "swagger-config.json")

    @app.get(path, include_in_schema=False)
    async def swagger_ui_html() -> HTMLResponse:
        openapi_url = settings.get_openapi_url()
        if not openapi_url:
            raise HTTPException(status_code=404, detail="OpenAPI schema is disabled")

        html_template = _render_swagger_html(
            title=settings.title,
            config_url=config_url,
        )
        return HTMLResponse(html_template)

    @app.get(config_url, include_in_schema=False)
    async def swagger_ui_config() -> JSONResponse:
        openapi_url = settings.get_openapi_url()
        if not openapi_url:
            raise HTTPException(status_code=404, detail="OpenAPI schema is disabled")

        payload: dict[str, Any] = {
            "openapiUrl": openapi_url,
            "swaggerUiParameters": settings.get_swagger_ui_parameters() or {},
        }

        if oauth_redirect:
            payload["oauth2RedirectUrl"] = oauth_redirect
        if settings.swagger_ui_init_oauth:
            payload["initOAuth"] = settings.swagger_ui_init_oauth

        return JSONResponse(payload)


def _register_redoc(app: FastAPI, redoc_url: str) -> None:
    settings = get_app_settings()
    path = _normalize_path(redoc_url)

    @app.get(path, include_in_schema=False)
    async def redoc_html() -> HTMLResponse:
        spec_url = settings.get_openapi_url()
        if not spec_url:
            raise HTTPException(status_code=404, detail="OpenAPI schema is disabled")

        html_template = _render_redoc_html(
            title=settings.title,
            spec_url=spec_url,
        )
        return HTMLResponse(html_template)


def _register_oauth_redirect(app: FastAPI, oauth_url: str) -> None:
    path = _normalize_path(oauth_url)

    @app.get(path, include_in_schema=False)
    async def oauth_redirect_html() -> HTMLResponse:
        html_template = _render_oauth_redirect_html()
        return HTMLResponse(html_template)


def _render_swagger_html(*, title: str, config_url: str) -> str:
    safe_title = html.escape(title)
    safe_config = html.escape(config_url, quote=True)
    css_url = f"{_DOCS_STATIC_URL}/docs.css"
    swagger_css = f"{_DOCS_STATIC_URL}/swagger-ui.css"
    swagger_bundle = f"{_DOCS_STATIC_URL}/swagger-ui-bundle.js"
    init_script = f"{_DOCS_STATIC_URL}/swagger-ui-init.js"

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title} · API Explorer</title>
    <link rel="stylesheet" href="{css_url}" />
    <link rel="stylesheet" href="{swagger_css}" />
  </head>
  <body class="docs-body" data-swagger-config-url="{safe_config}">
    <div class="docs-shell">
      <div id="swagger-ui" class="docs-container"></div>
    </div>
    <script defer src="{swagger_bundle}"></script>
    <script defer src="{init_script}"></script>
  </body>
</html>
"""


def _render_redoc_html(*, title: str, spec_url: str) -> str:
    safe_title = html.escape(title)
    safe_spec = html.escape(spec_url, quote=True)
    css_url = f"{_DOCS_STATIC_URL}/docs.css"
    redoc_bundle = f"{_DOCS_STATIC_URL}/redoc.standalone.js"
    redoc_init = f"{_DOCS_STATIC_URL}/redoc-init.js"

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title} · ReDoc</title>
    <link rel="stylesheet" href="{css_url}" />
  </head>
  <body class="docs-body" data-redoc-spec-url="{safe_spec}">
    <div class="docs-shell">
      <div id="redoc-container" class="docs-container docs-loading">Loading documentation…</div>
    </div>
    <script defer src="{redoc_bundle}"></script>
    <script defer src="{redoc_init}"></script>
  </body>
</html>
"""


def _render_oauth_redirect_html() -> str:
    css_url = f"{_DOCS_STATIC_URL}/docs.css"
    oauth_script = f"{_DOCS_STATIC_URL}/swagger-ui-oauth2-redirect.js"

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Swagger UI · OAuth2 Redirect</title>
    <link rel="stylesheet" href="{css_url}" />
  </head>
  <body class="docs-body">
    <div class="docs-shell">
      <p class="docs-loading">Completing OAuth2 flow…</p>
    </div>
    <script src="{oauth_script}"></script>
  </body>
</html>
"""


def _patch_asyncapi_template() -> None:
    global _ASYNCAPI_PATCHED
    if _ASYNCAPI_PATCHED:
        return

    from faststream.specification.asyncapi import site as asyncapi_site

    def custom_asyncapi_html(
        schema: Any,
        sidebar: bool = True,
        info: bool = True,
        servers: bool = True,
        operations: bool = True,
        messages: bool = True,
        schemas: bool = True,
        errors: bool = True,
        expand_message_examples: bool = True,
        asyncapi_js_url: str | None = None,  # noqa: ARG001 - ignored, use local assets
        asyncapi_css_url: str | None = None,  # noqa: ARG001 - ignored, use local assets
    ) -> str:
        config = {
            "show": {
                "sidebar": sidebar,
                "info": info,
                "servers": servers,
                "operations": operations,
                "messages": messages,
                "schemas": schemas,
                "errors": errors,
            },
            "expand": {
                "messageExamples": expand_message_examples,
            },
            "sidebar": {
                "showServers": "byDefault",
                "showOperations": "byDefault",
            },
        }
        config_json = html.escape(json.dumps(config), quote=True)
        base_css = f"{_DOCS_STATIC_URL}/docs.css"
        asyncapi_css = f"{_DOCS_STATIC_URL}/asyncapi-default.min.css"
        asyncapi_bundle = f"{_DOCS_STATIC_URL}/asyncapi-standalone.js"
        asyncapi_init = f"{_DOCS_STATIC_URL}/asyncapi-init.js"
        safe_title = html.escape(getattr(schema, "title", "AsyncAPI"))

        return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title} · AsyncAPI</title>
    <link rel="stylesheet" href="{base_css}" />
    <link rel="stylesheet" href="{asyncapi_css}" />
  </head>
  <body class="docs-body" data-asyncapi-config="{config_json}">
    <div class="docs-shell">
      <div id="asyncapi" class="docs-container docs-loading">Loading AsyncAPI schema…</div>
    </div>
    <script defer src="{asyncapi_bundle}"></script>
    <script defer src="{asyncapi_init}"></script>
  </body>
</html>
"""

    asyncapi_site.get_asyncapi_html = custom_asyncapi_html
    _ASYNCAPI_PATCHED = True

    logger.debug("Patched FastStream AsyncAPI template for CSP-safe assets")


def _resolve_static_directory() -> str:
    static_dir = resources.files("example_service") / "static" / "docs"
    # Check if directory exists by trying to iterate it
    try:
        next(static_dir.iterdir(), None)
    except (OSError, FileNotFoundError) as e:
        raise RuntimeError("Documentation assets are missing. Reinstall the application.") from e
    return str(static_dir)


def _normalize_path(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return path.rstrip("/") or "/"


def _path_join(base: str, suffix: str) -> str:
    base = _normalize_path(base)
    suffix = suffix.lstrip("/")
    if base == "/":
        return f"/{suffix}"
    return f"{base}/{suffix}"
