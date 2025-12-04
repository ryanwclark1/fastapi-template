"""OpenAI provider implementations for transcription and LLM.

Provides:
- OpenAITranscriptionProvider: Whisper API for speech-to-text
- OpenAILLMProvider: GPT models for text generation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.providers.base import (
    BaseProvider,
    LLMMessage,
    LLMResponse,
    ProviderAuthenticationError,
    ProviderError,
    TranscriptionResult,
    TranscriptionSegment,
)

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletionAssistantMessageParam,
        ChatCompletionSystemMessageParam,
        ChatCompletionUserMessageParam,
    )
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class OpenAITranscriptionProvider(BaseProvider):
    """OpenAI Whisper API transcription provider.

    Supports:
    - Audio transcription via Whisper API
    - Multiple audio formats
    - Automatic language detection
    - Timestamps and word-level timing (when available)

    Note: OpenAI Whisper API does not support speaker diarization.
    Use Deepgram or AssemblyAI for speaker identification.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "whisper-1",
        timeout: int = 120,
        max_retries: int = 3,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize OpenAI transcription provider.

        Args:
            api_key: OpenAI API key
            model_name: Whisper model (whisper-1)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            **kwargs: Additional arguments
        """
        super().__init__(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model_name = model_name
        self._validate_api_key()

        # Lazy import to avoid dependency if not used
        try:
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        except ImportError as e:
            raise ImportError(
                "openai package is required for OpenAI provider. Install with: pip install openai"
            ) from e

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai"

    async def transcribe(
        self,
        audio: bytes | str,
        language: str | None = None,
        speaker_diarization: bool = False,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe audio using OpenAI Whisper API.

        Args:
            audio: Audio data (bytes) or file path/URL
            language: Optional ISO 639-1 language code
            speaker_diarization: Not supported by OpenAI (ignored)
            **kwargs: Additional Whisper API parameters

        Returns:
            TranscriptionResult with transcribed text

        Raises:
            ProviderError: If transcription fails
        """
        if speaker_diarization:
            logger.warning(
                "OpenAI Whisper does not support speaker diarization. "
                "Consider using Deepgram or AssemblyAI."
            )

        try:
            # Prepare audio data
            if isinstance(audio, str):
                # If it's a file path, open it
                with open(audio, "rb") as f:
                    audio_data = f.read()
            else:
                audio_data = audio

            # Transcribe with detailed response format
            response = await self.client.audio.transcriptions.create(  # type: ignore[call-overload]
                model=self.model_name,
                file=(None, audio_data, "audio/wav"),
                response_format="verbose_json",  # Get segments with timestamps
                language=language,
                **kwargs,
            )

            # Parse response
            segments = []
            if hasattr(response, "segments") and response.segments:
                for seg in response.segments:
                    segments.append(
                        TranscriptionSegment(
                            text=seg.text.strip(),
                            start=seg.start,
                            end=seg.end,
                            confidence=None,  # OpenAI doesn't provide confidence
                            speaker=None,  # No speaker diarization
                        )
                    )
            else:
                # Fallback if no segments
                segments.append(
                    TranscriptionSegment(
                        text=response.text,
                        start=0.0,
                        end=0.0,
                    )
                )

            return TranscriptionResult(
                text=response.text,
                segments=segments,
                language=response.language if hasattr(response, "language") else language,
                duration_seconds=response.duration if hasattr(response, "duration") else None,
                provider_metadata={"model": self.model_name},
            )

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "authentication" in error_msg.lower():
                raise ProviderAuthenticationError(
                    "Invalid OpenAI API key",
                    provider="openai",
                    operation="transcription",
                    original_error=e,
                ) from e

            raise ProviderError(
                f"OpenAI transcription failed: {error_msg}",
                provider="openai",
                operation="transcription",
                original_error=e,
            ) from e

    async def transcribe_dual_channel(
        self,
        channel1: bytes | str,
        channel2: bytes | str,
        language: str | None = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe dual-channel audio by processing separately then merging.

        Args:
            channel1: First audio channel
            channel2: Second audio channel
            language: Optional language code
            **kwargs: Additional parameters

        Returns:
            Merged TranscriptionResult with speaker attribution
        """
        # Transcribe both channels
        result1 = await self.transcribe(channel1, language=language, **kwargs)
        result2 = await self.transcribe(channel2, language=language, **kwargs)

        # Merge segments with speaker attribution
        all_segments = []

        for seg in result1.segments:
            all_segments.append(
                TranscriptionSegment(
                    text=seg.text,
                    start=seg.start,
                    end=seg.end,
                    speaker="Channel 1",
                    confidence=seg.confidence,
                )
            )

        for seg in result2.segments:
            all_segments.append(
                TranscriptionSegment(
                    text=seg.text,
                    start=seg.start,
                    end=seg.end,
                    speaker="Channel 2",
                    confidence=seg.confidence,
                )
            )

        # Sort by start time
        all_segments.sort(key=lambda s: s.start)

        # Combine text
        combined_text = " ".join(seg.text for seg in all_segments)

        return TranscriptionResult(
            text=combined_text,
            segments=all_segments,
            language=result1.language or result2.language,
            duration_seconds=max(
                result1.duration_seconds or 0,
                result2.duration_seconds or 0,
            ),
            speakers={"channel_1": "Channel 1", "channel_2": "Channel 2"},
            provider_metadata={"model": self.model_name, "dual_channel": True},
        )

    def supports_speaker_diarization(self) -> bool:
        """Check if provider supports speaker diarization."""
        return False

    def get_supported_languages(self) -> list[str]:
        """Get list of supported languages.

        OpenAI Whisper supports 97+ languages.
        """
        return [
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
            # ... Whisper supports 97+ languages
            # Full list: https://github.com/openai/whisper#available-models-and-languages
        ]


class OpenAILLMProvider(BaseProvider):
    """OpenAI GPT LLM provider.

    Supports:
    - GPT-4, GPT-4 Turbo, GPT-3.5 Turbo models
    - Structured output via function calling
    - Streaming (future)
    - JSON mode
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gpt-4o-mini",
        timeout: int = 120,
        max_retries: int = 3,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize OpenAI LLM provider.

        Args:
            api_key: OpenAI API key
            model_name: Model to use (gpt-4, gpt-4o-mini, etc.)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            **kwargs: Additional arguments
        """
        super().__init__(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model_name = model_name
        self._validate_api_key()

        try:
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        except ImportError as e:
            raise ImportError(
                "openai package is required for OpenAI provider. Install with: pip install openai"
            ) from e

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai"

    async def generate(
        self,
        messages: list[LLMMessage] | list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate text completion using OpenAI API.

        Args:
            messages: Conversation history
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional OpenAI parameters

        Returns:
            LLMResponse with generated text

        Raises:
            ProviderError: If generation fails
        """
        try:
            # Convert LLMMessage to dict if needed

            messages_list: list[
                ChatCompletionUserMessageParam
                | ChatCompletionSystemMessageParam
                | ChatCompletionAssistantMessageParam
            ] = []
            for msg in messages:
                if isinstance(msg, LLMMessage):
                    if msg.role == "system":
                        messages_list.append({"role": "system", "content": msg.content})
                    elif msg.role == "assistant":
                        messages_list.append({"role": "assistant", "content": msg.content})
                    else:
                        messages_list.append({"role": "user", "content": msg.content})
                elif isinstance(msg, dict):
                    messages_list.append(msg)  # type: ignore[arg-type]
                else:
                    # Fallback: convert to dict
                    messages_list.append(
                        {
                            "role": getattr(msg, "role", "user"),
                            "content": getattr(msg, "content", str(msg)),
                        }
                    )

            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages_list,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            # Extract response
            choice = response.choices[0]
            content = choice.message.content or ""

            usage = None
            if response.usage:
                usage = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            return LLMResponse(
                content=content,
                model=response.model,
                usage=usage,
                finish_reason=choice.finish_reason,
                provider_metadata={"id": response.id},
            )

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "authentication" in error_msg.lower():
                raise ProviderAuthenticationError(
                    "Invalid OpenAI API key",
                    provider="openai",
                    operation="llm_generation",
                    original_error=e,
                ) from e

            raise ProviderError(
                f"OpenAI generation failed: {error_msg}",
                provider="openai",
                operation="llm_generation",
                original_error=e,
            ) from e

    async def generate_structured(
        self,
        messages: list[LLMMessage] | list[dict[str, str]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate structured output using function calling.

        Args:
            messages: Conversation history
            response_model: Pydantic model for structured output
            **kwargs: Additional parameters

        Returns:
            Instance of response_model with parsed data

        Raises:
            ProviderError: If generation or parsing fails
        """
        try:
            # Use instructor library for structured output
            # This requires: pip install instructor
            import instructor

            # Patch client with instructor
            client = instructor.from_openai(self.client)

            # Convert messages
            from typing import cast

            messages_list: list[
                ChatCompletionUserMessageParam
                | ChatCompletionSystemMessageParam
                | ChatCompletionAssistantMessageParam
            ] = []
            for msg in messages:
                if isinstance(msg, LLMMessage):
                    # Convert LLMMessage to OpenAI message format
                    msg_dict = cast(
                        "ChatCompletionUserMessageParam | ChatCompletionSystemMessageParam | ChatCompletionAssistantMessageParam",
                        {"role": msg.role, "content": msg.content},
                    )
                    messages_list.append(msg_dict)
                else:
                    messages_list.append(msg)  # type: ignore[arg-type]

            # Generate with structured output
            result = await client.chat.completions.create(
                model=self.model_name,
                messages=messages_list,  # type: ignore[arg-type]
                response_model=response_model,
                **kwargs,
            )

            return result

        except ImportError as e:
            raise ImportError(
                "instructor package is required for structured output. "
                "Install with: pip install instructor"
            ) from e
        except Exception as e:
            raise ProviderError(
                f"Structured generation failed: {e}",
                provider="openai",
                operation="structured_generation",
                original_error=e,
            ) from e

    def supports_streaming(self) -> bool:
        """Check if provider supports streaming."""
        return True

    def get_model_name(self) -> str:
        """Get the model name being used."""
        return self.model_name
