"""AI configuration manager for tenant-aware provider settings.

Handles resolution of AI provider configuration with tenant overrides:
1. Check tenant-specific configuration in database
2. Fall back to service-level defaults from settings
3. Decrypt API keys
4. Validate configuration
5. Return ProviderConfig for factory
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from example_service.core.database.types import decrypt_value, encrypt_value
from example_service.core.settings import get_ai_settings
from example_service.features.ai.models import (
    AIProviderType,
    TenantAIConfig,
    TenantAIFeature,
)
from example_service.infra.ai.providers.base import ProviderConfig

if TYPE_CHECKING:
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _get_ai_encryption_key() -> str | None:
    """Get AI encryption key from environment.

    Returns:
        Encryption key from AI_ENCRYPTION_KEY env var, or None if not set
    """
    return os.getenv("AI_ENCRYPTION_KEY")

class AIConfigManager:
    """Manages AI configuration with tenant-aware overrides.

    Resolves provider configuration in priority order:
    1. Tenant-specific config (from database)
    2. Service defaults (from settings)

    Handles:
    - API key encryption/decryption
    - Feature flag checking
    - Provider validation
    - Model selection
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize config manager.

        Args:
            session: Database session for querying tenant configs
        """
        self.session = session
        self.settings = get_ai_settings()

    async def get_transcription_config(
        self,
        tenant_id: str,
        provider_override: str | None = None,
    ) -> ProviderConfig:
        """Get transcription provider configuration for tenant.

        Args:
            tenant_id: Tenant identifier
            provider_override: Optional provider to use instead of default

        Returns:
            ProviderConfig with resolved settings

        Raises:
            ValueError: If transcription is disabled or misconfigured
        """
        # Check if transcription is enabled for tenant
        if not await self._is_feature_enabled(tenant_id, "transcription"):
            raise ValueError(f"Transcription is disabled for tenant {tenant_id}")

        # Determine which provider to use
        provider_name = provider_override or self.settings.default_transcription_provider

        # Try to get tenant-specific config
        tenant_config = await self._get_tenant_config(
            tenant_id, AIProviderType.TRANSCRIPTION, provider_name
        )

        if tenant_config:
            return await self._build_config_from_tenant(tenant_config, provider_name)

        # Fall back to service defaults
        return self._build_config_from_settings(provider_name, "transcription")

    async def get_llm_config(
        self,
        tenant_id: str,
        provider_override: str | None = None,
    ) -> ProviderConfig:
        """Get LLM provider configuration for tenant.

        Args:
            tenant_id: Tenant identifier
            provider_override: Optional provider to use instead of default

        Returns:
            ProviderConfig with resolved settings

        Raises:
            ValueError: If LLM features are disabled or misconfigured
        """
        # Determine which provider to use
        provider_name = provider_override or self.settings.default_llm_provider

        # Try to get tenant-specific config
        tenant_config = await self._get_tenant_config(
            tenant_id, AIProviderType.LLM, provider_name
        )

        if tenant_config:
            return await self._build_config_from_tenant(tenant_config, provider_name)

        # Fall back to service defaults
        return self._build_config_from_settings(provider_name, "llm")

    async def get_pii_redaction_config(self, tenant_id: str) -> dict[str, Any]:
        """Get PII redaction configuration for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Dictionary with PII redaction settings

        Raises:
            ValueError: If PII redaction is disabled
        """
        if not await self._is_feature_enabled(tenant_id, "pii_redaction"):
            raise ValueError(f"PII redaction is disabled for tenant {tenant_id}")

        # Get tenant-specific settings
        features = await self._get_tenant_features(tenant_id)

        entity_types = (
            features.pii_entity_types
            if features and features.pii_entity_types
            else self.settings.default_pii_entity_types
        )

        confidence_threshold = (
            features.pii_confidence_threshold
            if features and features.pii_confidence_threshold is not None
            else self.settings.pii_confidence_threshold
        )

        return {
            "service_url": self.settings.accent_redaction_url,
            "api_key": (
                self.settings.accent_redaction_api_key.get_secret_value()
                if self.settings.accent_redaction_api_key
                else None
            ),
            "entity_types": entity_types,
            "confidence_threshold": confidence_threshold,
            "redaction_method": self.settings.pii_redaction_method,
        }

    async def get_feature_settings(self, tenant_id: str) -> dict[str, Any]:
        """Get all AI feature settings for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Dictionary with all feature flags and settings
        """
        features = await self._get_tenant_features(tenant_id)

        if not features:
            # Return service defaults
            return {
                "transcription_enabled": self.settings.enable_transcription,
                "pii_redaction_enabled": self.settings.enable_pii_redaction,
                "summary_enabled": self.settings.enable_summarization,
                "sentiment_enabled": self.settings.enable_sentiment_analysis,
                "coaching_enabled": self.settings.enable_coaching_analysis,
                "max_audio_duration_seconds": self.settings.max_audio_duration_seconds,
                "max_concurrent_jobs": self.settings.max_concurrent_transcriptions,
            }

        return {
            "transcription_enabled": features.transcription_enabled,
            "pii_redaction_enabled": features.pii_redaction_enabled,
            "summary_enabled": features.summary_enabled,
            "sentiment_enabled": features.sentiment_enabled,
            "coaching_enabled": features.coaching_enabled,
            "max_audio_duration_seconds": (
                features.max_audio_duration_seconds or self.settings.max_audio_duration_seconds
            ),
            "max_concurrent_jobs": (
                features.max_concurrent_jobs or self.settings.max_concurrent_transcriptions
            ),
            "monthly_budget_usd": features.monthly_budget_usd,
            "enable_cost_alerts": features.enable_cost_alerts,
        }

    async def _get_tenant_config(
        self,
        tenant_id: str,
        provider_type: AIProviderType,
        provider_name: str,
    ) -> TenantAIConfig | None:
        """Get tenant-specific provider configuration.

        Args:
            tenant_id: Tenant identifier
            provider_type: Type of provider (LLM, TRANSCRIPTION, etc.)
            provider_name: Specific provider name

        Returns:
            TenantAIConfig if exists and active, None otherwise
        """
        stmt = (
            select(TenantAIConfig)
            .where(
                TenantAIConfig.tenant_id == tenant_id,
                TenantAIConfig.provider_type == provider_type,
                TenantAIConfig.provider_name == provider_name,
                TenantAIConfig.is_active == True,  # noqa: E712
            )
            .order_by(TenantAIConfig.created_at.desc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_tenant_features(self, tenant_id: str) -> TenantAIFeature | None:
        """Get tenant AI feature settings.

        Args:
            tenant_id: Tenant identifier

        Returns:
            TenantAIFeature if exists, None otherwise
        """
        stmt = select(TenantAIFeature).where(TenantAIFeature.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _is_feature_enabled(self, tenant_id: str, feature: str) -> bool:
        """Check if specific AI feature is enabled for tenant.

        Args:
            tenant_id: Tenant identifier
            feature: Feature name (transcription|pii_redaction|summary|sentiment|coaching)

        Returns:
            True if feature is enabled, False otherwise
        """
        features = await self._get_tenant_features(tenant_id)

        if not features:
            # Use service defaults
            feature_map = {
                "transcription": self.settings.enable_transcription,
                "pii_redaction": self.settings.enable_pii_redaction,
                "summary": self.settings.enable_summarization,
                "sentiment": self.settings.enable_sentiment_analysis,
                "coaching": self.settings.enable_coaching_analysis,
            }
            return feature_map.get(feature, False)

        # Use tenant-specific settings
        feature_map = {
            "transcription": features.transcription_enabled,
            "pii_redaction": features.pii_redaction_enabled,
            "summary": features.summary_enabled,
            "sentiment": features.sentiment_enabled,
            "coaching": features.coaching_enabled,
        }
        return feature_map.get(feature, False)

    async def _build_config_from_tenant(
        self,
        tenant_config: TenantAIConfig,
        provider_name: str,
    ) -> ProviderConfig:
        """Build ProviderConfig from tenant configuration.

        Args:
            tenant_config: Tenant-specific configuration
            provider_name: Provider name

        Returns:
            ProviderConfig with decrypted API key
        """
        # Decrypt API key if present
        api_key = None
        if tenant_config.encrypted_api_key:
            key = _get_ai_encryption_key()
            if not key:
                raise ValueError("AI_ENCRYPTION_KEY environment variable not set")
            api_key = decrypt_value(tenant_config.encrypted_api_key, key)

        return ProviderConfig(
            provider_name=provider_name,
            api_key=api_key,
            model_name=tenant_config.model_name,
            timeout=self.settings.llm_request_timeout_seconds,
            max_retries=self.settings.max_retries,
            additional_config=tenant_config.config_json or {},
        )

    def _build_config_from_settings(
        self,
        provider_name: str,
        provider_type: str,
    ) -> ProviderConfig:
        """Build ProviderConfig from service settings.

        Args:
            provider_name: Provider name
            provider_type: Provider type (transcription|llm)

        Returns:
            ProviderConfig with service-level settings
        """
        # Get API key from settings
        api_key = self._get_api_key_from_settings(provider_name)

        # Get model name
        model_name = None
        if provider_type == "transcription":
            model_name = self.settings.default_transcription_model
        elif provider_type == "llm":
            model_name = self.settings.default_llm_model

        # Build base URL for internal services
        base_url = None
        if provider_name == "accent_stt":
            base_url = self.settings.accent_stt_url
        elif provider_name == "ollama":
            base_url = self.settings.ollama_base_url

        return ProviderConfig(
            provider_name=provider_name,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            timeout=self.settings.llm_request_timeout_seconds,
            max_retries=self.settings.max_retries,
        )

    def _get_api_key_from_settings(self, provider_name: str) -> str | None:
        """Get API key from settings for provider.

        Args:
            provider_name: Provider name

        Returns:
            Decrypted API key or None
        """
        key: SecretStr | None = self.settings.get_provider_api_key(provider_name)
        return key.get_secret_value() if key else None


async def encrypt_api_key(api_key: str) -> str:
    """Encrypt API key for storage.

    Args:
        api_key: Plain text API key

    Returns:
        Encrypted API key string
    """
    key = _get_ai_encryption_key()
    if not key:
        raise ValueError("AI_ENCRYPTION_KEY environment variable not set")
    return encrypt_value(api_key, key)


async def create_tenant_ai_config(
    session: AsyncSession,
    tenant_id: str,
    provider_type: AIProviderType,
    provider_name: str,
    api_key: str,
    model_name: str | None = None,
    config_json: dict[str, Any] | None = None,
    created_by_id: Any = None,
) -> TenantAIConfig:
    """Create tenant AI configuration with encrypted API key.

    Args:
        session: Database session
        tenant_id: Tenant identifier
        provider_type: Type of provider
        provider_name: Provider name
        api_key: Plain text API key to encrypt
        model_name: Optional model override
        config_json: Additional configuration
        created_by_id: User who created config

    Returns:
        Created TenantAIConfig
    """
    key = _get_ai_encryption_key()
    if not key:
        raise ValueError("AI_ENCRYPTION_KEY environment variable not set")
    encrypted_key = encrypt_value(api_key, key)

    config = TenantAIConfig(
        tenant_id=tenant_id,
        provider_type=provider_type,
        provider_name=provider_name,
        encrypted_api_key=encrypted_key,
        model_name=model_name,
        config_json=config_json,
        is_active=True,
        created_by_id=created_by_id,
    )

    session.add(config)
    await session.flush()

    logger.info(
        "Created tenant AI config",
        extra={
            "tenant_id": tenant_id,
            "provider_type": provider_type.value,
            "provider_name": provider_name,
        },
    )

    return config
