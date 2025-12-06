"""AssemblyAI provider for high-quality speech-to-text transcription.

Provides advanced transcription with:
- Speaker diarization
- Auto-highlighting
- Entity detection
- High-accuracy word-level timestamps
- Polling-based async transcription
- File upload to AssemblyAI storage
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from example_service.infra.ai.providers.base import (
    BaseProvider,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)


class AssemblyAIProvider(BaseProvider):
    """AssemblyAI speech-to-text provider.

    Features:
    - High-quality transcription with speaker diarization
    - Auto-highlighting of key phrases
    - Entity detection (PII, dates, numbers)
    - Word-level timestamps
    - Support for multiple languages
    - Async processing with polling

    Unlike real-time services, AssemblyAI requires:
    1. Upload audio file to their storage
    2. Create transcription job
    3. Poll for completion
    """

    BASE_URL = "https://api.assemblyai.com/v2"

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "best",
        timeout: int = 600,  # Longer timeout for polling
        max_retries: int = 3,
        poll_interval: float = 3.0,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize AssemblyAI provider.

        Args:
            api_key: AssemblyAI API key
            model_name: Model to use (best, nano)
            timeout: Request timeout in seconds (for polling)
            max_retries: Maximum retry attempts
            poll_interval: Seconds between status polls
            **kwargs: Additional arguments
        """
        super().__init__(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model_name = model_name
        self.poll_interval = poll_interval
        self._validate_api_key()

        # HTTP client for API requests
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "authorization": self.api_key,
                "content-type": "application/json",
            },
            timeout=timeout,
        )

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "assemblyai"

    async def _upload_file(self, audio: bytes) -> str:
        """Upload audio file to AssemblyAI storage.

        Args:
            audio: Audio data as bytes

        Returns:
            URL of uploaded file

        Raises:
            ProviderError: If upload fails
        """
        try:
            response = await self.client.post(
                "/upload",
                content=audio,
                headers={"content-type": "application/octet-stream"},
            )
            response.raise_for_status()
            data = response.json()
            upload_url = data.get("upload_url")

            if not upload_url:
                raise ProviderError(
                    "No upload URL returned from AssemblyAI",
                    provider="assemblyai",
                    operation="file_upload",
                )

            logger.debug(f"Uploaded file to AssemblyAI: {upload_url}")
            return upload_url

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ProviderAuthenticationError(
                    "Invalid AssemblyAI API key",
                    provider="assemblyai",
                    operation="file_upload",
                    original_error=e,
                ) from e
            if e.response.status_code == 429:
                raise ProviderRateLimitError(
                    "AssemblyAI rate limit exceeded during upload",
                    provider="assemblyai",
                    operation="file_upload",
                    original_error=e,
                ) from e
            raise ProviderError(
                f"AssemblyAI upload failed: HTTP {e.response.status_code}",
                provider="assemblyai",
                operation="file_upload",
                original_error=e,
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                "AssemblyAI upload timed out",
                provider="assemblyai",
                operation="file_upload",
                original_error=e,
            ) from e
        except Exception as e:
            raise ProviderError(
                f"AssemblyAI upload error: {e}",
                provider="assemblyai",
                operation="file_upload",
                original_error=e,
            ) from e

    async def _create_transcript(
        self,
        audio_url: str,
        language: str | None,
        speaker_diarization: bool,
        **kwargs: Any,
    ) -> str:
        """Create transcription job.

        Args:
            audio_url: URL of audio file (from upload or external)
            language: Language code (e.g., "en")
            speaker_diarization: Enable speaker identification
            **kwargs: Additional AssemblyAI parameters

        Returns:
            Transcript ID for polling

        Raises:
            ProviderError: If job creation fails
        """
        try:
            # Build request payload
            payload = {
                "audio_url": audio_url,
                "speaker_labels": speaker_diarization,
                "punctuate": True,
                "format_text": True,
                **kwargs,
            }

            # Add language if specified
            if language:
                payload["language_code"] = language

            response = await self.client.post("/transcript", json=payload)
            response.raise_for_status()
            data = response.json()
            transcript_id = data.get("id")

            if not transcript_id:
                raise ProviderError(
                    "No transcript ID returned from AssemblyAI",
                    provider="assemblyai",
                    operation="create_transcript",
                )

            logger.debug(f"Created AssemblyAI transcript: {transcript_id}")
            return transcript_id

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ProviderAuthenticationError(
                    "Invalid AssemblyAI API key",
                    provider="assemblyai",
                    operation="create_transcript",
                    original_error=e,
                ) from e
            if e.response.status_code == 429:
                raise ProviderRateLimitError(
                    "AssemblyAI rate limit exceeded",
                    provider="assemblyai",
                    operation="create_transcript",
                    original_error=e,
                ) from e
            raise ProviderError(
                f"AssemblyAI transcript creation failed: HTTP {e.response.status_code}",
                provider="assemblyai",
                operation="create_transcript",
                original_error=e,
            ) from e
        except Exception as e:
            raise ProviderError(
                f"AssemblyAI transcript creation error: {e}",
                provider="assemblyai",
                operation="create_transcript",
                original_error=e,
            ) from e

    async def _poll_transcript(self, transcript_id: str) -> dict[str, Any]:
        """Poll for transcription completion.

        Args:
            transcript_id: Transcript ID to poll

        Returns:
            Completed transcript data

        Raises:
            ProviderError: If transcription fails
            ProviderTimeoutError: If polling times out
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > self.timeout:
                raise ProviderTimeoutError(
                    f"AssemblyAI transcription timed out after {self.timeout}s",
                    provider="assemblyai",
                    operation="poll_transcript",
                )

            try:
                response = await self.client.get(f"/transcript/{transcript_id}")
                response.raise_for_status()
                data = response.json()

                status = data.get("status")
                logger.debug(f"Transcript {transcript_id} status: {status}")

                if status == "completed":
                    return data
                if status == "error":
                    error_msg = data.get("error", "Unknown error")
                    raise ProviderError(
                        f"AssemblyAI transcription failed: {error_msg}",
                        provider="assemblyai",
                        operation="poll_transcript",
                    )
                if status in ("queued", "processing"):
                    # Still processing, continue polling
                    await asyncio.sleep(self.poll_interval)
                else:
                    # Unknown status
                    raise ProviderError(
                        f"Unknown AssemblyAI status: {status}",
                        provider="assemblyai",
                        operation="poll_transcript",
                    )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise ProviderAuthenticationError(
                        "Invalid AssemblyAI API key",
                        provider="assemblyai",
                        operation="poll_transcript",
                        original_error=e,
                    ) from e
                raise ProviderError(
                    f"AssemblyAI polling failed: HTTP {e.response.status_code}",
                    provider="assemblyai",
                    operation="poll_transcript",
                    original_error=e,
                ) from e
            except ProviderError:
                # Re-raise provider errors
                raise
            except Exception as e:
                raise ProviderError(
                    f"AssemblyAI polling error: {e}",
                    provider="assemblyai",
                    operation="poll_transcript",
                    original_error=e,
                ) from e

    async def transcribe(
        self,
        audio: bytes | str,
        language: str | None = None,
        speaker_diarization: bool = True,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe audio using AssemblyAI API.

        Args:
            audio: Audio data (bytes) or URL
            language: Optional language code (en, es, fr, etc.)
            speaker_diarization: Enable speaker identification
            **kwargs: Additional AssemblyAI parameters

        Returns:
            TranscriptionResult with text, segments, and speakers

        Raises:
            ProviderError: If transcription fails
        """
        try:
            # Step 1: Upload file or use provided URL
            if isinstance(audio, bytes):
                logger.info("Uploading audio file to AssemblyAI")
                audio_url = await self._upload_file(audio)
            else:
                # Assume it's a URL
                audio_url = audio
                logger.info(f"Using audio URL: {audio_url}")

            # Step 2: Create transcription job
            logger.info("Creating AssemblyAI transcription job")
            transcript_id = await self._create_transcript(
                audio_url, language, speaker_diarization, **kwargs
            )

            # Step 3: Poll for completion
            logger.info(f"Polling for transcription completion: {transcript_id}")
            data = await self._poll_transcript(transcript_id)

            # Step 4: Parse results
            return self._parse_results(data, language, speaker_diarization)

        except ProviderError:
            # Re-raise provider errors
            raise
        except Exception as e:
            raise ProviderError(
                f"AssemblyAI transcription failed: {e}",
                provider="assemblyai",
                operation="transcription",
                original_error=e,
            ) from e

    def _parse_results(
        self,
        data: dict[str, Any],
        language: str | None,
        speaker_diarization: bool,
    ) -> TranscriptionResult:
        """Parse AssemblyAI response into TranscriptionResult.

        Args:
            data: Raw API response
            language: Requested language
            speaker_diarization: Whether speaker diarization was enabled

        Returns:
            Parsed TranscriptionResult
        """
        # Get full transcript text
        transcript_text = data.get("text", "")

        # Parse segments with speaker attribution
        segments = []
        speakers_info = {}

        if speaker_diarization and data.get("utterances"):
            # Use utterances (speaker-attributed segments)
            for utterance in data["utterances"]:
                speaker_id = utterance.get("speaker")
                if speaker_id is not None:
                    speaker_label = f"Speaker {speaker_id}"
                    speakers_info[speaker_label] = speaker_label
                else:
                    speaker_label = None

                segments.append(
                    TranscriptionSegment(
                        text=utterance.get("text", ""),
                        start=utterance.get("start", 0) / 1000.0,  # Convert ms to seconds
                        end=utterance.get("end", 0) / 1000.0,
                        speaker=speaker_label,
                        confidence=utterance.get("confidence"),
                        words=utterance.get("words"),
                    )
                )
        elif data.get("words"):
            # Fallback: group words into segments
            current_segment = {
                "text": "",
                "start": 0.0,
                "end": 0.0,
                "speaker": None,
                "words": [],
            }

            for word in data["words"]:
                word_text = word.get("text", "")
                word_start = word.get("start", 0) / 1000.0
                word_end = word.get("end", 0) / 1000.0
                word_speaker = word.get("speaker")

                # Start new segment if speaker changes
                if (
                    speaker_diarization
                    and word_speaker is not None
                    and current_segment["text"]
                    and word_speaker != current_segment["speaker"]
                ):
                    segments.append(
                        TranscriptionSegment(
                            text=current_segment["text"].strip(),
                            start=current_segment["start"],
                            end=current_segment["end"],
                            speaker=(
                                f"Speaker {current_segment['speaker']}"
                                if current_segment["speaker"] is not None
                                else None
                            ),
                            words=current_segment["words"],
                        )
                    )
                    if word_speaker is not None:
                        speakers_info[f"Speaker {word_speaker}"] = f"Speaker {word_speaker}"
                    current_segment = {
                        "text": word_text,
                        "start": word_start,
                        "end": word_end,
                        "speaker": word_speaker,
                        "words": [word],
                    }
                else:
                    # Continue current segment
                    if not current_segment["text"]:
                        current_segment["start"] = word_start
                        current_segment["speaker"] = word_speaker
                    current_segment["text"] += " " + word_text
                    current_segment["end"] = word_end
                    current_segment["words"].append(word)
                    if word_speaker is not None:
                        speakers_info[f"Speaker {word_speaker}"] = f"Speaker {word_speaker}"

            # Add final segment
            if current_segment["text"]:
                segments.append(
                    TranscriptionSegment(
                        text=current_segment["text"].strip(),
                        start=current_segment["start"],
                        end=current_segment["end"],
                        speaker=(
                            f"Speaker {current_segment['speaker']}"
                            if current_segment["speaker"] is not None
                            else None
                        ),
                        words=current_segment["words"],
                    )
                )
        else:
            # No word-level data, create single segment
            segments.append(
                TranscriptionSegment(
                    text=transcript_text,
                    start=0.0,
                    end=data.get("audio_duration", 0) / 1000.0,
                )
            )

        # Get duration
        duration = data.get("audio_duration")
        if duration is not None:
            duration = duration / 1000.0  # Convert ms to seconds

        return TranscriptionResult(
            text=transcript_text,
            segments=segments,
            language=data.get("language_code") or language or "en",
            duration_seconds=duration,
            speakers=speakers_info if speakers_info else None,
            provider_metadata={
                "model": self.model_name,
                "confidence": data.get("confidence"),
                "audio_duration": duration,
                "transcript_id": data.get("id"),
            },
        )

    async def transcribe_dual_channel(
        self,
        channel1: bytes | str,
        channel2: bytes | str,
        language: str | None = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Transcribe dual-channel audio.

        For AssemblyAI, we transcribe both channels separately and merge
        the results with speaker attribution.

        Args:
            channel1: First audio channel (typically agent)
            channel2: Second audio channel (typically customer)
            language: Optional language code
            **kwargs: Additional parameters

        Returns:
            Merged TranscriptionResult with speaker attribution
        """
        # Transcribe both channels separately without speaker diarization
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
                    words=seg.words,
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
                    words=seg.words,
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

        AssemblyAI supports 100+ languages.
        """
        return [
            "en",  # English (Global)
            "en_au",  # English (Australian)
            "en_uk",  # English (British)
            "en_us",  # English (US)
            "es",  # Spanish
            "fr",  # French
            "de",  # German
            "it",  # Italian
            "pt",  # Portuguese
            "nl",  # Dutch
            "af",  # Afrikaans
            "sq",  # Albanian
            "am",  # Amharic
            "ar",  # Arabic
            "hy",  # Armenian
            "az",  # Azerbaijani
            "eu",  # Basque
            "be",  # Belarusian
            "bn",  # Bengali
            "bs",  # Bosnian
            "bg",  # Bulgarian
            "ca",  # Catalan
            "zh",  # Chinese
            "hr",  # Croatian
            "cs",  # Czech
            "da",  # Danish
            "et",  # Estonian
            "fi",  # Finnish
            "gl",  # Galician
            "ka",  # Georgian
            "el",  # Greek
            "gu",  # Gujarati
            "he",  # Hebrew
            "hi",  # Hindi
            "hu",  # Hungarian
            "is",  # Icelandic
            "id",  # Indonesian
            "ja",  # Japanese
            "jv",  # Javanese
            "kn",  # Kannada
            "kk",  # Kazakh
            "ko",  # Korean
            "lo",  # Lao
            "lv",  # Latvian
            "lt",  # Lithuanian
            "mk",  # Macedonian
            "ms",  # Malay
            "ml",  # Malayalam
            "mr",  # Marathi
            "mn",  # Mongolian
            "ne",  # Nepali
            "no",  # Norwegian
            "fa",  # Persian
            "pl",  # Polish
            "ro",  # Romanian
            "ru",  # Russian
            "sr",  # Serbian
            "si",  # Sinhala
            "sk",  # Slovak
            "sl",  # Slovenian
            "so",  # Somali
            "su",  # Sundanese
            "sw",  # Swahili
            "sv",  # Swedish
            "tl",  # Tagalog
            "ta",  # Tamil
            "te",  # Telugu
            "th",  # Thai
            "tr",  # Turkish
            "uk",  # Ukrainian
            "ur",  # Urdu
            "uz",  # Uzbek
            "vi",  # Vietnamese
            "cy",  # Welsh
            # ... AssemblyAI supports many more
            # Full list: https://www.assemblyai.com/docs/getting-started/supported-languages
        ]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
        logger.info("Closed AssemblyAI provider")
