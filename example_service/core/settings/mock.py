"""Mock mode settings for development and testing.

This module provides configuration for mock mode, which enables UI development
and testing without requiring external backend services.

Features:
- Multiple user personas for testing different permission levels
- Quick persona switching via environment variable
- Production safety validator
- Custom fixture path support
- Request/response logging for debugging

Environment Variables:
    MOCK_MODE: Enable mock mode (default: false)
    MOCK_PERSONA: Active persona name (default: admin)
    MOCK_FIXTURES_PATH: Custom path to fixture JSON files
    MOCK_LOG_REQUESTS: Log mock request/response for debugging

Available Personas:
    - admin: Full admin access with all permissions
    - user: Standard user with common permissions
    - readonly: Read-only access for testing permission denial
    - service: Service account for backend-to-backend testing
    - multitenant_admin: Cross-tenant admin access
    - limited_user: Minimal permissions for fine-grained testing

Example:
    Enable mock mode for UI development::

        export MOCK_MODE=true
        uvicorn example_service.main:app --reload

    Quick persona switching::

        export MOCK_MODE=true
        export MOCK_PERSONA=readonly
        uvicorn example_service.main:app --reload

    With custom fixtures::

        export MOCK_MODE=true
        export MOCK_FIXTURES_PATH=/path/to/my/fixtures
        uvicorn example_service.main:app --reload
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_mock_yaml_source


class MockUserSettings(BaseModel):
    """Settings for a mock user persona.

    This model defines a mock user persona that is used when mock mode is enabled.
    Multiple personas are pre-defined for testing different permission levels.
    """

    user_id: str = Field(
        default="dev-user-00000000-0000-0000-0000-000000000001",
        description="UUID for the mock user",
    )
    email: str | None = Field(
        default="dev@example.com",
        description="Email for the mock user (None for service accounts)",
    )
    tenant_id: str = Field(
        default="dev-tenant-00000000-0000-0000-0000-000000000001",
        description="Tenant UUID for the mock user",
    )
    tenant_slug: str = Field(
        default="dev-tenant",
        description="Tenant slug for the mock user",
    )
    session_id: str = Field(
        default="dev-session-00000000-0000-0000-0000-000000000001",
        description="Session UUID for the mock user",
    )
    roles: list[str] = Field(
        default_factory=lambda: ["admin", "user"],
        description="Roles for the mock user",
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Permissions/ACLs for the mock user",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the mock user",
    )


# Pre-defined personas for different testing scenarios
DEFAULT_PERSONAS: dict[str, dict[str, Any]] = {
    "admin": {
        "user_id": "dev-admin-00000000-0000-0000-0000-000000000001",
        "email": "admin@dev.example.com",
        "tenant_id": "dev-tenant-00000000-0000-0000-0000-000000000001",
        "tenant_slug": "dev-tenant",
        "session_id": "dev-session-admin",
        "roles": ["admin", "user"],
        "permissions": ["#"],  # Accent-Auth superuser wildcard - full access
        "metadata": {"name": "Dev Admin User", "can_switch_tenants": False},
    },
    "user": {
        "user_id": "dev-user-00000000-0000-0000-0000-000000000002",
        "email": "user@dev.example.com",
        "tenant_id": "dev-tenant-00000000-0000-0000-0000-000000000001",
        "tenant_slug": "dev-tenant",
        "session_id": "dev-session-user",
        "roles": ["user"],
        "permissions": [
            "confd.users.me.read",
            "confd.users.me.update",
            "confd.voicemails.me.read",
            "confd.voicemails.me.update",
            "confd.funckeys.me.read",
            "confd.funckeys.me.update",
            "confd.lines.me.read",
            "confd.forwards.me.read",
            "confd.forwards.me.update",
            "confd.services.me.read",
            "confd.services.me.update",
            "calld.calls.read",
            "calld.calls.create",
            "calld.transfers.create",
            "calld.voicemails.read",
            "dird.directories.read",
            "dird.personal.read",
            "dird.personal.create",
            "dird.personal.update",
            "dird.personal.delete",
            "webhookd.subscriptions.me.read",
            "webhookd.subscriptions.me.create",
            "webhookd.subscriptions.me.update",
            "webhookd.subscriptions.me.delete",
        ],
        "metadata": {"name": "Dev Regular User"},
    },
    "readonly": {
        "user_id": "dev-readonly-00000000-0000-0000-0000-000000000003",
        "email": "readonly@dev.example.com",
        "tenant_id": "dev-tenant-00000000-0000-0000-0000-000000000001",
        "tenant_slug": "dev-tenant",
        "session_id": "dev-session-readonly",
        "roles": ["viewer"],
        "permissions": [
            "confd.*.*.read",
            "calld.*.read",
            "call-logd.*.read",
            "dird.*.read",
            "webhookd.*.read",
        ],
        "metadata": {"name": "Dev Read-Only User"},
    },
    "service": {
        "user_id": "dev-service-00000000-0000-0000-0000-000000000004",
        "email": None,
        "tenant_id": "dev-tenant-00000000-0000-0000-0000-000000000001",
        "tenant_slug": "dev-tenant",
        "session_id": "dev-session-service",
        "roles": ["service"],
        "permissions": ["*.*.*"],  # Service-level wildcard
        "metadata": {"name": "Dev Service Account", "is_service": True},
    },
    "multitenant_admin": {
        "user_id": "dev-mtadmin-00000000-0000-0000-0000-000000000005",
        "email": "mtadmin@dev.example.com",
        "tenant_id": "dev-tenant-00000000-0000-0000-0000-000000000001",
        "tenant_slug": "dev-tenant",
        "session_id": "dev-session-mtadmin",
        "roles": ["admin", "super_admin"],
        "permissions": ["#", "*.*.*"],  # Cross-tenant access
        "metadata": {"name": "Dev Multi-Tenant Admin", "can_switch_tenants": True},
    },
    "limited_user": {
        "user_id": "dev-limited-00000000-0000-0000-0000-000000000006",
        "email": "limited@dev.example.com",
        "tenant_id": "dev-tenant-00000000-0000-0000-0000-000000000001",
        "tenant_slug": "dev-tenant",
        "session_id": "dev-session-limited",
        "roles": ["user"],
        "permissions": [
            "confd.users.me.read",
            "confd.users.me.update",
        ],  # Very minimal permissions for testing fine-grained access
        "metadata": {"name": "Dev Limited User"},
    },
}


class MockModeSettings(BaseSettings):
    """Settings for mock mode operation.

    Mock mode enables the service to operate without external services by providing
    mock implementations of all service clients with realistic sample data.

    Features:
    - Multiple user personas for testing different permission levels
    - Quick persona switching via MOCK_PERSONA environment variable
    - Production safety validator (prevents mock mode in production)
    - Custom fixture path support for custom mock data
    - Request/response logging for debugging

    Environment Variables:
        MOCK_MODE: Enable mock mode (default: false)
        MOCK_PERSONA: Active persona name (default: admin)
        MOCK_FIXTURES_PATH: Custom path to fixture JSON files
        MOCK_LOG_REQUESTS: Log mock request/response for debugging

    YAML Configuration:
        conf/mock.yaml (base)
        conf/mock.d/*.yaml (overrides)

    Example:
        Quick persona switching::

            # Test as admin (default)
            export MOCK_MODE=true

            # Test as regular user
            export MOCK_MODE=true
            export MOCK_PERSONA=user

            # Test permission denial with readonly user
            export MOCK_MODE=true
            export MOCK_PERSONA=readonly
    """

    model_config = SettingsConfigDict(
        env_prefix="MOCK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        populate_by_name=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    # Core mock mode toggle
    mode: bool = Field(
        default=False,
        description="Enable mock mode for UI development without backend services. "
        "Set MOCK_MODE=true environment variable to enable.",
    )

    # Persona selection
    persona: str = Field(
        default="admin",
        description="Active persona name. Available: admin, user, readonly, service, "
        "multitenant_admin, limited_user. Set via MOCK_PERSONA env var.",
    )

    # Pre-defined personas (can be extended via YAML)
    personas: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: DEFAULT_PERSONAS.copy(),
        description="Mock user persona configurations. Each persona has different "
        "permissions for testing various access levels.",
    )

    # Fixture configuration
    fixtures_path: Path | None = Field(
        default=None,
        description="Custom path to fixture JSON files. "
        "If not set, uses built-in fixtures from infra/mock/fixtures/",
    )

    # Debugging
    log_requests: bool = Field(
        default=False,
        description="Log mock request/response details for debugging",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Customize settings source precedence: init > yaml > env > dotenv > secrets."""
        return (
            init_settings,
            create_mock_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @model_validator(mode="after")
    def validate_production_safety(self) -> MockModeSettings:
        """Ensure mock mode cannot be enabled in production.

        This is a critical security check that prevents accidentally
        enabling mock authentication in production environments.

        Raises:
            ValueError: If mode is True in production environment
        """
        if self.mode:
            # Import here to avoid circular dependency
            from .loader import get_app_settings

            app_settings = get_app_settings()
            if app_settings.environment == "production":
                msg = (
                    "CRITICAL SECURITY ERROR: Mock mode (MOCK_MODE=true) "
                    "is enabled in production environment. This bypasses all authentication "
                    "and MUST NOT be used in production. Set MOCK_MODE=false."
                )
                raise ValueError(
                    msg
                )
        return self

    @property
    def enabled(self) -> bool:
        """Check if mock mode is enabled.

        Returns:
            True if mock mode is enabled via MOCK_MODE=true
        """
        return self.mode

    @property
    def is_mock_mode(self) -> bool:
        """Alias for enabled property.

        Returns:
            True if mock mode is enabled
        """
        return self.mode

    def get_persona_config(self, persona_name: str | None = None) -> dict[str, Any]:
        """Get mock user configuration for specified persona.

        Args:
            persona_name: Persona name (admin, user, readonly, service,
                         multitenant_admin, limited_user).
                         If None, uses the active persona from settings.

        Returns:
            Mock user configuration dictionary.

        Raises:
            ValueError: If persona not found in personas dict.

        Example:
            config = mock_settings.get_persona_config("readonly")
            user = MockUserSettings(**config)
        """
        name = persona_name or self.persona

        if name not in self.personas:
            available = ", ".join(self.personas.keys())
            raise ValueError(
                f"Mock persona '{name}' not found. Available personas: {available}"
            )

        return self.personas[name]

    def get_active_user(self) -> MockUserSettings:
        """Get the active mock user based on current persona.

        Returns:
            MockUserSettings for the active persona.

        Example:
            if mock_settings.enabled:
                user = mock_settings.get_active_user()
                print(f"Mock user: {user.user_id}")
        """
        config = self.get_persona_config()
        return MockUserSettings(**config)

    @property
    def active_user(self) -> MockUserSettings:
        """Property alias for get_active_user().

        Returns:
            MockUserSettings for the active persona.
        """
        return self.get_active_user()


__all__ = ["DEFAULT_PERSONAS", "MockModeSettings", "MockUserSettings"]
