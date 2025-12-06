"""Predefined pipeline definitions for common AI workflows.

This module provides ready-to-use pipeline definitions for:
- Basic transcription
- Transcription with speaker diarization
- Transcription with PII redaction
- Full call analysis (transcription → redaction → summary → sentiment → coaching)

Usage:
    from example_service.infra.ai.pipelines.predefined import (
        get_call_analysis_pipeline,
        get_transcription_pipeline,
    )

    # Get a predefined pipeline
    pipeline = get_call_analysis_pipeline()

    # Execute it
    result = await executor.execute(
        pipeline=pipeline,
        input_data={"audio": audio_bytes},
    )

Pipeline Customization:
    All pipelines are built using the Pipeline DSL, so you can easily
    modify them or use them as templates for custom pipelines.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from example_service.infra.ai.capabilities.types import Capability
from example_service.infra.ai.pipelines.builder import Pipeline

if TYPE_CHECKING:
    from example_service.infra.ai.pipelines.types import PipelineDefinition


def get_transcription_pipeline(
    *,
    with_diarization: bool = True,
    provider_preference: list[str] | None = None,
) -> PipelineDefinition:
    """Get a basic transcription pipeline.

    Features:
    - Speaker diarization (optional)
    - Word-level timestamps
    - Fallback between Deepgram and OpenAI Whisper

    Args:
        with_diarization: Include speaker diarization
        provider_preference: Override provider preference order

    Returns:
        PipelineDefinition for transcription
    """
    providers = provider_preference or ["deepgram", "openai"]
    capability = (
        Capability.TRANSCRIPTION_DIARIZATION
        if with_diarization
        else Capability.TRANSCRIPTION
    )

    return (
        Pipeline("transcription")
        .version("1.0.0")
        .description(
            "Transcribe audio with optional speaker diarization"
            if with_diarization
            else "Basic audio transcription"
        )
        .tags("transcription", "audio")
        .timeout(600)
        .estimated_duration(120)

        .step("transcribe")
            .description("Transcribe audio to text")
            .capability(capability)
            .prefer_providers(*providers)
            .output_as("transcript")
            .with_fallback(max_fallbacks=2)
            .with_retry(max_attempts=3)
            .timeout(300)
            .progress_weight(1.0)
            .done()

        .build()
    )


def get_transcription_with_redaction_pipeline(
    *,
    with_diarization: bool = True,
    entity_types: list[str] | None = None,
    redaction_method: str = "mask",
) -> PipelineDefinition:
    """Get a transcription pipeline with PII redaction.

    Features:
    - Speech-to-text with speaker diarization
    - PII detection and redaction
    - Configurable entity types and redaction methods

    Args:
        with_diarization: Include speaker diarization
        entity_types: PII entity types to redact (default: all common types)
        redaction_method: How to redact PII (mask, replace, hash, remove)

    Returns:
        PipelineDefinition for transcription with redaction
    """
    transcribe_capability = (
        Capability.TRANSCRIPTION_DIARIZATION
        if with_diarization
        else Capability.TRANSCRIPTION
    )

    default_entities = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
    ]

    return (
        Pipeline("transcription_with_redaction")
        .version("1.0.0")
        .description("Transcribe audio and redact PII from the transcript")
        .tags("transcription", "pii", "redaction", "compliance")
        .timeout(600)
        .estimated_duration(180)
        .with_compensation()

        # Step 1: Transcription
        .step("transcribe")
            .description("Transcribe audio to text with speaker identification")
            .capability(transcribe_capability)
            .prefer_providers("deepgram", "openai")
            .output_as("transcript")
            .with_fallback(max_fallbacks=2)
            .with_retry(max_attempts=3)
            .timeout(300)
            .progress_weight(3.0)
            .done()

        # Step 2: PII Redaction
        .step("redact_pii")
            .description("Detect and redact personally identifiable information")
            .capability(Capability.PII_REDACTION)
            .prefer_providers("accent_redaction")
            .input_transform(lambda ctx: {
                "segments": getattr(ctx.get("transcript"), "segments", []),
                "entity_types": entity_types or default_entities,
                "redaction_method": redaction_method,
            })
            .output_as("redacted_transcript")
            .no_fallback()  # Internal service only
            .with_retry(max_attempts=2)
            .timeout(60)
            .progress_weight(1.0)
            .done()

        .checkpoint("transcribe")
        .checkpoint("redact_pii")
        .build()
    )


def get_call_analysis_pipeline(
    *,
    include_summary: bool = True,
    include_sentiment: bool = True,
    include_coaching: bool = True,
    summary_max_length: int = 500,
    llm_provider_preference: list[str] | None = None,
) -> PipelineDefinition:
    """Get the full call analysis pipeline.

    Features:
    - Transcription with speaker diarization
    - PII redaction
    - Call summarization
    - Sentiment analysis per speaker
    - Coaching insights

    This is the complete pipeline for analyzing call center recordings.

    Args:
        include_summary: Include summarization step
        include_sentiment: Include sentiment analysis step
        include_coaching: Include coaching analysis step
        summary_max_length: Maximum summary length in words
        llm_provider_preference: Provider preference for LLM steps

    Returns:
        PipelineDefinition for full call analysis
    """
    llm_providers = llm_provider_preference or ["anthropic", "openai"]

    builder = (
        Pipeline("call_analysis")
        .version("1.0.0")
        .description(
            "Complete call analysis: transcription, PII redaction, "
            "summarization, sentiment analysis, and coaching insights"
        )
        .tags("call-center", "analysis", "transcription", "insights")
        .timeout(900)
        .estimated_duration(300)
        .estimated_cost(Decimal("0.15"))
        .with_compensation(timeout_seconds=120)

        # Step 1: Transcription with diarization
        .step("transcribe")
            .description("Transcribe audio with speaker diarization")
            .capability(Capability.TRANSCRIPTION_DIARIZATION)
            .prefer_providers("deepgram", "openai")
            .output_as("transcript")
            .with_fallback(max_fallbacks=2)
            .with_retry(max_attempts=3)
            .timeout(300)
            .progress_weight(3.0)
            .done()

        # Step 2: PII Redaction
        .step("redact_pii")
            .description("Redact personally identifiable information")
            .capability(Capability.PII_REDACTION)
            .prefer_providers("accent_redaction")
            .input_transform(lambda ctx: {
                "segments": getattr(ctx.get("transcript"), "segments", []),
                "entity_types": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN"],
            })
            .output_as("redacted_transcript")
            .no_fallback()
            .with_retry(max_attempts=2)
            .timeout(60)
            .progress_weight(1.0)
            .done()

        .checkpoint("transcribe")
        .checkpoint("redact_pii")
    )

    # Step 3: Summarization (conditional)
    if include_summary:
        builder = (
            builder
            .step("summarize")
                .description("Generate call summary")
                .capability(Capability.SUMMARIZATION)
                .prefer_providers(*llm_providers)
                .input_transform(lambda ctx: {
                    "text": _get_full_text(ctx.get("redacted_transcript")),
                    "max_length": summary_max_length,
                    "format": "bullet_points",
                })
                .output_as("summary")
                .when(lambda ctx: _has_sufficient_content(ctx.get("redacted_transcript"), 100))
                .with_fallback(max_fallbacks=2)
                .with_retry(max_attempts=2)
                .timeout(120)
                .progress_weight(2.0)
                .done()
            .checkpoint("summarize")
        )

    # Step 4: Sentiment Analysis (conditional)
    if include_sentiment:
        builder = (
            builder
            .step("sentiment")
                .description("Analyze sentiment per speaker")
                .capability(Capability.SENTIMENT_ANALYSIS)
                .prefer_providers(*llm_providers)
                .input_transform(lambda ctx: {
                    "segments": getattr(ctx.get("redacted_transcript"), "segments", []),
                    "analyze_per_speaker": True,
                })
                .output_as("sentiment_analysis")
                .when(lambda ctx: _has_sufficient_content(ctx.get("redacted_transcript"), 50))
                .with_fallback(max_fallbacks=2)
                .with_retry(max_attempts=2)
                .timeout(90)
                .progress_weight(1.5)
                .done()
            .checkpoint("sentiment")
        )

    # Step 5: Coaching Analysis (conditional)
    if include_coaching:
        builder = (
            builder
            .step("coaching")
                .description("Generate coaching insights for agent improvement")
                .capability(Capability.COACHING_ANALYSIS)
                .prefer_providers(*llm_providers)
                .input_transform(lambda ctx: {
                    "transcript": ctx.get("redacted_transcript"),
                    "summary": ctx.get("summary"),
                    "sentiment": ctx.get("sentiment_analysis"),
                })
                .output_as("coaching_insights")
                .when(lambda ctx: _has_sufficient_content(ctx.get("redacted_transcript"), 100))
                .with_fallback(max_fallbacks=2)
                .with_retry(max_attempts=2)
                .timeout(120)
                .progress_weight(2.0)
                .done()
            .checkpoint("coaching")
        )

    return builder.build()


def get_dual_channel_analysis_pipeline(
    *,
    include_summary: bool = True,
    include_sentiment: bool = True,
) -> PipelineDefinition:
    """Get pipeline for dual-channel (stereo) call analysis.

    Designed for recordings where agent and customer are on
    separate audio channels.

    Args:
        include_summary: Include summarization step
        include_sentiment: Include sentiment analysis step

    Returns:
        PipelineDefinition for dual-channel analysis
    """
    builder = (
        Pipeline("dual_channel_analysis")
        .version("1.0.0")
        .description("Analyze dual-channel call recordings with separate agent/customer channels")
        .tags("call-center", "dual-channel", "stereo")
        .timeout(900)
        .estimated_duration(300)
        .with_compensation()

        # Step 1: Dual-channel transcription
        .step("transcribe")
            .description("Transcribe dual-channel audio")
            .capability(Capability.TRANSCRIPTION_DUAL_CHANNEL)
            .prefer_providers("deepgram", "openai")
            .output_as("transcript")
            .with_fallback(max_fallbacks=2)
            .with_retry(max_attempts=3)
            .timeout(300)
            .progress_weight(3.0)
            .done()

        # Step 2: PII Redaction
        .step("redact_pii")
            .description("Redact PII from transcript")
            .capability(Capability.PII_REDACTION)
            .prefer_providers("accent_redaction")
            .input_transform(lambda ctx: {
                "segments": getattr(ctx.get("transcript"), "segments", []),
            })
            .output_as("redacted_transcript")
            .no_fallback()
            .timeout(60)
            .progress_weight(1.0)
            .done()

        .checkpoint("transcribe")
        .checkpoint("redact_pii")
    )

    if include_summary:
        builder = (
            builder
            .step("summarize")
                .capability(Capability.SUMMARIZATION)
                .prefer_providers("anthropic", "openai")
                .input_transform(lambda ctx: {
                    "text": _get_full_text(ctx.get("redacted_transcript")),
                    "format": "narrative",
                })
                .output_as("summary")
                .with_fallback(max_fallbacks=2)
                .timeout(120)
                .progress_weight(2.0)
                .done()
        )

    if include_sentiment:
        builder = (
            builder
            .step("sentiment")
                .capability(Capability.SENTIMENT_ANALYSIS)
                .prefer_providers("anthropic", "openai")
                .input_transform(lambda ctx: {
                    "text": _get_full_text(ctx.get("redacted_transcript")),
                    "analyze_per_channel": True,
                })
                .output_as("sentiment_analysis")
                .with_fallback(max_fallbacks=2)
                .timeout(90)
                .progress_weight(1.5)
                .done()
        )

    return builder.build()


def get_pii_detection_pipeline() -> PipelineDefinition:
    """Get a simple PII detection pipeline.

    For detecting (not redacting) PII in text.

    Returns:
        PipelineDefinition for PII detection
    """
    return (
        Pipeline("pii_detection")
        .version("1.0.0")
        .description("Detect personally identifiable information in text")
        .tags("pii", "detection", "compliance")
        .timeout(60)
        .estimated_duration(5)

        .step("detect_pii")
            .description("Detect PII entities in text")
            .capability(Capability.PII_DETECTION)
            .prefer_providers("accent_redaction")
            .output_as("pii_entities")
            .no_fallback()
            .timeout(30)
            .done()

        .build()
    )


def get_text_summarization_pipeline(
    *,
    max_length: int = 500,
    format: str = "paragraph",
) -> PipelineDefinition:
    """Get a simple text summarization pipeline.

    Args:
        max_length: Maximum summary length in words
        format: Summary format (paragraph, bullet_points, key_points)

    Returns:
        PipelineDefinition for text summarization
    """
    return (
        Pipeline("text_summarization")
        .version("1.0.0")
        .description("Summarize text content")
        .tags("summarization", "text", "llm")
        .timeout(120)
        .estimated_duration(30)

        .step("summarize")
            .description("Generate summary from text")
            .capability(Capability.SUMMARIZATION)
            .prefer_providers("anthropic", "openai")
            .input_transform(lambda ctx: {
                "text": ctx.get("text"),
                "max_length": max_length,
                "format": format,
            })
            .output_as("summary")
            .with_fallback(max_fallbacks=2)
            .with_retry(max_attempts=2)
            .timeout(90)
            .done()

        .build()
    )


# Helper functions for pipeline transforms


def _get_full_text(transcript: object | None) -> str:
    """Extract full text from a transcript object."""
    if transcript is None:
        return ""

    # Handle different transcript formats
    if hasattr(transcript, "text"):
        text = getattr(transcript, "text", "")
        return str(text) if text is not None else ""
    if hasattr(transcript, "full_text"):
        full_text = getattr(transcript, "full_text", "")
        return str(full_text) if full_text is not None else ""
    if hasattr(transcript, "segments"):
        segments = getattr(transcript, "segments", None)
        if isinstance(segments, list):
            return " ".join(
                seg.get("text", "") if isinstance(seg, dict) else str(getattr(seg, "text", ""))
                for seg in segments
            )
    if isinstance(transcript, dict):
        return str(transcript.get("text", "") or transcript.get("full_text", ""))

    return str(transcript)


def _has_sufficient_content(transcript: object | None, min_words: int) -> bool:
    """Check if transcript has enough content for analysis."""
    text = _get_full_text(transcript)
    word_count = len(text.split())
    return word_count >= min_words


# Registry of all predefined pipelines
PREDEFINED_PIPELINES = {
    "transcription": get_transcription_pipeline,
    "transcription_with_diarization": lambda: get_transcription_pipeline(with_diarization=True),
    "transcription_with_redaction": get_transcription_with_redaction_pipeline,
    "call_analysis": get_call_analysis_pipeline,
    "dual_channel_analysis": get_dual_channel_analysis_pipeline,
    "pii_detection": get_pii_detection_pipeline,
    "text_summarization": get_text_summarization_pipeline,
}


def get_pipeline(name: str, **kwargs: Any) -> PipelineDefinition:
    """Get a predefined pipeline by name.

    Args:
        name: Pipeline name
        **kwargs: Pipeline-specific options

    Returns:
        PipelineDefinition

    Raises:
        KeyError: If pipeline name not found
    """
    if name not in PREDEFINED_PIPELINES:
        available = ", ".join(PREDEFINED_PIPELINES.keys())
        raise KeyError(f"Unknown pipeline: {name}. Available: {available}")

    factory = PREDEFINED_PIPELINES[name]
    if kwargs:
        return factory(**kwargs)  # type: ignore[operator, no-any-return]
    return factory()  # type: ignore[operator, no-any-return]


def list_pipelines() -> list[dict]:
    """List all available predefined pipelines.

    Returns:
        List of pipeline info dicts
    """
    pipelines = []
    for name, factory in PREDEFINED_PIPELINES.items():
        pipeline = factory()  # type: ignore[operator]
        pipelines.append({
            "name": name,
            "version": pipeline.version,
            "description": pipeline.description,
            "tags": pipeline.tags,
            "step_count": len(pipeline.steps),
            "estimated_duration_seconds": pipeline.estimated_duration_seconds,
            "estimated_cost_usd": str(pipeline.estimated_cost_usd) if pipeline.estimated_cost_usd else None,
            "required_capabilities": [step.capability.value for step in pipeline.steps if step.capability],
        })
    return pipelines
