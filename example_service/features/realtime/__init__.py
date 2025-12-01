"""Realtime feature for WebSocket communication.

This feature provides real-time bidirectional communication:
- WebSocket connection management
- Channel-based pub/sub messaging
- User-targeted notifications
- Event broadcasting from domain events

Usage:
    # In your FastAPI app
    from example_service.features.realtime import router
    app.include_router(router)

    # Connect via WebSocket
    ws://localhost:8000/ws?channels=notifications,updates
"""

from example_service.features.realtime.router import router

__all__ = ["router"]
