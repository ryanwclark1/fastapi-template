"""Database models package.

Import all models here to make them available to Alembic for auto-generation.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

from .post import Post
from .tenant import Tenant
from .user import User


def _load_module_from_path(module_name: str, module_path: Path) -> None:
    """Load a module directly from a file without importing its package.

    This avoids executing feature package __init__ files, which often pull in
    optional dependencies (FastAPI routers, external services, etc.) that
    aren't installed in Alembic environments.
    """
    if module_name in sys.modules:
        return

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {module_name} at {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise


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
            _load_module_from_path(module_name, models_file)
            imported_modules.add(module_name)

    return sorted(imported_modules)


_IMPORTED_FEATURE_MODELS = _import_feature_models()

_EMAIL_MODEL_EXPORTS = {
    "EmailAuditLog",
    "EmailConfig",
    "EmailProviderType",
    "EmailUsageLog",
}


def __getattr__(name: str):
    """Lazily load email models for backwards compatibility."""
    if name in _EMAIL_MODEL_EXPORTS:
        email_models = importlib.import_module("example_service.features.email.models")
        value = getattr(email_models, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    *_EMAIL_MODEL_EXPORTS,
    "Post",
    "Tenant",
    "User",
]
