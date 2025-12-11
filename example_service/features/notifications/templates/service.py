"""Service layer for notification template management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from example_service.core.services.base import BaseService
from example_service.features.notifications.models import NotificationTemplate
from example_service.features.notifications.repository import (
    NotificationTemplateRepository,
    get_notification_template_repository,
)
from example_service.features.notifications.templates.renderer import (
    get_template_renderer,
)
from example_service.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class NotificationTemplateService(BaseService):
    """Service for notification template CRUD and rendering.

    Provides:
    - Template CRUD operations with tenant isolation
    - Template rendering with Jinja2
    - Template resolution (tenant-specific > global fallback)
    - Context variable validation
    """

    def __init__(
        self,
        repository: NotificationTemplateRepository | None = None,
    ) -> None:
        """Initialize with repository and renderer.

        Args:
            repository: Optional repository (defaults to singleton)
        """
        super().__init__()
        self._repository: NotificationTemplateRepository = repository or get_notification_template_repository()
        self._renderer = get_template_renderer()
        self._logger = get_logger()

    async def get_template_for_type_and_channel(
        self,
        session: AsyncSession,
        notification_type: str,
        channel: str,
        tenant_id: str | None = None,
    ) -> NotificationTemplate | None:
        """Get template by notification type and channel with tenant resolution.

        Resolves template with priority:
        1. Tenant-specific template (if tenant_id provided)
        2. Global template (tenant_id = None)

        Args:
            session: Database session
            notification_type: Type of notification (e.g., 'reminder')
            channel: Delivery channel (email, webhook, websocket, in_app)
            tenant_id: Optional tenant ID

        Returns:
            Template if found, None otherwise
        """
        # The repository method uses name for lookup, but we want to search by type
        # List all active templates for this type, then filter by channel
        templates = await self._repository.list_by_type(session, notification_type, tenant_id)

        # Find template matching channel
        # Prefer tenant-specific, fall back to global
        tenant_template = None
        global_template = None

        for template in templates:
            if template.channel != channel:
                continue

            if template.tenant_id == tenant_id:
                tenant_template = template
            elif template.tenant_id is None:
                global_template = template

        result = tenant_template or global_template

        if result:
            self._logger.debug(
                lambda: f"Resolved template for {notification_type}/{channel}: {result.name} (tenant={result.tenant_id})",
            )
        else:
            self._logger.warning(
                f"No template found for {notification_type}/{channel} (tenant={tenant_id})",
            )

        return result

    async def render_template(
        self,
        session: AsyncSession,
        template_id: UUID,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Render a template with context.

        Args:
            session: Database session
            template_id: Template UUID
            context: Variables for rendering

        Returns:
            Dictionary with rendered content (subject, body, body_html, payload)

        Raises:
            ValueError: If template not found
            TemplateRenderError: If rendering fails
        """
        template = await self._repository.get(session, template_id)

        if not template:
            msg = f"Template {template_id} not found"
            raise ValueError(msg)

        if not template.is_active:
            msg = f"Template {template_id} is not active"
            raise ValueError(msg)

        return self._renderer.render_template(template, context)

    async def render_template_by_name(
        self,
        session: AsyncSession,
        name: str,
        channel: str,
        context: dict[str, Any],
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Render a template by name and channel.

        Args:
            session: Database session
            name: Template name (e.g., 'reminder_due')
            channel: Delivery channel
            context: Variables for rendering
            tenant_id: Optional tenant ID

        Returns:
            Dictionary with rendered content

        Raises:
            ValueError: If template not found
            TemplateRenderError: If rendering fails
        """
        template = await self._repository.get_by_name_and_channel(session, name, channel, tenant_id)

        if not template:
            msg = f"Template {name} for channel {channel} not found (tenant={tenant_id})"
            raise ValueError(msg)

        if not template.is_active:
            msg = f"Template {name} is not active"
            raise ValueError(msg)

        return self._renderer.render_template(template, context)

    async def preview_template(
        self,
        template: NotificationTemplate,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Preview template rendering without saving.

        Useful for testing templates before activating them.

        Args:
            template: Template instance (can be unsaved)
            context: Variables for rendering

        Returns:
            Dictionary with rendered content

        Raises:
            TemplateRenderError: If rendering fails
        """
        return self._renderer.render_template(template, context)

    async def list_templates_for_type(
        self,
        session: AsyncSession,
        notification_type: str,
        tenant_id: str | None = None,
    ) -> Sequence[NotificationTemplate]:
        """List all active templates for a notification type.

        Args:
            session: Database session
            notification_type: Type of notification
            tenant_id: Optional tenant ID (returns tenant + global if specified)

        Returns:
            Sequence of templates
        """
        return await self._repository.list_by_type(session, notification_type, tenant_id)

    async def duplicate_template(
        self,
        session: AsyncSession,
        template_id: UUID,
        new_name: str,
        tenant_id: str | None = None,
    ) -> NotificationTemplate:
        """Duplicate an existing template with a new name.

        Useful for creating tenant-specific overrides of global templates.

        Args:
            session: Database session
            template_id: Source template UUID
            new_name: Name for the new template
            tenant_id: Optional tenant ID for the new template

        Returns:
            New template instance

        Raises:
            ValueError: If source template not found
        """
        source = await self._repository.get(session, template_id)

        if not source:
            msg = f"Source template {template_id} not found"
            raise ValueError(msg)

        # Create new template with same content
        new_template = NotificationTemplate(
            name=new_name,
            notification_type=source.notification_type,
            channel=source.channel,
            description=f"Copy of {source.name}",
            priority=source.priority,
            tenant_id=tenant_id,
            subject_template=source.subject_template,
            body_template=source.body_template,
            body_html_template=source.body_html_template,
            webhook_payload_template=source.webhook_payload_template,
            websocket_event_type=source.websocket_event_type,
            websocket_payload_template=source.websocket_payload_template,
            required_context_vars=source.required_context_vars.copy(),
            is_active=False,  # Start inactive for review
            version=1,
        )

        session.add(new_template)
        await session.flush()

        self._logger.info(
            f"Duplicated template {source.name} -> {new_name} (tenant={tenant_id})",
        )

        return new_template


# Singleton instance
_service: NotificationTemplateService | None = None


def get_notification_template_service() -> NotificationTemplateService:
    """Get or create the singleton NotificationTemplateService instance.

    Returns:
        NotificationTemplateService instance
    """
    global _service
    if _service is None:
        _service = NotificationTemplateService()
    return _service
