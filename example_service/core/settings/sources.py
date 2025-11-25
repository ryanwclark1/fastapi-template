"""Optional YAML and conf.d file sources for Pydantic Settings.

These sources are optional and intended for local/dev convenience.
Environment variables always take precedence in production.

Directory structure:
    conf/
    ├── app.yaml       # Base app config
    ├── app.d/         # App config overrides
    │   ├── 01-cors.yml
    │   └── 02-docs.yml
    ├── db.yaml        # Database config
    ├── rabbit.yaml    # RabbitMQ config
    ├── logging.yaml   # Logging config
    └── otel.yaml      # OpenTelemetry config

Environment variables to override config directories:
    APP_CONFIG_DIR, DB_CONFIG_DIR, RABBIT_CONFIG_DIR, LOGGING_CONFIG_DIR, OTEL_CONFIG_DIR
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file if it exists and yaml is available."""
    if not path.exists() or not YAML_AVAILABLE:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _load_conf_d(dir_path: Path) -> dict[str, Any]:
    """Load and merge all YAML/JSON files from a conf.d directory."""
    if not dir_path.exists():
        return {}

    merged: dict[str, Any] = {}
    files = sorted(
        [p for p in dir_path.iterdir() if p.suffix in {".yml", ".yaml", ".json"}]
    )

    for p in files:
        if p.suffix in {".yml", ".yaml"}:
            part = _load_yaml(p)
        else:
            part = json.loads(p.read_text(encoding="utf-8"))

        if isinstance(part, dict):
            merged.update(part)

    return merged


def app_source() -> dict[str, Any]:
    """Load app settings from YAML files."""
    base = Path(os.getenv("APP_CONFIG_DIR", "conf"))
    return {**_load_yaml(base / "app.yaml"), **_load_conf_d(base / "app.d")}


def db_source() -> dict[str, Any]:
    """Load database settings from YAML files."""
    base = Path(os.getenv("DB_CONFIG_DIR", "conf"))
    return {**_load_yaml(base / "db.yaml"), **_load_conf_d(base / "db.d")}


def rabbit_source() -> dict[str, Any]:
    """Load RabbitMQ settings from YAML files."""
    base = Path(os.getenv("RABBIT_CONFIG_DIR", "conf"))
    return {**_load_yaml(base / "rabbit.yaml"), **_load_conf_d(base / "rabbit.d")}


def logging_source() -> dict[str, Any]:
    """Load logging settings from YAML files."""
    base = Path(os.getenv("LOGGING_CONFIG_DIR", "conf"))
    return {**_load_yaml(base / "logging.yaml"), **_load_conf_d(base / "logging.d")}


def otel_source() -> dict[str, Any]:
    """Load OpenTelemetry settings from YAML files."""
    base = Path(os.getenv("OTEL_CONFIG_DIR", "conf"))
    return {**_load_yaml(base / "otel.yaml"), **_load_conf_d(base / "otel.d")}


def backup_source() -> dict[str, Any]:
    """Load backup settings from YAML files."""
    base = Path(os.getenv("BACKUP_CONFIG_DIR", "conf"))
    return {**_load_yaml(base / "backup.yaml"), **_load_conf_d(base / "backup.d")}
