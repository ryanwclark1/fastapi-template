"""Deepgram provider for advanced speech-to-text transcription.

Provides high-accuracy transcription with:
- Speaker diarization
- Word-level timestamps
- Punctuation and formatting
- Multiple language support
- Real-time streaming (future)
"""

from __future__ import annotations

import logging
from typing import Any

from example_service.infra.ai.providers.base import (
    BaseProvider,
    ProviderAuthenticationError,
    ProviderError,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)


class DeepgramProvider(BaseProvider):
    """Deepgram speech-to-text provider.

    Features:
    - Nova-2 model (high accuracy)
    - Speaker diarization
    - Word-level timestamps
    - Punctuation and capitalization
    - Multiple languages
    - Custom vocabulary (future)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "nova-2",
        timeout: int = 120,
        max_retries: int = 3,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize Deepgram provider.

        Args:
            api_key: Deepgram API key
            model_name: Model to use (nova-2, enhanced, base)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            **kwargs: Additional arguments
        """
        super().__init__(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model_name = model_name
        self._validate_api_key()

        try:
            from deepgram import (
                DeepgramClient,
                PrerecordedOptions,
            )

            self.client = DeepgramClient(api_key=self.api_key)
            self.options_class = PrerecordedOptions
        except ImportError as e:
            raise ImportError(
                "deepgram-sdk package is required for Deepgram provider. "
                "Install with: pip install deepgram-sdk"
            ) from e

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "deepgram"

    async def transcribe(
        self,
        audio: bytes | str,
        language: str | None = None,
        speaker_diarization: bool = True,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe audio using Deepgram API.

        Args:
            audio: Audio data (bytes) or URL
            language: Optional language code (en, es, fr, etc.)
            speaker_diarization: Enable speaker identification
            **kwargs: Additional Deepgram parameters

        Returns:
            TranscriptionResult with text, segments, and speakers

        Raises:
            ProviderError: If transcription fails
        """
        try:
            # Prepare options
            options = self.options_class(
                model=self.model_name,
                language=language or "en",
                punctuate=True,
                diarize=speaker_diarization,
                utterances=True,  # Get speaker-attributed segments
                smart_format=True,
                paragraphs=False,
                **kwargs,
            )

            # Transcribe
            if isinstance(audio, str):
                # URL source
                response = await self.client.listen.asyncrest.v("1").transcribe_url(
                    {"url": audio}, options
                )
            else:
                # Bytes source
                response = await self.client.listen.asyncrest.v("1").transcribe_file(
                    {"buffer": audio}, options
                )

            # Parse response
            results = response["results"]
            channels = results["channels"][0]
            alternatives = channels["alternatives"][0]

            # Get full transcript
            transcript = alternatives["transcript"]

            # Parse segments/utterances
            segments = []
            speakers_info = {}

            if speaker_diarization and "utterances" in results:
                for utt in results["utterances"]:
                    speaker_id = f"Speaker {utt['speaker']}"
                    speakers_info[speaker_id] = speaker_id

                    segments.append(
                        TranscriptionSegment(
                            text=utt["transcript"],
                            start=utt["start"],
                            end=utt["end"],
                            speaker=speaker_id,
                            confidence=utt.get("confidence"),
                        )
                    )
            else:
                # Fallback to words if no utterances
                if "words" in alternatives:
                    # Group words into segments
                    current_segment = []
                    current_start = None

                    for word in alternatives["words"]:
                        if current_start is None:
                            current_start = word["start"]
                        current_segment.append(word["word"])

                        # Create segment every ~10 words or at punctuation
                        if len(current_segment) >= 10 or word["word"].endswith((".", "!", "?")):
                            segments.append(
                                TranscriptionSegment(
                                    text=" ".join(current_segment),
                                    start=current_start,
                                    end=word["end"],
                                    confidence=alternatives.get("confidence"),
                                )
                            )
                            current_segment = []
                            current_start = None

                    # Add remaining words
                    if current_segment:
                        last_word = alternatives["words"][-1]
                        segments.append(
                            TranscriptionSegment(
                                text=" ".join(current_segment),
                                start=current_start or 0.0,
                                end=last_word["end"],
                                confidence=alternatives.get("confidence"),
                            )
                        )
                else:
                    # No words available, create single segment
                    segments.append(
                        TranscriptionSegment(
                            text=transcript,
                            start=0.0,
                            end=results.get("duration", 0.0),
                            confidence=alternatives.get("confidence"),
                        )
                    )

            # Get duration
            duration = results.get("duration")

            return TranscriptionResult(
                text=transcript,
                segments=segments,
                language=language or "en",
                duration_seconds=duration,
                speakers=speakers_info if speakers_info else None,
                provider_metadata={
                    "model": self.model_name,
                    "confidence": alternatives.get("confidence"),
                    "request_id": response.get("metadata", {}).get("request_id"),
                },
            )

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                raise ProviderAuthenticationError(
                    "Invalid Deepgram API key",
                    provider="deepgram",
                    operation="transcription",
                    original_error=e,
                ) from e

            raise ProviderError(
                f"Deepgram transcription failed: {error_msg}",
                provider="deepgram",
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
        """Transcribe dual-channel audio.

        For Deepgram, we can either:
        1. Use multichannel support (if audio is already interleaved)
        2. Transcribe separately and merge

        This implementation uses separate transcription for flexibility.

        Args:
            channel1: First audio channel
            channel2: Second audio channel
            language: Optional language code
            **kwargs: Additional parameters

        Returns:
            Merged TranscriptionResult with speaker attribution
        """
        # Transcribe both channels with speaker diarization disabled
        # (we'll use channel as speaker)
        result1 = await self.transcribe(
            channel1, language=language, speaker_diarization=False, **kwargs
        )
        result2 = await self.transcribe(
            channel2, language=language, speaker_diarization=False, **kwargs
        )

        # Merge segments with channel attribution
        all_segments = []

        for seg in result1.segments:
            all_segments.append(
                TranscriptionSegment(
                    text=seg.text,
                    start=seg.start,
                    end=seg.end,
                    speaker="Agent",  # Channel 1 is typically agent
                    confidence=seg.confidence,
                )
            )

        for seg in result2.segments:
            all_segments.append(
                TranscriptionSegment(
                    text=seg.text,
                    start=seg.start,
                    end=seg.end,
                    speaker="Customer",  # Channel 2 is typically customer
                    confidence=seg.confidence,
                )
            )

        # Sort by start time
        all_segments.sort(key=lambda s: s.start)

        # Combine text in chronological order
        combined_text = " ".join(seg.text for seg in all_segments)

        return TranscriptionResult(
            text=combined_text,
            segments=all_segments,
            language=result1.language or result2.language,
            duration_seconds=max(
                result1.duration_seconds or 0,
                result2.duration_seconds or 0,
            ),
            speakers={"agent": "Agent", "customer": "Customer"},
            provider_metadata={
                "model": self.model_name,
                "dual_channel": True,
            },
        )

    def supports_speaker_diarization(self) -> bool:
        """Check if provider supports speaker diarization."""
        return True

    def get_supported_languages(self) -> list[str]:
        """Get list of supported languages.

        Deepgram Nova-2 supports 100+ languages.
        """
        return [
            "en",  # English
            "es",  # Spanish
            "fr",  # French
            "de",  # German
            "it",  # Italian
            "pt",  # Portuguese
            "nl",  # Dutch
            "ru",  # Russian
            "zh",  # Chinese
            "ja",  # Japanese
            "ko",  # Korean
            "ar",  # Arabic
            "hi",  # Hindi
            "tr",  # Turkish
            # ... Deepgram supports 100+ languages
            # Full list: https://developers.deepgram.com/docs/models-languages-overview
        ]
