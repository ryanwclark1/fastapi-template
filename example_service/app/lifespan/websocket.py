"""WebSocket connection manager lifespan management."""

from __future__ import annotations

import logging

from .registry import lifespan_registry

logger = logging.getLogger(__name__)

# Track if websocket was started
_websocket_enabled = False


@lifespan_registry.register(
    name="websocket",
    startup_order=40,
    requires=["cache", "messaging"],
)
async def startup_websocket(
    ws_settings: object,
    rabbit_settings: object,
    **kwargs: object,
) -> None:
    """Initialize WebSocket connection manager and event bridge.

    Requires Redis for horizontal scaling and RabbitMQ for event bridge.

    Args:
        ws_settings: WebSocket settings
        rabbit_settings: RabbitMQ settings
        **kwargs: Additional settings (ignored)
    """
    global _websocket_enabled

    from example_service.core.settings.rabbit import RabbitSettings
    from example_service.core.settings.websocket import WebSocketSettings
    from example_service.infra.realtime import (
        start_connection_manager,
        start_event_bridge,
    )

    ws = (
        WebSocketSettings.model_validate(ws_settings)
        if not isinstance(ws_settings, WebSocketSettings)
        else ws_settings
    )
    rabbit = (
        RabbitSettings.model_validate(rabbit_settings)
        if not isinstance(rabbit_settings, RabbitSettings)
        else rabbit_settings
    )

    _websocket_enabled = False
    if ws.enabled:
        try:
            await start_connection_manager()
            _websocket_enabled = True
            logger.info("WebSocket connection manager initialized")

            # Start event bridge (requires RabbitMQ)
            if rabbit.is_configured and ws.event_bridge_enabled:
                bridge_started = await start_event_bridge()
                if bridge_started:
                    logger.info("WebSocket event bridge started")
        except Exception as e:
            logger.warning(
                "Failed to start WebSocket manager, realtime features disabled",
                extra={"error": str(e)},
            )


@lifespan_registry.register(name="websocket")
async def shutdown_websocket(
    ws_settings: object,
    **kwargs: object,
) -> None:
    """Stop WebSocket connection manager and event bridge.

    Args:
        ws_settings: WebSocket settings
        **kwargs: Additional settings (ignored)
    """
    global _websocket_enabled

    from example_service.core.settings.websocket import WebSocketSettings
    from example_service.infra.realtime import (
        stop_connection_manager,
        stop_event_bridge,
    )

    ws = (
        WebSocketSettings.model_validate(ws_settings)
        if not isinstance(ws_settings, WebSocketSettings)
        else ws_settings
    )

    # Stop WebSocket event bridge and connection manager (before RabbitMQ/Redis)
    if ws.enabled and _websocket_enabled:
        await stop_event_bridge()
        logger.info("WebSocket event bridge stopped")
        await stop_connection_manager()
        logger.info("WebSocket connection manager stopped")


def get_websocket_enabled() -> bool:
    """Get whether WebSocket was successfully started.

    Returns:
        True if WebSocket is enabled, False otherwise.
    """
    return _websocket_enabled
