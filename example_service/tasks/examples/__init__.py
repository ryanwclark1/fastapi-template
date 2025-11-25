"""Taskiq integration examples.

This package contains examples of using Taskiq for background task processing
with different integrations:

1. fastapi_integration.py - Kicking tasks from FastAPI endpoints
2. faststream_integration.py - Triggering tasks from Faststream message handlers
3. scheduled_messages.py - Scheduled message publishing with taskiq-faststream

Note: APScheduler scheduling has been moved to tasks/scheduler.py (production code).
"""
from .fastapi_integration import router as tasks_router

__all__ = ["tasks_router"]
