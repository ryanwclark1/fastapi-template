"""Email template rendering with Jinja2.

Provides email template rendering with support for:
- HTML and plain text templates
- Template inheritance
- Automatic text version generation from HTML
- Default context variables
"""

from __future__ import annotations

from functools import lru_cache
from html import unescape
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from .client import get_email_settings

if TYPE_CHECKING:
    from example_service.core.settings.email import EmailSettings

logger = logging.getLogger(__name__)


class EmailTemplateRenderer:
    """Jinja2-based email template renderer.

    Renders HTML and plain text email templates with support for
    template inheritance and automatic text generation from HTML.

    Example:
        renderer = EmailTemplateRenderer(settings)
        html, text = renderer.render(
            "welcome",
            user_name="John",
            action_url="https://example.com/verify",
        )
    """

    def __init__(self, settings: EmailSettings) -> None:
        """Initialize template renderer.

        Args:
            settings: Email settings with template configuration.
        """
        self.settings = settings

        # Determine template directory
        package_root = Path(__file__).parent.parent.parent
        self.template_dir = package_root / settings.template_dir

        # Create Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Add custom filters
        self.env.filters["html_to_text"] = self._html_to_text

        # Store default context
        self.default_context = settings.default_template_context or {}

        logger.info(
            "Email template renderer initialized",
            extra={"template_dir": str(self.template_dir)},
        )

    def render(
        self,
        template_name: str,
        **context: Any,
    ) -> tuple[str | None, str | None]:
        """Render an email template.

        Attempts to render both HTML and plain text versions.
        If only HTML exists, generates text from HTML.
        If only text exists, uses that without HTML.

        Args:
            template_name: Name of the template (without extension).
            **context: Variables to pass to the template.

        Returns:
            Tuple of (html_content, text_content).

        Raises:
            TemplateNotFoundError: If neither HTML nor text template exists.

        Example:
            html, text = renderer.render(
                "welcome",
                user_name="John",
                action_url="https://example.com/verify",
            )
        """
        # Merge default context with provided context
        full_context = {**self.default_context, **context}

        html_content = None
        text_content = None

        # Try to render HTML template
        try:
            html_template = self.env.get_template(f"{template_name}.html")
            html_content = html_template.render(**full_context)
        except TemplateNotFound:
            logger.debug(f"No HTML template found for: {template_name}")

        # Try to render text template
        try:
            text_template = self.env.get_template(f"{template_name}.txt")
            text_content = text_template.render(**full_context)
        except TemplateNotFound:
            logger.debug(f"No text template found for: {template_name}")

        # Generate text from HTML if no text template
        if html_content and not text_content:
            text_content = self._html_to_text(html_content)

        # Raise error if neither template found
        if html_content is None and text_content is None:
            msg = (
                f"No template found for: {template_name} "
                f"(looked for {template_name}.html and {template_name}.txt)"
            )
            raise TemplateNotFoundError(
                msg,
            )

        return html_content, text_content

    def render_string(
        self,
        template_string: str,
        is_html: bool = True,
        **context: Any,
    ) -> tuple[str | None, str | None]:
        """Render an email from a template string.

        Args:
            template_string: Jinja2 template string.
            is_html: Whether the template is HTML.
            **context: Variables to pass to the template.

        Returns:
            Tuple of (html_content, text_content).
        """
        full_context = {**self.default_context, **context}
        template = self.env.from_string(template_string)
        content = template.render(**full_context)

        if is_html:
            return content, self._html_to_text(content)
        return None, content

    def template_exists(self, template_name: str) -> bool:
        """Check if a template exists.

        Args:
            template_name: Name of the template (without extension).

        Returns:
            True if either HTML or text template exists.
        """
        try:
            self.env.get_template(f"{template_name}.html")
            return True
        except TemplateNotFound:
            pass

        try:
            self.env.get_template(f"{template_name}.txt")
            return True
        except TemplateNotFound:
            pass

        return False

    def list_templates(self) -> list[str]:
        """List available template names.

        Returns:
            List of unique template names (without extensions).
        """
        templates = set()
        for template_path in self.env.loader.list_templates(): # type: ignore[union-attr]
            # Remove extension to get base name
            name = Path(template_path).stem
            templates.add(name)
        return sorted(templates)

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text.

        Performs basic HTML to text conversion:
        - Removes HTML tags
        - Converts links to text with URL
        - Handles common HTML entities
        - Normalizes whitespace

        Args:
            html: HTML content.

        Returns:
            Plain text version.
        """
        # Convert links to text format
        html = re.sub(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
            r"\2 (\1)",
            html,
            flags=re.IGNORECASE,
        )

        # Convert headers to uppercase with newlines
        for i in range(1, 7):
            html = re.sub(
                rf"<h{i}[^>]*>([^<]+)</h{i}>",
                r"\n\n\1\n" + "=" * 40 + r"\n",
                html,
                flags=re.IGNORECASE,
            )

        # Convert paragraph and div to newlines
        html = re.sub(r"</?(p|div)[^>]*>", r"\n\n", html, flags=re.IGNORECASE)

        # Convert br to newline
        html = re.sub(r"<br\s*/?>", r"\n", html, flags=re.IGNORECASE)

        # Convert list items
        html = re.sub(r"<li[^>]*>", r"\n  * ", html, flags=re.IGNORECASE)

        # Remove remaining HTML tags
        html = re.sub(r"<[^>]+>", "", html)

        # Decode HTML entities
        text = unescape(html)

        # Normalize whitespace
        text = re.sub(r" +", " ", text)  # Multiple spaces to single
        text = re.sub(r"\n\s*\n", "\n\n", text)  # Multiple newlines to double
        return text.strip()



class TemplateNotFoundError(Exception):
    """Raised when an email template cannot be found."""



@lru_cache(maxsize=1)
def get_template_renderer(settings: EmailSettings | None = None) -> EmailTemplateRenderer:
    """Get cached email template renderer.

    Args:
        settings: Optional settings override.

    Returns:
        Configured EmailTemplateRenderer instance.
    """
    if settings is None:
        settings = get_email_settings()
    return EmailTemplateRenderer(settings)
