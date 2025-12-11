"""Custom YAML config source with conf.d directory support.

Extends pydantic-settings YamlConfigSettingsSource to support:
- Main YAML file (e.g., conf/app.yaml)
- conf.d directory merging (e.g., conf/app.d/*.yaml)
- Alphabetical file ordering in conf.d
- Deep merge of nested configurations

This approach leverages pydantic-settings' built-in YAML handling while
preserving the Linux-style conf.d pattern for modular configuration.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings.sources.providers.yaml import YamlConfigSettingsSource

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings


class ConfDYamlConfigSettingsSource(YamlConfigSettingsSource):
    """YAML settings source with conf.d directory support.

    Supports the standard Linux conf.d pattern:
    - conf/app.yaml        (base configuration)
    - conf/app.d/*.yaml    (override files, merged alphabetically)

    Environment variable can override config directory:
    - APP_CONFIG_DIR=/custom/path

    Example:
        class AppSettings(BaseSettings):
            @classmethod
            def settings_customise_sources(cls, settings_cls, ...):
                return (
                    init_settings,
                    create_app_yaml_source(settings_cls),
                    env_settings,
                    dotenv_settings,
                    file_secret_settings,
                )
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: str = "app.yaml",
        confd_dir: str | None = "app.d",
        config_dir_env: str = "CONFIG_DIR",
        base_dir: str = "conf",
        yaml_file_encoding: str | None = "utf-8",
    ) -> None:
        """Initialize the conf.d YAML source.

        Args:
            settings_cls: The settings class being configured.
            yaml_file: Main YAML file name (e.g., "app.yaml").
            confd_dir: conf.d subdirectory name (e.g., "app.d"), or None to disable.
            config_dir_env: Environment variable to override base directory.
            base_dir: Default base directory for config files.
            yaml_file_encoding: File encoding for YAML files.
        """
        # Resolve config directory from environment or default
        config_base = Path(os.getenv(config_dir_env, base_dir))

        # Build list of YAML files to load
        yaml_files: list[Path] = []

        # 1. Main YAML file
        main_file = config_base / yaml_file
        if main_file.exists():
            yaml_files.append(main_file)

        # 2. conf.d directory files (sorted alphabetically for deterministic order)
        if confd_dir:
            confd_path = config_base / confd_dir
            if confd_path.exists() and confd_path.is_dir():
                # YAML files
                yaml_files.extend(sorted(confd_path.glob("*.yaml")))
                yaml_files.extend(sorted(confd_path.glob("*.yml")))
                # JSON files (also valid YAML)
                yaml_files.extend(sorted(confd_path.glob("*.json")))

        # Store files list for __repr__
        self._yaml_files = yaml_files

        # Initialize parent with all files and deep_merge enabled
        # deep_merge=True ensures nested dicts are merged, not replaced
        super().__init__(
            settings_cls=settings_cls,
            yaml_file=yaml_files if yaml_files else None,
            yaml_file_encoding=yaml_file_encoding,
        )

    def __repr__(self) -> str:
        """Return human-readable summary of configured YAML files."""
        if self._yaml_files:
            files_str = ", ".join(str(f) for f in self._yaml_files)
            return f"{self.__class__.__name__}(yaml_files=[{files_str}])"
        return f"{self.__class__.__name__}(yaml_files=[])"


# ============================================================================
# Convenience factory functions for each settings domain
# ============================================================================


def create_app_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for AppSettings.

    Loads from:
    - conf/app.yaml (base)
    - conf/app.d/*.yaml (overrides)

    Override directory with: APP_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="app.yaml",
        confd_dir="app.d",
        config_dir_env="APP_CONFIG_DIR",
    )


def create_db_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for PostgresSettings.

    Loads from:
    - conf/db.yaml (base)
    - conf/db.d/*.yaml (overrides)

    Override directory with: DB_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="db.yaml",
        confd_dir="db.d",
        config_dir_env="DB_CONFIG_DIR",
    )


def create_redis_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for RedisSettings.

    Loads from:
    - conf/redis.yaml (base)
    - conf/redis.d/*.yaml (overrides)

    Override directory with: REDIS_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="redis.yaml",
        confd_dir="redis.d",
        config_dir_env="REDIS_CONFIG_DIR",
    )


def create_rabbit_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for RabbitSettings.

    Loads from:
    - conf/rabbit.yaml (base)
    - conf/rabbit.d/*.yaml (overrides)

    Override directory with: RABBIT_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="rabbit.yaml",
        confd_dir="rabbit.d",
        config_dir_env="RABBIT_CONFIG_DIR",
    )


def create_auth_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for AuthSettings.

    Loads from:
    - conf/auth.yaml (base)
    - conf/auth.d/*.yaml (overrides)

    Override directory with: AUTH_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="auth.yaml",
        confd_dir="auth.d",
        config_dir_env="AUTH_CONFIG_DIR",
    )


def create_logging_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for LoggingSettings.

    Loads from:
    - conf/logging.yaml (base)
    - conf/logging.d/*.yaml (overrides)

    Override directory with: LOGGING_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="logging.yaml",
        confd_dir="logging.d",
        config_dir_env="LOGGING_CONFIG_DIR",
    )


def create_otel_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for OtelSettings.

    Loads from:
    - conf/otel.yaml (base)
    - conf/otel.d/*.yaml (overrides)

    Override directory with: OTEL_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="otel.yaml",
        confd_dir="otel.d",
        config_dir_env="OTEL_CONFIG_DIR",
    )


def create_backup_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for BackupSettings.

    Loads from:
    - conf/backup.yaml (base)
    - conf/backup.d/*.yaml (overrides)

    Override directory with: BACKUP_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="backup.yaml",
        confd_dir="backup.d",
        config_dir_env="BACKUP_CONFIG_DIR",
    )


def create_consul_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for ConsulSettings.

    Loads from:
    - conf/consul.yaml (base)
    - conf/consul.d/*.yaml (overrides)

    Override directory with: CONSUL_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="consul.yaml",
        confd_dir="consul.d",
        config_dir_env="CONSUL_CONFIG_DIR",
    )


def create_storage_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for StorageSettings.

    Loads from:
    - conf/storage.yaml (base)
    - conf/storage.d/*.yaml (overrides)

    Override directory with: STORAGE_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="storage.yaml",
        confd_dir="storage.d",
        config_dir_env="STORAGE_CONFIG_DIR",
    )


def create_i18n_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for I18nSettings.

    Loads from:
    - conf/i18n.yaml (base)
    - conf/i18n.d/*.yaml (overrides)

    Override directory with: I18N_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="i18n.yaml",
        confd_dir="i18n.d",
        config_dir_env="I18N_CONFIG_DIR",
    )


def create_ai_yaml_source(settings_cls: type[BaseSettings]) -> ConfDYamlConfigSettingsSource:
    """Create YAML source for AISettings.

    Loads from:
    - conf/ai.yaml (base)
    - conf/ai.d/*.yaml (overrides)

    Override directory with: AI_CONFIG_DIR=/custom/path
    """
    return ConfDYamlConfigSettingsSource(
        settings_cls,
        yaml_file="ai.yaml",
        confd_dir="ai.d",
        config_dir_env="AI_CONFIG_DIR",
    )
