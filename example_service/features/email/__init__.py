"""Email configuration feature exports.

This module now exposes feature components lazily so importing the
package does not pull in optional infrastructure dependencies. Alembic
and other tooling can safely import :mod:`example_service.features.email`
without requiring the full email stack to be installed.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from example_service.features.email.models import (
        EmailAuditLog,
        EmailConfig,
        EmailProviderType,
        EmailUsageLog,
    )
    from example_service.features.email.repository import (
        EmailAuditLogRepository,
        EmailConfigRepository,
        EmailUsageLogRepository,
        get_email_audit_log_repository,
        get_email_config_repository,
        get_email_usage_log_repository,
    )
    from example_service.features.email.router import router
    from example_service.features.email.service import EmailConfigService

__all__ = [
    "EmailAuditLog",
    "EmailAuditLogRepository",
    "EmailConfig",
    "EmailConfigRepository",
    "EmailConfigService",
    "EmailProviderType",
    "EmailUsageLog",
    "EmailUsageLogRepository",
    "get_email_audit_log_repository",
    "get_email_config_repository",
    "get_email_usage_log_repository",
    "router",
]

_ATTR_TO_MODULE: dict[str, str] = {
    # Database models
    "EmailAuditLog": "example_service.features.email.models",
    "EmailConfig": "example_service.features.email.models",
    "EmailProviderType": "example_service.features.email.models",
    "EmailUsageLog": "example_service.features.email.models",
    # Repository exports
    "EmailAuditLogRepository": "example_service.features.email.repository",
    "EmailConfigRepository": "example_service.features.email.repository",
    "EmailUsageLogRepository": "example_service.features.email.repository",
    "get_email_audit_log_repository": "example_service.features.email.repository",
    "get_email_config_repository": "example_service.features.email.repository",
    "get_email_usage_log_repository": "example_service.features.email.repository",
    # Services/routers
    "EmailConfigService": "example_service.features.email.service",
    "router": "example_service.features.email.router",
}


def __getattr__(name: str) -> Any:
    """Lazily import feature components when accessed."""
    module_path = _ATTR_TO_MODULE.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    base_attrs = set(globals().keys()) | set(__all__)
    return sorted(base_attrs)
