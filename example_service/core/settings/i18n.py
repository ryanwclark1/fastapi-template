"""Internationalization (I18n) settings for multi-language support.

This module provides configuration for locale detection and translation management.
Settings can be configured via environment variables with the I18N_ prefix.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .yaml_sources import create_i18n_yaml_source


class I18nSettings(BaseSettings):
    """Internationalization settings for multi-language support.

    Environment variables use I18N_ prefix.
    Example: I18N_ENABLED=true, I18N_DEFAULT_LOCALE="en"

    Attributes:
        enabled: Enable I18n middleware for locale detection
        default_locale: Default locale to use when detection fails
        supported_locales: List of supported locale codes
        cookie_name: Cookie name for storing user locale preference
        cookie_max_age_days: Cookie expiration in days
        query_param: Query parameter name for locale override
        use_accept_language: Enable Accept-Language header parsing
        use_user_preference: Enable user.preferred_language detection
        use_query_param: Enable query parameter detection
        use_cookie: Enable cookie-based detection
    """

    # Feature toggle
    enabled: bool = Field(
        default=False,
        description="Enable I18n middleware for locale detection",
    )

    # Locale configuration
    default_locale: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$",
        description="Default locale (ISO 639-1 format, e.g., 'en', 'es', 'fr', 'en-US')",
    )

    supported_locales: list[str] = Field(
        default_factory=lambda: ["en", "es", "fr"],
        min_length=1,
        description="List of supported locale codes (JSON array)",
    )

    # Cookie configuration
    cookie_name: str = Field(
        default="locale",
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Cookie name for storing locale preference",
    )

    cookie_max_age_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Cookie expiration in days (1-365)",
    )

    # Detection configuration
    query_param: str = Field(
        default="lang",
        min_length=1,
        max_length=20,
        pattern=r"^[a-z_]+$",
        description="Query parameter name for locale override (e.g., ?lang=es)",
    )

    # Detection sources (priority: user > accept-language > query > cookie > default)
    use_accept_language: bool = Field(
        default=True,
        description="Enable Accept-Language header parsing",
    )

    use_user_preference: bool = Field(
        default=True,
        description="Enable user.preferred_language detection from authenticated user",
    )

    use_query_param: bool = Field(
        default=True,
        description="Enable query parameter detection (?lang=es)",
    )

    use_cookie: bool = Field(
        default=True,
        description="Enable cookie-based locale detection",
    )

    @field_validator("supported_locales")
    @classmethod
    def validate_supported_locales(cls, v: list[str]) -> list[str]:
        """Validate that all supported locales match the expected format.

        Args:
            v: List of locale codes to validate

        Returns:
            Validated list of locale codes

        Raises:
            ValueError: If any locale code is invalid
        """
        if not v:
            raise ValueError("At least one supported locale is required")

        # Validate each locale format (e.g., 'en', 'es', 'en-US')
        locale_pattern = r"^[a-z]{2}(-[A-Z]{2})?$"
        import re

        for locale in v:
            if not re.match(locale_pattern, locale):
                raise ValueError(
                    f"Invalid locale format: {locale}. "
                    f"Expected ISO 639-1 format (e.g., 'en', 'es', 'en-US')"
                )

        # Remove duplicates while preserving order
        seen = set()
        unique_locales = []
        for locale in v:
            if locale not in seen:
                seen.add(locale)
                unique_locales.append(locale)

        return unique_locales

    @field_validator("default_locale")
    @classmethod
    def validate_default_locale_in_supported(
        cls, v: str, info: ValidationInfo
    ) -> str:
        """Validate that default locale is in supported locales.

        Note: This validator runs before supported_locales is validated,
        so we only perform the check if supported_locales exists.

        Args:
            v: Default locale to validate
            info: Validation context with other field values

        Returns:
            Validated default locale

        Raises:
            ValueError: If default locale is not in supported locales
        """
        # Skip validation if we're in the initial pass (supported_locales not set yet)
        if "supported_locales" in info.data:
            supported = info.data["supported_locales"]
            if supported and v not in supported:
                raise ValueError(f"Default locale '{v}' must be in supported_locales: {supported}")
        return v

    @property
    def cookie_max_age_seconds(self) -> int:
        """Get cookie max age in seconds.

        Returns:
            Cookie max age converted to seconds
        """
        return self.cookie_max_age_days * 24 * 60 * 60

    def is_locale_supported(self, locale: str) -> bool:
        """Check if a locale is supported.

        Args:
            locale: Locale code to check

        Returns:
            True if locale is supported, False otherwise
        """
        return locale in self.supported_locales

    model_config = SettingsConfigDict(
        env_prefix="I18N_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,  # Immutable settings
        extra="ignore",
        env_ignore_empty=True,
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
            create_i18n_yaml_source(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
