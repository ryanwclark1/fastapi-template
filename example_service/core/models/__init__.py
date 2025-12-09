"""Database models package.

Import all models here to make them available to Alembic for auto-generation.
"""

from __future__ import annotations

import importlib
from pathlib import Path

# Re-export email models from features/email for backwards compatibility
from example_service.features.email.models import (
    EmailAuditLog,
    EmailConfig,
    EmailProviderType,
    EmailUsageLog,
)
from .post import Post
from .tenant import Tenant
from .user import User


def _import_feature_models() -> list[str]:
    """Import every feature-level models module so metadata is populated."""
    try:
        features_pkg = importlib.import_module("example_service.features")
    except ModuleNotFoundError:
        return []

    features_path = Path(features_pkg.__file__).parent
    imported_modules: set[str] = set()

    for models_file in features_path.glob("**/models.py"):
        relative_module = models_file.relative_to(features_path).with_suffix("")
        module_name = ".".join([features_pkg.__name__, *relative_module.parts])
        if module_name not in imported_modules:
            importlib.import_module(module_name)
            imported_modules.add(module_name)

    return sorted(imported_modules)


_IMPORTED_FEATURE_MODELS = _import_feature_models()

__all__ = [
    "EmailAuditLog",
    "EmailConfig",
    "EmailProviderType",
    "EmailUsageLog",
    "Post",
    "Tenant",
    "User",
]
