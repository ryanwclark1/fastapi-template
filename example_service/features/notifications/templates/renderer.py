"""Jinja2 template rendering for notifications with validation and security."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from jinja2 import TemplateSyntaxError, UndefinedError, select_autoescape
from jinja2.sandbox import SandboxedEnvironment

from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from example_service.features.notifications.models import NotificationTemplate


class TemplateRenderError(Exception):
    """Raised when template rendering fails."""

    def __init__(self, message: str, template_name: str | None = None, missing_vars: list[str] | None = None) -> None:
        """Initialize render error with details.

        Args:
            message: Error description
            template_name: Name of template that failed
            missing_vars: List of missing required variables
        """
        super().__init__(message)
        self.template_name = template_name
        self.missing_vars = missing_vars or []


class TemplateRenderer:
    """Jinja2 template renderer with security sandboxing and validation.

    Uses SandboxedEnvironment to prevent arbitrary code execution.
    Validates required context variables before rendering.
    Supports email (subject, text, HTML) and JSON (webhook, websocket) templates.
    """

    def __init__(self) -> None:
        """Initialize with sandboxed Jinja2 environment."""
        self._logger = get_logger()

        # Create sandboxed environment for security
        self._env = SandboxedEnvironment(
            autoescape=select_autoescape(
                enabled_extensions=("html", "xml"),
                default_for_string=True,
            ),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Register custom filters
        self._env.filters["json"] = json.dumps

    def render_template(
        self,
        template: NotificationTemplate,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Render all templates for a notification template.

        Args:
            template: NotificationTemplate instance
            context: Variables for template rendering

        Returns:
            Dictionary with rendered content:
            - subject: Rendered email subject (if template has subject_template)
            - body: Rendered plain text body (if template has body_template)
            - body_html: Rendered HTML body (if template has body_html_template)
            - payload: Rendered JSON payload (for webhook/websocket)

        Raises:
            TemplateRenderError: If validation fails or rendering errors occur
        """
        # Validate required context variables
        self._validate_context(template, context)

        rendered = {}

        try:
            # Render email templates
            if template.subject_template:
                rendered["subject"] = self._render_string(template.subject_template, context)

            if template.body_template:
                rendered["body"] = self._render_string(template.body_template, context)

            if template.body_html_template:
                rendered["body_html"] = self._render_string(template.body_html_template, context, autoescape=True)

            # Render webhook payload
            if template.webhook_payload_template:
                rendered["payload"] = self._render_json(template.webhook_payload_template, context)

            # Render websocket payload
            if template.websocket_payload_template:
                rendered["payload"] = self._render_json(template.websocket_payload_template, context)
                rendered["event_type"] = template.websocket_event_type

            self._logger.debug(
                lambda: f"Rendered template {template.name} for channel {template.channel}",
            )

            return rendered

        except UndefinedError as exc:
            msg = f"Missing variable in template {template.name}: {exc}"
            raise TemplateRenderError(msg, template_name=template.name) from exc

        except TemplateSyntaxError as exc:
            msg = f"Syntax error in template {template.name}: {exc}"
            raise TemplateRenderError(msg, template_name=template.name) from exc

        except Exception as exc:
            msg = f"Failed to render template {template.name}: {exc}"
            raise TemplateRenderError(msg, template_name=template.name) from exc

    def _validate_context(
        self,
        template: NotificationTemplate,
        context: dict[str, Any],
    ) -> None:
        """Validate that all required context variables are present.

        Args:
            template: NotificationTemplate instance
            context: Context variables

        Raises:
            TemplateRenderError: If required variables are missing
        """
        if not template.required_context_vars:
            return

        missing = [var for var in template.required_context_vars if var not in context]

        if missing:
            msg = (
                f"Missing required context variables for template {template.name}: {', '.join(missing)}"
            )
            raise TemplateRenderError(
                msg,
                template_name=template.name,
                missing_vars=missing,
            )

    def _render_string(
        self,
        template_str: str,
        context: dict[str, Any],
        autoescape: bool = False,
    ) -> str:
        """Render a string template.

        Args:
            template_str: Template string
            context: Context variables
            autoescape: Enable HTML autoescaping

        Returns:
            Rendered string
        """
        if autoescape:
            # For HTML, use environment with autoescape
            template = self._env.from_string(template_str)
        else:
            # For plain text, disable autoescape
            env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
            template = env.from_string(template_str)

        return template.render(**context)

    def _render_json(
        self,
        template_dict: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Render a JSON template (dict with Jinja2 strings in values).

        Args:
            template_dict: Template dictionary with Jinja2 expressions
            context: Context variables

        Returns:
            Rendered dictionary with all Jinja2 expressions evaluated
        """
        return self._render_dict_recursive(template_dict, context)

    def _render_dict_recursive(
        self,
        obj: Any,
        context: dict[str, Any],
    ) -> Any:
        """Recursively render Jinja2 expressions in nested dicts/lists.

        Args:
            obj: Object to render (dict, list, str, or primitive)
            context: Context variables

        Returns:
            Object with all Jinja2 expressions rendered
        """
        if isinstance(obj, dict):
            return {k: self._render_dict_recursive(v, context) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self._render_dict_recursive(item, context) for item in obj]

        if isinstance(obj, str):
            # Check if string contains Jinja2 syntax
            if "{{" in obj or "{%" in obj:
                env = SandboxedEnvironment(autoescape=False)
                template = env.from_string(obj)
                return template.render(**context)
            return obj

        # Primitives (int, float, bool, None) pass through
        return obj


# Singleton instance
_renderer: TemplateRenderer | None = None


def get_template_renderer() -> TemplateRenderer:
    """Get or create the singleton TemplateRenderer instance.

    Returns:
        TemplateRenderer instance
    """
    global _renderer
    if _renderer is None:
        _renderer = TemplateRenderer()
    return _renderer
