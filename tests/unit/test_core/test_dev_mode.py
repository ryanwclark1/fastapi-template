"""Tests for development mode authentication."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request
import pytest

from example_service.core.schemas.auth import AuthUser
from example_service.core.settings.auth import AuthSettings


class TestDevModeSettings:
    """Test development mode settings and validation."""

    def test_dev_mode_blocked_in_production(self, monkeypatch):
        """Dev mode should raise error in production environment."""
        # Mock app settings to return production
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "production"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            with pytest.raises(ValueError, match="CRITICAL SECURITY ERROR"):
                AuthSettings()

    def test_dev_mode_allowed_in_development(self, monkeypatch):
        """Dev mode should work in development environment."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            assert settings.is_dev_mode is True

    def test_dev_mode_allowed_in_test(self, monkeypatch):
        """Dev mode should work in test environment."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "test"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            assert settings.is_dev_mode is True

    def test_dev_mode_disabled_by_default(self):
        """Dev mode should be disabled by default."""
        settings = AuthSettings()
        assert settings.is_dev_mode is False
        assert settings.dev_mode is False

    def test_get_mock_user_config_default(self, monkeypatch):
        """Should return default mock user config."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config()

            # Default is "admin"
            assert config["user_id"] == "dev-admin-001"
            assert config["email"] == "admin@dev.local"
            assert "#" in config["acl"]

    def test_get_mock_user_config_explicit_persona(self, monkeypatch):
        """Should return specified persona config."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config("readonly")

            assert config["user_id"] == "dev-readonly-001"
            assert config["roles"] == ["viewer"]

    def test_get_mock_user_config_all_personas(self, monkeypatch):
        """Should have all 6 required personas."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()

            # Test all required personas exist
            personas = ["admin", "user", "readonly", "service", "multitenant_admin", "limited_user"]
            for persona in personas:
                config = settings.get_mock_user_config(persona)
                assert config is not None
                assert "metadata" in config
                assert "tenant_uuid" in config["metadata"]

    def test_get_mock_user_config_invalid_persona(self, monkeypatch):
        """Should raise ValueError for invalid persona."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()

            with pytest.raises(ValueError, match="not found"):
                settings.get_mock_user_config("nonexistent")

    def test_admin_persona_has_superuser_acl(self, monkeypatch):
        """Admin persona should have # ACL wildcard."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config("admin")

            assert "#" in config["acl"]
            assert config["user_id"] is not None
            assert config["email"] == "admin@dev.local"

    def test_multitenant_admin_has_cross_tenant_access(self, monkeypatch):
        """Multitenant admin should have cross-tenant ACLs."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config("multitenant_admin")

            assert "#" in config["acl"]
            assert "*.*.*" in config["acl"]
            assert config["metadata"].get("can_switch_tenants") is True

    def test_limited_user_has_specific_acls(self, monkeypatch):
        """Limited user should have very specific ACL patterns."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config("limited_user")

            # Should have very specific ACLs, not wildcards
            assert "confd.users.me.read" in config["acl"]
            assert "confd.users.me.update" in config["acl"]
            assert "#" not in config["acl"]  # No superuser access

    def test_service_persona_has_service_id(self, monkeypatch):
        """Service persona should have service_id, not user_id."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config("service")

            assert "service_id" in config
            assert "user_id" not in config or config.get("user_id") is None


class TestDevModeDependencies:
    """Test dev mode in auth dependencies."""

    @pytest.fixture
    def mock_auth_settings(self, monkeypatch):
        """Mock auth settings with dev mode enabled."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")
            monkeypatch.setenv("AUTH_DEV_MOCK_USER", "admin")

            # Clear cached settings
            from example_service.core.settings.loader import clear_settings_cache

            clear_settings_cache()

            yield

            clear_settings_cache()

    async def test_accent_auth_returns_mock_user(self, mock_auth_settings, monkeypatch):
        """Accent-Auth should return mock user in dev mode."""
        from example_service.core.dependencies import accent_auth

        # Reload the module to pick up new settings
        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        # Create mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        # Call get_current_user without token
        user = await accent_auth.get_current_user(
            request=mock_request,
            x_auth_token=None,
            accent_tenant=None,
            cache=None,
        )

        assert isinstance(user, AuthUser)
        assert user.user_id == "dev-admin-001"
        assert user.email == "admin@dev.local"
        assert user.tenant_id == "dev-tenant-001"
        assert "#" in user.permissions

    async def test_persona_switching_via_env(self, mock_auth_settings, monkeypatch):
        """Should respect AUTH_DEV_MOCK_USER environment variable."""
        monkeypatch.setenv("AUTH_DEV_MOCK_USER", "readonly")

        from example_service.core.dependencies import accent_auth

        # Reload settings
        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        # Create mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        user = await accent_auth.get_current_user(
            request=mock_request,
            x_auth_token=None,
            accent_tenant=None,
            cache=None,
        )

        assert user.user_id == "dev-readonly-001"
        assert user.roles == ["viewer"]

    async def test_mock_user_stored_in_request_state(self, mock_auth_settings, monkeypatch):
        """Mock user should be stored in request.state."""
        from example_service.core.dependencies import accent_auth

        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        # Create mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        user = await accent_auth.get_current_user(
            request=mock_request,
            x_auth_token=None,
            accent_tenant=None,
            cache=None,
        )

        assert mock_request.state.user == user
        assert mock_request.state.tenant_uuid == user.tenant_id

    async def test_dev_mode_logs_warning(self, mock_auth_settings, monkeypatch, caplog):
        """Dev mode should log warning for each request."""
        import logging

        from example_service.core.dependencies import accent_auth

        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        # Create mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        with caplog.at_level(logging.WARNING):
            await accent_auth.get_current_user(
                request=mock_request,
                x_auth_token=None,
                accent_tenant=None,
                cache=None,
            )

        # Check for dev mode warning
        assert any("DEV MODE" in record.message for record in caplog.records)

    async def test_dev_mode_disabled_requires_token(self, monkeypatch):
        """With dev mode disabled, should require token."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "false")

            from example_service.core.dependencies import accent_auth
            from example_service.core.settings.loader import clear_settings_cache

            clear_settings_cache()
            monkeypatch.setattr(
                accent_auth,
                "auth_settings",
                AuthSettings(),
            )

            # Create mock request
            mock_request = AsyncMock(spec=Request)
            mock_request.state = type("State", (), {})()

            # Should raise HTTPException without token
            with pytest.raises(HTTPException) as exc_info:
                await accent_auth.get_current_user(
                    request=mock_request,
                    x_auth_token=None,
                    accent_tenant=None,
                    cache=None,
                )

            assert exc_info.value.status_code == 401

            clear_settings_cache()


class TestAuthUserProperties:
    """Test new AuthUser properties."""

    def test_tenant_id_property(self):
        """Should extract tenant_uuid from metadata."""
        user = AuthUser(
            user_id="test",
            metadata={"tenant_uuid": "tenant-123", "tenant_slug": "acme"},
        )

        assert user.tenant_id == "tenant-123"
        assert user.tenant_uuid == "tenant-123"  # Alias

    def test_session_id_property(self):
        """Should extract session_uuid from metadata."""
        user = AuthUser(
            user_id="test",
            metadata={"session_uuid": "session-456"},
        )

        assert user.session_id == "session-456"

    def test_properties_return_none_when_missing(self):
        """Should return None when metadata keys missing."""
        user = AuthUser(user_id="test", metadata={})

        assert user.tenant_id is None
        assert user.tenant_uuid is None
        assert user.session_id is None

    def test_tenant_uuid_alias_consistency(self):
        """tenant_id and tenant_uuid should return same value."""
        user = AuthUser(
            user_id="test",
            metadata={"tenant_uuid": "tenant-abc"},
        )

        assert user.tenant_id == user.tenant_uuid
        assert user.tenant_id is user.tenant_uuid  # Same object reference

    def test_properties_with_mock_user(self, monkeypatch):
        """Properties should work with mock user from dev mode."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")

            settings = AuthSettings()
            config = settings.get_mock_user_config("admin")

            user = AuthUser(**config)

            assert user.tenant_id == "dev-tenant-001"
            assert user.tenant_uuid == "dev-tenant-001"
            assert user.session_id == "dev-session-admin"


class TestDevModeIntegration:
    """Integration tests for dev mode functionality."""

    @pytest.fixture
    def enable_dev_mode(self, monkeypatch):
        """Enable dev mode for integration tests."""
        with patch("example_service.core.settings.auth.get_app_settings") as mock_get_app:
            mock_app_settings = type("AppSettings", (), {"environment": "development"})()
            mock_get_app.return_value = mock_app_settings

            monkeypatch.setenv("AUTH_DEV_MODE", "true")
            monkeypatch.setenv("AUTH_DEV_MOCK_USER", "admin")

            from example_service.core.settings.loader import clear_settings_cache

            clear_settings_cache()

            yield

            clear_settings_cache()

    async def test_admin_has_all_permissions(self, enable_dev_mode, monkeypatch):
        """Admin persona should pass all ACL checks."""
        from example_service.core.dependencies import accent_auth

        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        user = await accent_auth.get_current_user(
            request=mock_request,
            x_auth_token=None,
            accent_tenant=None,
            cache=None,
        )

        # Admin should have superuser ACL
        assert "#" in user.permissions

    async def test_readonly_lacks_write_permissions(self, enable_dev_mode, monkeypatch):
        """Readonly persona should only have read permissions."""
        monkeypatch.setenv("AUTH_DEV_MOCK_USER", "readonly")

        from example_service.core.dependencies import accent_auth
        from example_service.core.settings.loader import clear_settings_cache

        clear_settings_cache()
        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        user = await accent_auth.get_current_user(
            request=mock_request,
            x_auth_token=None,
            accent_tenant=None,
            cache=None,
        )

        # Should only have read permissions
        assert all("read" in acl for acl in user.permissions if acl != "#")
        assert "#" not in user.permissions  # Not a superuser

    async def test_service_account_identified_correctly(self, enable_dev_mode, monkeypatch):
        """Service persona should be identified as service."""
        monkeypatch.setenv("AUTH_DEV_MOCK_USER", "service")

        from example_service.core.dependencies import accent_auth
        from example_service.core.settings.loader import clear_settings_cache

        clear_settings_cache()
        monkeypatch.setattr(
            accent_auth,
            "auth_settings",
            AuthSettings(),
        )

        mock_request = AsyncMock(spec=Request)
        mock_request.state = type("State", (), {})()

        user = await accent_auth.get_current_user(
            request=mock_request,
            x_auth_token=None,
            accent_tenant=None,
            cache=None,
        )

        # Should be identified as service
        assert user.is_service
        assert not user.is_user
        assert user.service_id is not None
