"""Webhook callbacks for async AI workflows.

This module provides webhook functionality for notifying external systems
about workflow events:

- Workflow completion notifications
- Step/node execution updates
- Human approval requests
- Error notifications
- Progress updates

Features:
- Configurable retry logic
- Signature verification
- Payload customization
- Delivery tracking
- Event filtering

Example:
    from example_service.infra.ai.agents.webhooks import (
        WebhookConfig,
        WebhookClient,
        WorkflowWebhookHandler,
    )

    # Configure webhook
    config = WebhookConfig(
        url="https://api.example.com/webhooks/ai",
        secret="webhook_secret",
        events=[WebhookEvent.WORKFLOW_COMPLETE, WebhookEvent.ERROR],
    )

    # Create handler
    handler = WorkflowWebhookHandler(config)

    # Attach to workflow
    workflow.add_event_handler(handler)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Callable
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field, HttpUrl

logger = logging.getLogger(__name__)


# =============================================================================
# Webhook Events
# =============================================================================


class WebhookEvent(str, Enum):
    """Types of webhook events."""

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETE = "workflow.complete"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_CANCELLED = "workflow.cancelled"
    WORKFLOW_PAUSED = "workflow.paused"
    WORKFLOW_RESUMED = "workflow.resumed"

    # Node events
    NODE_STARTED = "node.started"
    NODE_COMPLETE = "node.complete"
    NODE_FAILED = "node.failed"

    # Approval events
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    APPROVAL_EXPIRED = "approval.expired"

    # Agent events
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETE = "agent.complete"
    AGENT_FAILED = "agent.failed"

    # Progress events
    PROGRESS_UPDATE = "progress.update"

    # Error events
    ERROR = "error"


# =============================================================================
# Webhook Payload
# =============================================================================


class WebhookPayload(BaseModel):
    """Payload sent to webhook endpoint."""

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique delivery ID")
    event: str = Field(..., description="Event type")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict, description="Event data")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    # Context
    tenant_id: str | None = Field(None, description="Tenant identifier")
    workflow_id: str | None = Field(None, description="Workflow execution ID")
    correlation_id: str | None = Field(None, description="Correlation ID for tracing")


class WebhookDelivery(BaseModel):
    """Record of a webhook delivery attempt."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    payload_id: str
    event: str
    url: str
    status: str = "pending"  # pending, success, failed
    attempts: int = 0
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    response_status: int | None = None
    response_body: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


# =============================================================================
# Webhook Configuration
# =============================================================================


class WebhookConfig(BaseModel):
    """Configuration for a webhook endpoint."""

    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    secret: str | None = Field(None, description="Secret for HMAC signature")
    events: list[WebhookEvent] = Field(
        default_factory=lambda: list(WebhookEvent),
        description="Events to send to this webhook",
    )

    # Retry configuration
    max_retries: int = Field(3, ge=0, le=10, description="Maximum retry attempts")
    retry_delay_seconds: float = Field(5.0, ge=1.0, description="Initial retry delay")
    retry_backoff: float = Field(2.0, ge=1.0, description="Exponential backoff multiplier")
    timeout_seconds: float = Field(30.0, ge=5.0, description="Request timeout")

    # Headers
    custom_headers: dict[str, str] = Field(
        default_factory=dict, description="Custom HTTP headers"
    )

    # Filtering
    tenant_ids: list[str] | None = Field(
        None, description="Filter by tenant IDs (None = all)"
    )
    workflow_ids: list[str] | None = Field(
        None, description="Filter by workflow IDs (None = all)"
    )

    # Options
    enabled: bool = Field(True, description="Whether webhook is enabled")
    include_full_data: bool = Field(True, description="Include full event data")
    batch_events: bool = Field(False, description="Batch multiple events together")
    batch_delay_seconds: float = Field(1.0, description="Delay for batching")


# =============================================================================
# Signature Generation
# =============================================================================


def generate_signature(
    payload: str,
    secret: str,
    algorithm: str = "sha256",
) -> str:
    """Generate HMAC signature for webhook payload.

    Args:
        payload: JSON payload string
        secret: Webhook secret
        algorithm: Hash algorithm (sha256, sha512)

    Returns:
        Hex-encoded signature
    """
    if algorithm == "sha256":
        mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256)
    elif algorithm == "sha512":
        mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha512)
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    return f"{algorithm}={mac.hexdigest()}"


def verify_signature(
    payload: str,
    signature: str,
    secret: str,
) -> bool:
    """Verify webhook signature.

    Args:
        payload: JSON payload string
        signature: Signature from header (format: algorithm=hex)
        secret: Webhook secret

    Returns:
        True if signature is valid
    """
    try:
        algorithm, hex_digest = signature.split("=", 1)
        expected = generate_signature(payload, secret, algorithm)
        return hmac.compare_digest(signature, expected)
    except (ValueError, KeyError):
        return False


# =============================================================================
# Webhook Client
# =============================================================================


class WebhookClient:
    """HTTP client for sending webhooks.

    Handles:
    - Retry logic with exponential backoff
    - Signature generation
    - Timeout handling
    - Error tracking
    """

    def __init__(
        self,
        config: WebhookConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize webhook client.

        Args:
            config: Webhook configuration
            http_client: Optional HTTP client (creates one if not provided)
        """
        self.config = config
        self._client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> WebhookClient:
        """Enter context."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout_seconds)
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context."""
        if self._owns_client and self._client:
            await self._client.aclose()

    async def send(self, payload: WebhookPayload) -> WebhookDelivery:
        """Send webhook with retry logic.

        Args:
            payload: Webhook payload

        Returns:
            Delivery record with status
        """
        if not self.config.enabled:
            return WebhookDelivery(
                payload_id=payload.id,
                event=payload.event,
                url=str(self.config.url),
                status="skipped",
                error="Webhook disabled",
            )

        delivery = WebhookDelivery(
            payload_id=payload.id,
            event=payload.event,
            url=str(self.config.url),
        )

        payload_json = payload.model_dump_json()

        for attempt in range(self.config.max_retries + 1):
            delivery.attempts = attempt + 1
            delivery.last_attempt_at = datetime.now(UTC)

            try:
                # Build headers
                headers = {
                    "Content-Type": "application/json",
                    "X-Webhook-ID": payload.id,
                    "X-Webhook-Event": payload.event,
                    "X-Webhook-Timestamp": payload.timestamp.isoformat(),
                    **self.config.custom_headers,
                }

                # Add signature if secret is configured
                if self.config.secret:
                    signature = generate_signature(payload_json, self.config.secret)
                    headers["X-Webhook-Signature"] = signature

                # Ensure client is available
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self.config.timeout_seconds)
                    )
                    self._owns_client = True

                # Send request
                response = await self._client.post(
                    str(self.config.url),
                    content=payload_json,
                    headers=headers,
                )

                delivery.response_status = response.status_code
                delivery.response_body = response.text[:1000]  # Limit size

                if response.is_success:
                    delivery.status = "success"
                    delivery.completed_at = datetime.now(UTC)
                    logger.info(
                        f"Webhook delivered successfully",
                        extra={
                            "webhook_id": payload.id,
                            "event": payload.event,
                            "url": str(self.config.url),
                            "status_code": response.status_code,
                        },
                    )
                    return delivery

                # Server error - retry
                if response.status_code >= 500:
                    delivery.error = f"Server error: {response.status_code}"
                    logger.warning(
                        f"Webhook server error, will retry",
                        extra={
                            "webhook_id": payload.id,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )
                else:
                    # Client error - don't retry
                    delivery.status = "failed"
                    delivery.error = f"Client error: {response.status_code}"
                    delivery.completed_at = datetime.now(UTC)
                    logger.error(
                        f"Webhook client error, not retrying",
                        extra={
                            "webhook_id": payload.id,
                            "status_code": response.status_code,
                        },
                    )
                    return delivery

            except httpx.TimeoutException:
                delivery.error = "Request timeout"
                logger.warning(
                    f"Webhook timeout, will retry",
                    extra={"webhook_id": payload.id, "attempt": attempt + 1},
                )

            except httpx.RequestError as e:
                delivery.error = f"Request error: {e!s}"
                logger.warning(
                    f"Webhook request error, will retry",
                    extra={
                        "webhook_id": payload.id,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )

            # Calculate next retry delay
            if attempt < self.config.max_retries:
                delay = self.config.retry_delay_seconds * (
                    self.config.retry_backoff**attempt
                )
                delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                await asyncio.sleep(delay)

        # All retries exhausted
        delivery.status = "failed"
        delivery.completed_at = datetime.now(UTC)
        logger.error(
            f"Webhook delivery failed after {self.config.max_retries + 1} attempts",
            extra={
                "webhook_id": payload.id,
                "event": payload.event,
                "url": str(self.config.url),
            },
        )

        return delivery


# =============================================================================
# Workflow Webhook Handler
# =============================================================================


class WorkflowWebhookHandler:
    """Handler for sending workflow events via webhooks.

    Integrates with workflows to automatically send notifications
    for configured events.

    Example:
        handler = WorkflowWebhookHandler(config)

        # Manual notification
        await handler.notify(
            WebhookEvent.WORKFLOW_COMPLETE,
            workflow_id="123",
            data={"result": "success"},
        )

        # As event handler
        async def on_complete(result):
            await handler.on_workflow_complete(workflow_id, result)
    """

    def __init__(
        self,
        config: WebhookConfig,
        tenant_id: str | None = None,
    ) -> None:
        """Initialize handler.

        Args:
            config: Webhook configuration
            tenant_id: Default tenant ID
        """
        self.config = config
        self.tenant_id = tenant_id
        self._deliveries: list[WebhookDelivery] = []
        self._batch_queue: list[WebhookPayload] = []
        self._batch_task: asyncio.Task | None = None

    def should_send(self, event: WebhookEvent) -> bool:
        """Check if event should be sent.

        Args:
            event: Event type

        Returns:
            True if event should be sent
        """
        if not self.config.enabled:
            return False
        return event in self.config.events

    async def notify(
        self,
        event: WebhookEvent,
        workflow_id: str | None = None,
        correlation_id: str | None = None,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WebhookDelivery | None:
        """Send a webhook notification.

        Args:
            event: Event type
            workflow_id: Workflow execution ID
            correlation_id: Correlation ID for tracing
            data: Event data
            metadata: Additional metadata

        Returns:
            Delivery record or None if not sent
        """
        if not self.should_send(event):
            return None

        payload = WebhookPayload(
            event=event.value,
            tenant_id=self.tenant_id,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            data=data or {},
            metadata=metadata or {},
        )

        if self.config.batch_events:
            await self._add_to_batch(payload)
            return None
        else:
            return await self._send_single(payload)

    async def _send_single(self, payload: WebhookPayload) -> WebhookDelivery:
        """Send a single webhook."""
        async with WebhookClient(self.config) as client:
            delivery = await client.send(payload)
            self._deliveries.append(delivery)
            return delivery

    async def _add_to_batch(self, payload: WebhookPayload) -> None:
        """Add payload to batch queue."""
        self._batch_queue.append(payload)

        # Start batch timer if not already running
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._process_batch())

    async def _process_batch(self) -> None:
        """Process batched webhooks."""
        await asyncio.sleep(self.config.batch_delay_seconds)

        if not self._batch_queue:
            return

        # Collect all pending payloads
        payloads = self._batch_queue.copy()
        self._batch_queue.clear()

        # Create batch payload
        batch_payload = WebhookPayload(
            event="batch",
            tenant_id=self.tenant_id,
            data={
                "events": [p.model_dump() for p in payloads],
                "count": len(payloads),
            },
        )

        await self._send_single(batch_payload)

    # =========================================================================
    # Event-specific handlers
    # =========================================================================

    async def on_workflow_started(
        self,
        workflow_id: str,
        definition_id: str,
        input_data: dict[str, Any],
    ) -> WebhookDelivery | None:
        """Handle workflow started event."""
        return await self.notify(
            WebhookEvent.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            data={
                "definition_id": definition_id,
                "input_data": input_data if self.config.include_full_data else None,
            },
        )

    async def on_workflow_complete(
        self,
        workflow_id: str,
        output_data: dict[str, Any],
        duration_seconds: float,
        total_cost_usd: float,
    ) -> WebhookDelivery | None:
        """Handle workflow completed event."""
        return await self.notify(
            WebhookEvent.WORKFLOW_COMPLETE,
            workflow_id=workflow_id,
            data={
                "output_data": output_data if self.config.include_full_data else None,
                "duration_seconds": duration_seconds,
                "total_cost_usd": total_cost_usd,
            },
        )

    async def on_workflow_failed(
        self,
        workflow_id: str,
        error: str,
        error_code: str | None = None,
        failed_node: str | None = None,
    ) -> WebhookDelivery | None:
        """Handle workflow failed event."""
        return await self.notify(
            WebhookEvent.WORKFLOW_FAILED,
            workflow_id=workflow_id,
            data={
                "error": error,
                "error_code": error_code,
                "failed_node": failed_node,
            },
        )

    async def on_node_started(
        self,
        workflow_id: str,
        node_name: str,
        node_type: str,
    ) -> WebhookDelivery | None:
        """Handle node started event."""
        return await self.notify(
            WebhookEvent.NODE_STARTED,
            workflow_id=workflow_id,
            data={
                "node_name": node_name,
                "node_type": node_type,
            },
        )

    async def on_node_complete(
        self,
        workflow_id: str,
        node_name: str,
        node_type: str,
        duration_ms: float,
    ) -> WebhookDelivery | None:
        """Handle node completed event."""
        return await self.notify(
            WebhookEvent.NODE_COMPLETE,
            workflow_id=workflow_id,
            data={
                "node_name": node_name,
                "node_type": node_type,
                "duration_ms": duration_ms,
            },
        )

    async def on_approval_requested(
        self,
        workflow_id: str,
        approval_id: str,
        node_name: str,
        prompt: str,
        options: list[str],
        expires_at: datetime | None = None,
    ) -> WebhookDelivery | None:
        """Handle approval requested event."""
        return await self.notify(
            WebhookEvent.APPROVAL_REQUESTED,
            workflow_id=workflow_id,
            data={
                "approval_id": approval_id,
                "node_name": node_name,
                "prompt": prompt,
                "options": options,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )

    async def on_approval_response(
        self,
        workflow_id: str,
        approval_id: str,
        response: str,
        responded_by: str | None = None,
    ) -> WebhookDelivery | None:
        """Handle approval response event."""
        event = (
            WebhookEvent.APPROVAL_GRANTED
            if response.lower() in ("approve", "approved", "yes")
            else WebhookEvent.APPROVAL_DENIED
        )
        return await self.notify(
            event,
            workflow_id=workflow_id,
            data={
                "approval_id": approval_id,
                "response": response,
                "responded_by": responded_by,
            },
        )

    async def on_progress_update(
        self,
        workflow_id: str,
        percent: float,
        current_step: str | None = None,
        message: str | None = None,
    ) -> WebhookDelivery | None:
        """Handle progress update event."""
        return await self.notify(
            WebhookEvent.PROGRESS_UPDATE,
            workflow_id=workflow_id,
            data={
                "percent": percent,
                "current_step": current_step,
                "message": message,
            },
        )

    async def on_error(
        self,
        workflow_id: str | None,
        error: str,
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> WebhookDelivery | None:
        """Handle error event."""
        return await self.notify(
            WebhookEvent.ERROR,
            workflow_id=workflow_id,
            data={
                "error": error,
                "error_code": error_code,
                "context": context,
            },
        )

    def get_deliveries(self) -> list[WebhookDelivery]:
        """Get all delivery records."""
        return self._deliveries.copy()

    def get_failed_deliveries(self) -> list[WebhookDelivery]:
        """Get failed delivery records."""
        return [d for d in self._deliveries if d.status == "failed"]


# =============================================================================
# Webhook Registry
# =============================================================================


class WebhookRegistry:
    """Registry for managing multiple webhook configurations.

    Allows registering webhooks per tenant or globally,
    and dispatches events to all matching webhooks.
    """

    def __init__(self) -> None:
        """Initialize registry."""
        self._global_webhooks: list[WebhookConfig] = []
        self._tenant_webhooks: dict[str, list[WebhookConfig]] = {}
        self._handlers: dict[str, WorkflowWebhookHandler] = {}

    def register_global(self, config: WebhookConfig) -> None:
        """Register a global webhook (receives all events)."""
        self._global_webhooks.append(config)

    def register_tenant(self, tenant_id: str, config: WebhookConfig) -> None:
        """Register a tenant-specific webhook."""
        if tenant_id not in self._tenant_webhooks:
            self._tenant_webhooks[tenant_id] = []
        self._tenant_webhooks[tenant_id].append(config)

    def get_webhooks(self, tenant_id: str | None = None) -> list[WebhookConfig]:
        """Get all webhooks for a tenant (including global)."""
        webhooks = self._global_webhooks.copy()
        if tenant_id and tenant_id in self._tenant_webhooks:
            webhooks.extend(self._tenant_webhooks[tenant_id])
        return webhooks

    def get_handler(
        self,
        tenant_id: str | None = None,
    ) -> WorkflowWebhookHandler | None:
        """Get or create a handler for tenant webhooks.

        Creates a combined handler that dispatches to all
        matching webhooks.
        """
        cache_key = tenant_id or "__global__"

        if cache_key in self._handlers:
            return self._handlers[cache_key]

        webhooks = self.get_webhooks(tenant_id)
        if not webhooks:
            return None

        # Use first webhook config as primary (for single-webhook case)
        # Multi-webhook dispatch would need a composite handler
        handler = WorkflowWebhookHandler(webhooks[0], tenant_id)
        self._handlers[cache_key] = handler
        return handler

    async def dispatch(
        self,
        event: WebhookEvent,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> list[WebhookDelivery]:
        """Dispatch event to all matching webhooks.

        Args:
            event: Event type
            tenant_id: Tenant ID for filtering
            **kwargs: Event data

        Returns:
            List of delivery records
        """
        deliveries = []
        webhooks = self.get_webhooks(tenant_id)

        for config in webhooks:
            handler = WorkflowWebhookHandler(config, tenant_id)
            delivery = await handler.notify(event, **kwargs)
            if delivery:
                deliveries.append(delivery)

        return deliveries


# Global registry
_registry: WebhookRegistry | None = None


def get_webhook_registry() -> WebhookRegistry:
    """Get global webhook registry."""
    global _registry
    if _registry is None:
        _registry = WebhookRegistry()
    return _registry


def reset_webhook_registry() -> None:
    """Reset webhook registry."""
    global _registry
    _registry = None


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Events
    "WebhookEvent",
    # Models
    "WebhookConfig",
    "WebhookDelivery",
    "WebhookPayload",
    # Client
    "WebhookClient",
    # Handler
    "WorkflowWebhookHandler",
    # Registry
    "WebhookRegistry",
    "get_webhook_registry",
    "reset_webhook_registry",
    # Utilities
    "generate_signature",
    "verify_signature",
]
