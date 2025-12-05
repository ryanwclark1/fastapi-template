"""Email administration feature.

This module provides administrative endpoints for email system management:
- System-wide usage statistics
- Provider health monitoring
- Configuration management across all tenants
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
