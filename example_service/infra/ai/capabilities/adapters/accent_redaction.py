"""Accent Redaction provider adapter for PII detection and masking.

Wraps AccentRedactionProvider with capability declarations.

Features:
- Multiple entity types (EMAIL, PHONE, SSN, etc.)
- Configurable redaction methods
- Segment-level redaction for transcripts
- Zero cost (internal service)

This is an internal service, so:
- No API key required (or internal auth)
- Zero cost per request
- Highest priority for PII operations
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, ClassVar

from example_service.infra.ai.capabilities.adapters.base import ProviderAdapter, TimedExecution
from example_service.infra.ai.capabilities.types import (
    Capability,
    CapabilityMetadata,
    CostUnit,
    OperationResult,
    ProviderRegistration,
    ProviderType,
    QualityTier,
)

logger = logging.getLogger(__name__)


class AccentRedactionAdapter(ProviderAdapter):
    """Accent Redaction adapter for PII capabilities.

    Capabilities:
        - PII_DETECTION: Detect PII entities in text
        - PII_REDACTION: Detect and mask PII in text

    This is an internal service, so it has:
        - Zero cost
        - Highest priority (priority=1)
        - Health check via service URL

    Usage:
        adapter = AccentRedactionAdapter(
            service_url="http://accent-redaction:8502",
        )

        # Redact PII
        result = await adapter.execute(
            Capability.PII_REDACTION,
            {"text": "My SSN is 123-45-6789"},
        )
    """

    # Default entity types
    DEFAULT_ENTITY_TYPES: ClassVar[list[str]] = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
    ]

    def __init__(
        self,
        service_url: str = "http://accent-redaction:8502",
        api_key: str | None = None,
        entity_types: list[str] | None = None,
        confidence_threshold: float = 0.7,
        redaction_method: str = "mask",
        timeout: int = 60,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize Accent Redaction adapter.

        Args:
            service_url: URL of accent-redaction service
            api_key: Optional API key (for external deployments)
            entity_types: Default entity types to detect
            confidence_threshold: Minimum confidence (0.0-1.0)
            redaction_method: How to redact (mask|replace|hash|remove)
            timeout: Request timeout in seconds
        """
        self.service_url = service_url
        self.api_key = api_key
        self.entity_types = entity_types or self.DEFAULT_ENTITY_TYPES
        self.confidence_threshold = confidence_threshold
        self.redaction_method = redaction_method
        self.timeout = timeout

        # Lazy initialization
        self._provider = None

    def _get_provider(self) -> Any:
        """Lazy initialize provider."""
        if self._provider is None:
            from example_service.infra.ai.providers.accent_redaction_client import (
                AccentRedactionProvider,
            )

            self._provider = AccentRedactionProvider(  # type: ignore[assignment]
                service_url=self.service_url,
                api_key=self.api_key,
                entity_types=self.entity_types,
                confidence_threshold=self.confidence_threshold,
                redaction_method=self.redaction_method,
                timeout=self.timeout,
            )
        return self._provider

    def get_registration(self) -> ProviderRegistration:
        """Get provider registration with all capabilities."""
        return ProviderRegistration(
            provider_name="accent_redaction",
            provider_type=ProviderType.INTERNAL,
            capabilities=[
                # PII Detection
                CapabilityMetadata(
                    capability=Capability.PII_DETECTION,
                    provider_name="accent_redaction",
                    cost_per_unit=Decimal("0"),  # Internal service - free
                    cost_unit=CostUnit.FREE,
                    quality_tier=QualityTier.PREMIUM,
                    priority=1,  # Highest priority for PII
                ),
                # PII Redaction
                CapabilityMetadata(
                    capability=Capability.PII_REDACTION,
                    provider_name="accent_redaction",
                    cost_per_unit=Decimal("0"),
                    cost_unit=CostUnit.FREE,
                    quality_tier=QualityTier.PREMIUM,
                    priority=1,
                ),
            ],
            requires_api_key=False,
            health_check_url=f"{self.service_url}/health",
        )

    async def execute(
        self,
        capability: Capability,
        input_data: Any,
        **options: Any,
    ) -> OperationResult:
        """Execute a PII operation.

        Args:
            capability: The capability to execute
            input_data: Input data with text or segments
            **options: Additional options

        Returns:
            OperationResult with PII detection/redaction data
        """
        if capability == Capability.PII_DETECTION:
            return await self._execute_detection(input_data, **options)
        elif capability == Capability.PII_REDACTION:
            return await self._execute_redaction(input_data, **options)
        else:
            return self._create_error_result(
                capability,
                f"Unsupported capability: {capability}",
                error_code="UNSUPPORTED_CAPABILITY",
                retryable=False,
            )

    async def _execute_detection(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute PII detection.

        Expected input_data:
            text: Text to analyze
            entity_types: Optional list of entity types
            confidence_threshold: Optional confidence threshold
        """
        async with TimedExecution() as timer:
            try:
                text = input_data.get("text")
                if not text:
                    return self._create_error_result(
                        Capability.PII_DETECTION,
                        "No text provided",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_provider()
                entities = await provider.detect_pii(
                    text=text,
                    entity_types=input_data.get("entity_types"),
                    confidence_threshold=input_data.get("confidence_threshold"),
                    **options,
                )

                # Build usage metrics (character count for tracking)
                usage = {
                    "character_count": len(text),
                    "entity_count": len(entities),
                    "request_count": 1,
                }

                return self._create_success_result(
                    Capability.PII_DETECTION,
                    data=entities,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                )

            except Exception as e:
                logger.exception(f"Accent Redaction PII detection failed: {e}")
                return self._create_error_result(
                    Capability.PII_DETECTION,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def _execute_redaction(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute PII redaction.

        Expected input_data:
            text: Text to redact
            OR
            segments: List of transcript segments
            entity_types: Optional list of entity types
            redaction_method: Optional redaction method
        """
        async with TimedExecution() as timer:
            try:
                text = input_data.get("text")
                segments = input_data.get("segments")

                if not text and not segments:
                    return self._create_error_result(
                        Capability.PII_REDACTION,
                        "Either text or segments must be provided",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_provider()

                if segments:
                    # Segment-level redaction for transcripts
                    result = await provider.redact_transcript_segments(
                        segments=segments,
                        entity_types=input_data.get("entity_types"),
                        **options,
                    )
                else:
                    # Text-level redaction
                    result = await provider.redact_pii(
                        text=text,
                        entity_types=input_data.get("entity_types"),
                        redaction_method=input_data.get("redaction_method"),
                        **options,
                    )

                # Build usage metrics
                usage = {
                    "character_count": len(text)
                    if text
                    else sum(len(s.get("text", "")) for s in segments) if segments else 0,
                    "entity_count": len(result.entities),
                    "request_count": 1,
                }

                return self._create_success_result(
                    Capability.PII_REDACTION,
                    data=result,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                )

            except Exception as e:
                logger.exception(f"Accent Redaction PII redaction failed: {e}")
                return self._create_error_result(
                    Capability.PII_REDACTION,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def health_check(self) -> bool:
        """Check if accent-redaction service is accessible."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.service_url}/health")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Accent Redaction health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close provider resources."""
        if self._provider:
            await self._provider.close()
            self._provider = None
