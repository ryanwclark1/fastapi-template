"""Tests for data transfer settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from example_service.core.settings.datatransfer import (
    DEFAULT_EXPORT_DIR,
    DataTransferSettings,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clear_datatransfer_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure DATATRANSFER_* env vars don't override defaults during tests."""
    monkeypatch.setenv("DATATRANSFER_EXPORT_DIR", str(DEFAULT_EXPORT_DIR))


class TestDataTransferSettings:
    """Tests for DataTransferSettings."""

    def test_default_values(self):
        """Test default settings values."""
        settings = DataTransferSettings()

        assert settings.export_dir == str(DEFAULT_EXPORT_DIR)
        assert settings.export_retention_hours == 24
        assert settings.enable_compression is False
        assert settings.compression_level == 6
        assert settings.max_import_size_mb == 100
        assert settings.default_batch_size == 100
        assert settings.max_validation_errors == 100
        assert settings.upload_to_storage is False
        assert settings.enable_tenant_isolation is False

    def test_export_path_property(self):
        """Test export_path computed property."""
        settings = DataTransferSettings()
        assert settings.export_path == DEFAULT_EXPORT_DIR

    def test_max_import_size_bytes_property(self):
        """Test max_import_size_bytes computed property."""
        settings = DataTransferSettings(max_import_size_mb=50)
        assert settings.max_import_size_bytes == 50 * 1024 * 1024

    def test_compression_level_bounds(self):
        """Test compression level is within valid range."""
        # Valid range is 1-9
        settings = DataTransferSettings(compression_level=1)
        assert settings.compression_level == 1

        settings = DataTransferSettings(compression_level=9)
        assert settings.compression_level == 9

    def test_batch_size_bounds(self):
        """Test batch size is within valid range."""
        settings = DataTransferSettings(default_batch_size=1)
        assert settings.default_batch_size == 1

        settings = DataTransferSettings(default_batch_size=1000)
        assert settings.default_batch_size == 1000

    def test_ensure_export_dir_creates_directory(self, tmp_path: Path):
        """Test ensure_export_dir creates the directory."""
        export_dir = tmp_path / "exports" / "nested"
        settings = DataTransferSettings(export_dir=str(export_dir))

        # Directory shouldn't exist yet
        assert not export_dir.exists()

        # Call ensure_export_dir
        result = settings.ensure_export_dir()

        # Now it should exist
        assert export_dir.exists()
        assert result == export_dir

    def test_settings_are_frozen(self):
        """Test settings are immutable."""
        settings = DataTransferSettings()
        with pytest.raises(Exception):  # ValidationError for frozen model
            settings.export_dir = "/new/path"


class TestCompressionSettings:
    """Tests for compression-related settings."""

    def test_compression_disabled_by_default(self):
        """Test compression is disabled by default."""
        settings = DataTransferSettings()
        assert settings.enable_compression is False

    def test_compression_enabled(self):
        """Test compression can be enabled."""
        settings = DataTransferSettings(enable_compression=True)
        assert settings.enable_compression is True

    def test_compression_level_default(self):
        """Test default compression level is 6."""
        settings = DataTransferSettings()
        assert settings.compression_level == 6


class TestTenantIsolationSettings:
    """Tests for tenant isolation settings."""

    def test_tenant_isolation_disabled_by_default(self):
        """Test tenant isolation is disabled by default."""
        settings = DataTransferSettings()
        assert settings.enable_tenant_isolation is False

    def test_tenant_isolation_enabled(self):
        """Test tenant isolation can be enabled."""
        settings = DataTransferSettings(enable_tenant_isolation=True)
        assert settings.enable_tenant_isolation is True
