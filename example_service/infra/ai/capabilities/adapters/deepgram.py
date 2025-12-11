"""Deepgram provider adapter for speech-to-text transcription.

Wraps DeepgramProvider with capability declarations and cost tracking.

Features:
- Nova-2 model for high accuracy
- Speaker diarization (highest priority for this capability)
- Word-level timestamps
- Multiple language support
- Dual-channel support

Pricing (as of 2025-01):
- Nova-2: $0.0043/minute
- Enhanced: $0.0055/minute
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import Any, ClassVar

from example_service.infra.ai.capabilities.adapters.base import (
    ProviderAdapter,
    TimedExecution,
)
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


class DeepgramAdapter(ProviderAdapter):
    """Deepgram adapter for transcription capabilities.

    Capabilities:
        - TRANSCRIPTION: Basic transcription with timestamps
        - TRANSCRIPTION_DIARIZATION: Speaker identification (priority 5)
        - TRANSCRIPTION_DUAL_CHANNEL: Dual-channel processing

    Deepgram is the preferred provider for:
        - Speaker diarization (best in class)
        - Real-time transcription
        - Multiple languages

    Usage:
        adapter = DeepgramAdapter(api_key="...", model_name="nova-2")

        # Transcription with speaker diarization
        result = await adapter.execute(
            Capability.TRANSCRIPTION_DIARIZATION,
            {"audio": audio_bytes, "language": "en"},
        )
    """

    # Pricing per minute (2025-01)
    MODEL_PRICING: ClassVar[dict[str, Decimal]] = {
        "nova-2": Decimal("0.0043"),
        "nova": Decimal("0.0041"),
        "enhanced": Decimal("0.0055"),
        "base": Decimal("0.0025"),
    }

    def __init__(
        self,
        api_key: str,
        model_name: str = "nova-2",
        timeout: int = 120,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        """Initialize Deepgram adapter.

        Args:
            api_key: Deepgram API key
            model_name: Model to use (nova-2, enhanced, base)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            **kwargs: Additional adapter-specific options.
        """
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries

        # Lazy initialization
        self._provider = None

    def _get_provider(self) -> Any:
        """Lazy initialize Deepgram provider."""
        if self._provider is None:
            from example_service.infra.ai.providers.deepgram_provider import (
                DeepgramProvider,
            )

            self._provider = DeepgramProvider(  # type: ignore[assignment]
                api_key=self.api_key,
                model_name=self.model_name,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._provider

    def get_registration(self) -> ProviderRegistration:
        """Get provider registration with all capabilities."""
        price_per_minute = self.MODEL_PRICING.get(
            self.model_name,
            Decimal("0.0043"),
        )

        return ProviderRegistration(
            provider_name="deepgram",
            provider_type=ProviderType.EXTERNAL,
            capabilities=[
                # Basic transcription
                CapabilityMetadata(
                    capability=Capability.TRANSCRIPTION,
                    provider_name="deepgram",
                    cost_per_unit=price_per_minute,
                    cost_unit=CostUnit.PER_MINUTE,
                    quality_tier=QualityTier.PREMIUM,
                    priority=10,
                    supported_languages=[
                        "en",
                        "es",
                        "fr",
                        "de",
                        "it",
                        "pt",
                        "nl",
                        "ru",
                        "zh",
                        "ja",
                        "ko",
                        "ar",
                        "hi",
                        "tr",
                        "pl",
                        "vi",
                    ],
                    model_name=self.model_name,
                ),
                # Speaker diarization - Deepgram's strength
                CapabilityMetadata(
                    capability=Capability.TRANSCRIPTION_DIARIZATION,
                    provider_name="deepgram",
                    cost_per_unit=price_per_minute,
                    cost_unit=CostUnit.PER_MINUTE,
                    quality_tier=QualityTier.PREMIUM,
                    priority=5,  # Highest priority for diarization
                    supported_languages=[
                        "en",
                        "es",
                        "fr",
                        "de",
                        "it",
                        "pt",
                        "nl",
                        "ru",
                        "zh",
                        "ja",
                        "ko",
                        "ar",
                        "hi",
                        "tr",
                        "pl",
                        "vi",
                    ],
                    model_name=self.model_name,
                ),
                # Dual-channel transcription
                CapabilityMetadata(
                    capability=Capability.TRANSCRIPTION_DUAL_CHANNEL,
                    provider_name="deepgram",
                    cost_per_unit=price_per_minute * 2,  # Two channels
                    cost_unit=CostUnit.PER_MINUTE,
                    quality_tier=QualityTier.PREMIUM,
                    priority=5,
                    model_name=self.model_name,
                ),
            ],
            requires_api_key=True,
            documentation_url="https://developers.deepgram.com/docs",
        )

    async def execute(
        self,
        capability: Capability,
        input_data: Any,
        **options: Any,
    ) -> OperationResult:
        """Execute a transcription operation.

        Args:
            capability: The capability to execute
            input_data: Input data with audio field
            **options: Additional options

        Returns:
            OperationResult with transcription data
        """
        if capability == Capability.TRANSCRIPTION:
            return await self._execute_transcription(
                input_data, speaker_diarization=False, **options,
            )
        if capability == Capability.TRANSCRIPTION_DIARIZATION:
            return await self._execute_transcription(
                input_data, speaker_diarization=True, **options,
            )
        if capability == Capability.TRANSCRIPTION_DUAL_CHANNEL:
            return await self._execute_dual_channel(input_data, **options)
        return self._create_error_result(
            capability,
            f"Unsupported capability: {capability}",
            error_code="UNSUPPORTED_CAPABILITY",
            retryable=False,
        )

    async def _execute_transcription(
        self,
        input_data: dict[str, Any],
        speaker_diarization: bool = True,
        **options: Any,
    ) -> OperationResult:
        """Execute audio transcription.

        Expected input_data:
            audio: bytes or URL string
            language: Optional language code
        """
        async with TimedExecution() as timer:
            try:
                audio = input_data.get("audio")
                if not audio:
                    return self._create_error_result(
                        Capability.TRANSCRIPTION_DIARIZATION
                        if speaker_diarization
                        else Capability.TRANSCRIPTION,
                        "No audio data provided",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_provider()
                result = await provider.transcribe(
                    audio=audio,
                    language=input_data.get("language"),
                    speaker_diarization=speaker_diarization,
                    **options,
                )

                # Build usage metrics
                usage = {
                    "duration_seconds": result.duration_seconds or 0,
                }

                capability = (
                    Capability.TRANSCRIPTION_DIARIZATION
                    if speaker_diarization
                    else Capability.TRANSCRIPTION
                )

                return self._create_success_result(
                    capability,
                    data=result,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                    request_id=result.provider_metadata.get("request_id")
                    if result.provider_metadata
                    else None,
                )

            except Exception as e:
                logger.exception(f"Deepgram transcription failed: {e}")
                capability = (
                    Capability.TRANSCRIPTION_DIARIZATION
                    if speaker_diarization
                    else Capability.TRANSCRIPTION
                )
                return self._create_error_result(
                    capability,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def _execute_dual_channel(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute dual-channel transcription.

        Expected input_data:
            channel1: bytes or URL (agent channel)
            channel2: bytes or URL (customer channel)
            language: Optional language code
        """
        async with TimedExecution() as timer:
            try:
                channel1 = input_data.get("channel1")
                channel2 = input_data.get("channel2")

                if not channel1 or not channel2:
                    return self._create_error_result(
                        Capability.TRANSCRIPTION_DUAL_CHANNEL,
                        "Both channel1 and channel2 are required",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_provider()
                result = await provider.transcribe_dual_channel(
                    channel1=channel1,
                    channel2=channel2,
                    language=input_data.get("language"),
                    **options,
                )

                # Usage is doubled for two channels
                usage = {
                    "duration_seconds": (result.duration_seconds or 0) * 2,
                }

                return self._create_success_result(
                    Capability.TRANSCRIPTION_DUAL_CHANNEL,
                    data=result,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                )

            except Exception as e:
                logger.exception(f"Deepgram dual-channel transcription failed: {e}")
                return self._create_error_result(
                    Capability.TRANSCRIPTION_DUAL_CHANNEL,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def health_check(self) -> bool:
        """Check if Deepgram API is accessible.

        Note: Deepgram doesn't have a dedicated health endpoint,
        so we just verify the client can be created.
        """
        try:
            _ = self._get_provider()
            return True
        except Exception as e:
            logger.warning(f"Deepgram health check failed: {e}")
            return False
