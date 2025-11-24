"""Taskiq integration examples.

This package contains comprehensive examples of using Taskiq for
background task processing with different integrations:

1. scheduled_tasks.py - Cron-like scheduled tasks
2. fastapi_integration.py - Kicking tasks from FastAPI endpoints
3. faststream_integration.py - Triggering tasks from Faststream message handlers
"""

from .fastapi_integration import router as tasks_router

__all__ = ["tasks_router"]
