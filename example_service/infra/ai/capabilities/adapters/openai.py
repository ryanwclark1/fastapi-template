"""OpenAI provider adapter.

Wraps OpenAITranscriptionProvider and OpenAILLMProvider with:
- Capability declarations
- Standardized OperationResult output
- Cost tracking from actual usage
"""

from __future__ import annotations

import logging
from decimal import Decimal
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


class OpenAIAdapter(ProviderAdapter):
    """OpenAI adapter supporting both LLM and transcription capabilities.

    Capabilities:
        - LLM_GENERATION: GPT models for text generation
        - LLM_STRUCTURED: Structured output via instructor
        - LLM_STREAMING: Streaming responses (future)
        - TRANSCRIPTION: Whisper API for speech-to-text
        - TRANSCRIPTION_DUAL_CHANNEL: Dual-channel transcription

    Pricing (as of 2025-01):
        - GPT-4o: $2.50/1M input, $10.00/1M output
        - GPT-4o-mini: $0.15/1M input, $0.60/1M output
        - Whisper: $0.006/minute

    Usage:
        adapter = OpenAIAdapter(api_key="sk-...", model_name="gpt-4o-mini")

        # LLM generation
        result = await adapter.execute(
            Capability.LLM_GENERATION,
            {"messages": [{"role": "user", "content": "Hello"}]},
            temperature=0.7,
        )

        # Transcription
        result = await adapter.execute(
            Capability.TRANSCRIPTION,
            {"audio": audio_bytes, "language": "en"},
        )
    """

    # Pricing per million tokens (2025-01)
    LLM_PRICING: ClassVar[dict[str, dict[str, Decimal]]] = {
        "gpt-4o": {"input": Decimal("2.50"), "output": Decimal("10.00")},
        "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
        "gpt-4-turbo": {"input": Decimal("10.00"), "output": Decimal("30.00")},
        "gpt-4": {"input": Decimal("30.00"), "output": Decimal("60.00")},
        "gpt-3.5-turbo": {"input": Decimal("0.50"), "output": Decimal("1.50")},
    }

    # Whisper pricing per minute
    WHISPER_PRICE_PER_MINUTE = Decimal("0.006")

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        transcription_model: str = "whisper-1",
        timeout: int = 120,
        max_retries: int = 3,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize OpenAI adapter.

        Args:
            api_key: OpenAI API key
            model_name: LLM model to use (gpt-4o, gpt-4o-mini, etc.)
            transcription_model: Transcription model (whisper-1)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.api_key = api_key
        self.model_name = model_name
        self.transcription_model = transcription_model
        self.timeout = timeout
        self.max_retries = max_retries

        # Lazy initialization of underlying providers
        self._llm_provider = None
        self._transcription_provider = None

    def _get_llm_provider(self) -> Any:
        """Lazy initialize LLM provider."""
        if self._llm_provider is None:
            from example_service.infra.ai.providers.openai_provider import (
                OpenAILLMProvider,
            )

            self._llm_provider = OpenAILLMProvider(  # type: ignore[assignment]
                api_key=self.api_key,
                model_name=self.model_name,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._llm_provider

    def _get_transcription_provider(self) -> Any:
        """Lazy initialize transcription provider."""
        if self._transcription_provider is None:
            from example_service.infra.ai.providers.openai_provider import (
                OpenAITranscriptionProvider,
            )

            self._transcription_provider = OpenAITranscriptionProvider(  # type: ignore[assignment]
                api_key=self.api_key,
                model_name=self.transcription_model,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._transcription_provider

    def get_registration(self) -> ProviderRegistration:
        """Get provider registration with all capabilities."""
        # Get pricing for current model
        llm_pricing = self.LLM_PRICING.get(
            self.model_name,
            {"input": Decimal("0.15"), "output": Decimal("0.60")},
        )

        return ProviderRegistration(
            provider_name="openai",
            provider_type=ProviderType.EXTERNAL,
            capabilities=[
                # LLM capabilities
                CapabilityMetadata(
                    capability=Capability.LLM_GENERATION,
                    provider_name="openai",
                    cost_per_unit=llm_pricing["input"],
                    output_cost_per_unit=llm_pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=QualityTier.STANDARD,
                    priority=50,
                    supports_streaming=True,
                    model_name=self.model_name,
                ),
                CapabilityMetadata(
                    capability=Capability.LLM_STRUCTURED,
                    provider_name="openai",
                    cost_per_unit=llm_pricing["input"],
                    output_cost_per_unit=llm_pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=QualityTier.STANDARD,
                    priority=50,
                    model_name=self.model_name,
                ),
                CapabilityMetadata(
                    capability=Capability.LLM_STREAMING,
                    provider_name="openai",
                    cost_per_unit=llm_pricing["input"],
                    output_cost_per_unit=llm_pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=QualityTier.STANDARD,
                    priority=50,
                    supports_streaming=True,
                    model_name=self.model_name,
                ),
                # Transcription capabilities
                CapabilityMetadata(
                    capability=Capability.TRANSCRIPTION,
                    provider_name="openai",
                    cost_per_unit=self.WHISPER_PRICE_PER_MINUTE,
                    cost_unit=CostUnit.PER_MINUTE,
                    quality_tier=QualityTier.STANDARD,
                    priority=50,
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
                    model_name=self.transcription_model,
                ),
                CapabilityMetadata(
                    capability=Capability.TRANSCRIPTION_DUAL_CHANNEL,
                    provider_name="openai",
                    cost_per_unit=self.WHISPER_PRICE_PER_MINUTE * 2,  # Two channels
                    cost_unit=CostUnit.PER_MINUTE,
                    quality_tier=QualityTier.STANDARD,
                    priority=60,  # Less preferred than Deepgram for dual-channel
                    model_name=self.transcription_model,
                ),
            ],
            requires_api_key=True,
            documentation_url="https://platform.openai.com/docs",
        )

    async def execute(
        self,
        capability: Capability,
        input_data: Any,
        **options: Any,
    ) -> OperationResult:
        """Execute an AI operation.

        Args:
            capability: The capability to execute
            input_data: Input data (dict with operation-specific fields)
            **options: Additional options

        Returns:
            OperationResult with success/failure, data, usage, and cost
        """
        # Route to appropriate handler
        if capability in (Capability.LLM_GENERATION, Capability.LLM_STREAMING):
            return await self._execute_llm_generation(input_data, **options)
        elif capability == Capability.LLM_STRUCTURED:
            return await self._execute_llm_structured(input_data, **options)
        elif capability == Capability.TRANSCRIPTION:
            return await self._execute_transcription(input_data, **options)
        elif capability == Capability.TRANSCRIPTION_DUAL_CHANNEL:
            return await self._execute_transcription_dual_channel(input_data, **options)
        else:
            return self._create_error_result(
                capability,
                f"Unsupported capability: {capability}",
                error_code="UNSUPPORTED_CAPABILITY",
                retryable=False,
            )

    async def _execute_llm_generation(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute LLM text generation.

        Expected input_data:
            messages: List of message dicts or LLMMessage objects

        Options:
            temperature: float (0.0-2.0)
            max_tokens: int
        """
        async with TimedExecution() as timer:
            try:
                messages = input_data.get("messages", [])
                if not messages:
                    return self._create_error_result(
                        Capability.LLM_GENERATION,
                        "No messages provided",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_llm_provider()
                response = await provider.generate(
                    messages=messages,
                    temperature=options.get("temperature", 0.7),
                    max_tokens=options.get("max_tokens", 4096),
                    **{k: v for k, v in options.items() if k not in ("temperature", "max_tokens")},
                )

                # Extract usage metrics
                usage = {
                    "input_tokens": response.usage.get("input_tokens", 0) if response.usage else 0,
                    "output_tokens": response.usage.get("output_tokens", 0)
                    if response.usage
                    else 0,
                }

                return self._create_success_result(
                    Capability.LLM_GENERATION,
                    data=response,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                    request_id=response.provider_metadata.get("id")
                    if response.provider_metadata
                    else None,
                )

            except Exception as e:
                logger.exception(f"OpenAI LLM generation failed: {e}")
                return self._create_error_result(
                    Capability.LLM_GENERATION,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def _execute_llm_structured(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute structured LLM generation.

        Expected input_data:
            messages: List of message dicts
            response_model: Pydantic model class for structured output
        """
        async with TimedExecution() as timer:
            try:
                messages = input_data.get("messages", [])
                response_model = input_data.get("response_model")

                if not messages or not response_model:
                    return self._create_error_result(
                        Capability.LLM_STRUCTURED,
                        "Both messages and response_model are required",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_llm_provider()
                result = await provider.generate_structured(
                    messages=messages,
                    response_model=response_model,
                    **options,
                )

                # Note: structured output doesn't return usage directly
                # Estimate based on typical usage
                usage = {
                    "input_tokens": options.get("estimated_input_tokens", 500),
                    "output_tokens": options.get("estimated_output_tokens", 500),
                }

                return self._create_success_result(
                    Capability.LLM_STRUCTURED,
                    data=result,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                )

            except Exception as e:
                logger.exception(f"OpenAI structured generation failed: {e}")
                return self._create_error_result(
                    Capability.LLM_STRUCTURED,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def _execute_transcription(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute audio transcription.

        Expected input_data:
            audio: bytes or file path
            language: Optional language code
        """
        async with TimedExecution() as timer:
            try:
                audio = input_data.get("audio")
                if not audio:
                    return self._create_error_result(
                        Capability.TRANSCRIPTION,
                        "No audio data provided",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                provider = self._get_transcription_provider()
                result = await provider.transcribe(
                    audio=audio,
                    language=input_data.get("language"),
                    **options,
                )

                # Calculate usage based on duration
                usage = {
                    "duration_seconds": result.duration_seconds or 0,
                }

                return self._create_success_result(
                    Capability.TRANSCRIPTION,
                    data=result,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                )

            except Exception as e:
                logger.exception(f"OpenAI transcription failed: {e}")
                return self._create_error_result(
                    Capability.TRANSCRIPTION,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def _execute_transcription_dual_channel(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute dual-channel transcription.

        Expected input_data:
            channel1: bytes or file path
            channel2: bytes or file path
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

                provider = self._get_transcription_provider()
                result = await provider.transcribe_dual_channel(
                    channel1=channel1,
                    channel2=channel2,
                    language=input_data.get("language"),
                    **options,
                )

                # Calculate usage (doubled for two channels)
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
                logger.exception(f"OpenAI dual-channel transcription failed: {e}")
                return self._create_error_result(
                    Capability.TRANSCRIPTION_DUAL_CHANNEL,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible.

        Makes a minimal API call to verify connectivity.
        """
        try:
            provider = self._get_llm_provider()
            # Make a minimal request
            await provider.generate(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            return True
        except Exception as e:
            logger.warning(f"OpenAI health check failed: {e}")
            return False
