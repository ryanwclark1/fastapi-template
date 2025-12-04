"""Unit tests for Pipeline Builder DSL.

Tests cover:
- StepBuilder fluent API and validation
- PipelineBuilder fluent API and validation
- Condition building (when, when_exists, when_equals)
- Retry and fallback configuration
- Pipeline composition patterns
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from example_service.infra.ai.capabilities.types import Capability, QualityTier
from example_service.infra.ai.pipelines.builder import (
    Pipeline,
    PipelineBuilder,
    Step,
    StepBuilder,
)
from example_service.infra.ai.pipelines.types import (
    ConditionalOperator,
    FallbackConfig,
    PipelineStep,
    RetryPolicy,
)

# ──────────────────────────────────────────────────────────────
# Test StepBuilder
# ──────────────────────────────────────────────────────────────


class TestStepBuilder:
    """Tests for StepBuilder fluent API."""

    def test_step_requires_capability(self):
        """Step build should fail without capability."""
        step = StepBuilder("test")

        with pytest.raises(ValueError, match="requires a capability"):
            step.build()

    def test_step_with_capability(self):
        """Step should accept capability setting."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .build()
        )

        assert step.name == "transcribe"
        assert step.capability == Capability.TRANSCRIPTION

    def test_step_description(self):
        """Step should accept description."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .description("Transcribe audio to text")
            .build()
        )

        assert step.description == "Transcribe audio to text"

    def test_step_provider_preference(self):
        """Step should accept provider preference order."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .prefer_providers("deepgram", "openai")
            .build()
        )

        assert step.provider_preference == ["deepgram", "openai"]

    def test_step_quality_tier(self):
        """Step should accept quality tier requirement."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .require_quality(QualityTier.PREMIUM)
            .build()
        )

        assert step.required_quality_tier == QualityTier.PREMIUM

    def test_step_options(self):
        """Step should accept arbitrary options."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .with_options(language="en", diarization=True)
            .build()
        )

        assert step.options == {"language": "en", "diarization": True}

    def test_step_input_output(self):
        """Step should accept input/output key configuration."""
        step = (
            Step("summarize")
            .capability(Capability.SUMMARIZATION)
            .input_from("transcript")
            .output_as("summary")
            .build()
        )

        assert step.input_key == "transcript"
        assert step.output_key == "summary"

    def test_step_input_transform(self):
        """Step should accept input transform function."""
        def transform(ctx):
            return ctx.get("transcript", {}).get("text", "")

        step = (
            Step("summarize")
            .capability(Capability.SUMMARIZATION)
            .input_transform(transform)
            .build()
        )

        assert step.input_transform is not None

    def test_step_output_transform(self):
        """Step should accept output transform function."""
        def transform(output):
            return {"text": output, "length": len(output)}

        step = (
            Step("summarize")
            .capability(Capability.SUMMARIZATION)
            .output_transform(transform)
            .build()
        )

        assert step.output_transform is transform

    def test_step_timeout(self):
        """Step should accept custom timeout."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .timeout(300)
            .build()
        )

        assert step.timeout_seconds == 300

    def test_step_default_timeout(self):
        """Step should have default timeout."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .build()
        )

        assert step.timeout_seconds == 120  # Default

    def test_step_progress_weight(self):
        """Step should accept progress weight."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .progress_weight(2.5)
            .build()
        )

        assert step.progress_weight == 2.5


# ──────────────────────────────────────────────────────────────
# Test Step Conditions
# ──────────────────────────────────────────────────────────────


class TestStepConditions:
    """Tests for step condition configuration."""

    def test_when_with_function(self):
        """Step should accept lambda condition."""
        def condition_fn(ctx):
            return len(ctx.get("text", "")) > 100

        step = (
            Step("summarize")
            .capability(Capability.SUMMARIZATION)
            .when(condition_fn)
            .build()
        )

        assert step.condition is not None
        # Test the condition evaluates correctly
        assert step.condition.evaluate({"text": "x" * 101}) is True
        assert step.condition.evaluate({"text": "short"}) is False

    def test_when_exists(self):
        """Step should accept existence condition."""
        step = (
            Step("summarize")
            .capability(Capability.SUMMARIZATION)
            .when_exists("transcript")
            .build()
        )

        assert step.condition is not None
        assert step.condition.context_path == "transcript"
        assert step.condition.operator == ConditionalOperator.EXISTS

    def test_when_equals(self):
        """Step should accept equality condition."""
        step = (
            Step("coaching")
            .capability(Capability.LLM_GENERATION)
            .when_equals("options.include_coaching", True)
            .build()
        )

        assert step.condition is not None
        assert step.condition.context_path == "options.include_coaching"
        assert step.condition.operator == ConditionalOperator.EQUALS
        assert step.condition.value is True


# ──────────────────────────────────────────────────────────────
# Test Step Optional/Required
# ──────────────────────────────────────────────────────────────


class TestStepOptional:
    """Tests for step required/optional configuration."""

    def test_step_is_required_by_default(self):
        """Steps should be required by default."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .build()
        )

        assert step.required is True
        assert step.continue_on_failure is False

    def test_step_optional(self):
        """Optional step should set both flags."""
        step = (
            Step("sentiment")
            .capability(Capability.SENTIMENT_ANALYSIS)
            .optional()
            .build()
        )

        assert step.required is False
        assert step.continue_on_failure is True

    def test_step_continue_on_failure(self):
        """Continue on failure should set flag."""
        step = (
            Step("sentiment")
            .capability(Capability.SENTIMENT_ANALYSIS)
            .continue_on_failure()
            .build()
        )

        assert step.continue_on_failure is True


# ──────────────────────────────────────────────────────────────
# Test Step Fallback Configuration
# ──────────────────────────────────────────────────────────────


class TestStepFallback:
    """Tests for step fallback configuration."""

    def test_fallback_enabled_by_default(self):
        """Fallback should be enabled by default with default settings."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .build()
        )

        assert step.fallback_config.enabled is True

    def test_with_fallback_configuration(self):
        """with_fallback should configure fallback settings."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .with_fallback(
                max_fallbacks=5,
                allow_quality_degradation=False,
                exclude_providers=["openai"],
            )
            .build()
        )

        assert step.fallback_config.enabled is True
        assert step.fallback_config.max_fallbacks == 5
        assert step.fallback_config.fallback_quality_degradation is False
        assert step.fallback_config.excluded_providers == ["openai"]

    def test_no_fallback(self):
        """no_fallback should disable fallback."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .no_fallback()
            .build()
        )

        assert step.fallback_config.enabled is False


# ──────────────────────────────────────────────────────────────
# Test Step Retry Configuration
# ──────────────────────────────────────────────────────────────


class TestStepRetry:
    """Tests for step retry configuration."""

    def test_default_retry_policy(self):
        """Step should have default retry policy."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .build()
        )

        assert step.retry_policy.max_attempts == 3  # Default
        assert step.retry_policy.exponential_backoff is True

    def test_with_retry_configuration(self):
        """with_retry should configure retry settings."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .with_retry(
                max_attempts=5,
                initial_delay_ms=2000,
                exponential_backoff=False,
            )
            .build()
        )

        assert step.retry_policy.max_attempts == 5
        assert step.retry_policy.initial_delay_ms == 2000
        assert step.retry_policy.exponential_backoff is False

    def test_no_retry(self):
        """no_retry should set max_attempts to 1."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .no_retry()
            .build()
        )

        assert step.retry_policy.max_attempts == 1


# ──────────────────────────────────────────────────────────────
# Test Step Compensation
# ──────────────────────────────────────────────────────────────


class TestStepCompensation:
    """Tests for step compensation configuration."""

    def test_no_compensation_by_default(self):
        """Steps should have no compensation by default."""
        step = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .build()
        )

        assert step.compensation is None

    def test_compensate_with(self):
        """compensate_with should set compensation handler."""
        async def compensate(ctx):
            # Delete uploaded file
            pass

        step = (
            Step("upload")
            .capability(Capability.TRANSCRIPTION)
            .compensate_with(compensate, description="Delete uploaded file")
            .build()
        )

        assert step.compensation is not None
        assert step.compensation.description == "Delete uploaded file"


# ──────────────────────────────────────────────────────────────
# Test PipelineBuilder
# ──────────────────────────────────────────────────────────────


class TestPipelineBuilder:
    """Tests for PipelineBuilder fluent API."""

    def test_pipeline_requires_steps(self):
        """Pipeline build should fail without steps."""
        builder = Pipeline("empty")

        with pytest.raises(ValueError, match="has no steps"):
            builder.build()

    def test_pipeline_basic_build(self):
        """Pipeline should build with minimal configuration."""
        pipeline = (
            Pipeline("simple")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.name == "simple"
        assert pipeline.version == "1.0.0"  # Default
        assert len(pipeline.steps) == 1

    def test_pipeline_version(self):
        """Pipeline should accept version."""
        pipeline = (
            Pipeline("versioned")
            .version("2.1.0")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.version == "2.1.0"

    def test_pipeline_description(self):
        """Pipeline should accept description."""
        pipeline = (
            Pipeline("described")
            .description("A test pipeline")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.description == "A test pipeline"

    def test_pipeline_tags(self):
        """Pipeline should accept tags."""
        pipeline = (
            Pipeline("tagged")
            .tags("call-analysis", "audio", "ai")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.tags == ["call-analysis", "audio", "ai"]

    def test_pipeline_timeout(self):
        """Pipeline should accept timeout."""
        pipeline = (
            Pipeline("timed")
            .timeout(1200)
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.timeout_seconds == 1200

    def test_pipeline_default_timeout(self):
        """Pipeline should have default timeout."""
        pipeline = (
            Pipeline("default_timed")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.timeout_seconds == 600  # Default

    def test_pipeline_max_concurrent(self):
        """Pipeline should accept max concurrent steps."""
        pipeline = (
            Pipeline("parallel")
            .max_concurrent(3)
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.max_concurrent_steps == 3

    def test_pipeline_no_fail_fast(self):
        """Pipeline should support no fail fast mode."""
        pipeline = (
            Pipeline("lenient")
            .no_fail_fast()
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.fail_fast is False

    def test_pipeline_fail_fast_by_default(self):
        """Pipeline should fail fast by default."""
        pipeline = (
            Pipeline("strict")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.fail_fast is True


# ──────────────────────────────────────────────────────────────
# Test Pipeline Compensation
# ──────────────────────────────────────────────────────────────


class TestPipelineCompensation:
    """Tests for pipeline compensation configuration."""

    def test_compensation_enabled_by_default(self):
        """Compensation should be enabled by default."""
        pipeline = (
            Pipeline("compensated")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.enable_compensation is True

    def test_with_compensation(self):
        """with_compensation should configure timeout."""
        pipeline = (
            Pipeline("compensated")
            .with_compensation(timeout_seconds=300)
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.enable_compensation is True
        assert pipeline.compensation_timeout_seconds == 300

    def test_no_compensation(self):
        """no_compensation should disable compensation."""
        pipeline = (
            Pipeline("no_compensate")
            .no_compensation()
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.enable_compensation is False


# ──────────────────────────────────────────────────────────────
# Test Pipeline Estimates
# ──────────────────────────────────────────────────────────────


class TestPipelineEstimates:
    """Tests for pipeline duration/cost estimates."""

    def test_estimated_duration(self):
        """Pipeline should accept estimated duration."""
        pipeline = (
            Pipeline("estimated")
            .estimated_duration(180)
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.estimated_duration_seconds == 180

    def test_estimated_cost(self):
        """Pipeline should accept estimated cost."""
        pipeline = (
            Pipeline("costed")
            .estimated_cost("0.15")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.estimated_cost_usd == Decimal("0.15")

    def test_estimated_cost_from_float(self):
        """Pipeline should accept float for cost."""
        pipeline = (
            Pipeline("costed")
            .estimated_cost(0.15)
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.estimated_cost_usd == Decimal("0.15")


# ──────────────────────────────────────────────────────────────
# Test Pipeline Checkpoints
# ──────────────────────────────────────────────────────────────


class TestPipelineCheckpoints:
    """Tests for pipeline progress checkpoints."""

    def test_no_checkpoints_by_default(self):
        """Pipeline should have no checkpoints by default."""
        pipeline = (
            Pipeline("no_checkpoints")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .build()
        )

        assert pipeline.progress_checkpoints == []

    def test_checkpoint(self):
        """Pipeline should accept checkpoint markers."""
        pipeline = (
            Pipeline("checkpointed")
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .checkpoint("step1")
            .step("step2")
                .capability(Capability.SUMMARIZATION)
                .done()
            .checkpoint("step2")
            .build()
        )

        assert pipeline.progress_checkpoints == ["step1", "step2"]


# ──────────────────────────────────────────────────────────────
# Test Pipeline Step Addition
# ──────────────────────────────────────────────────────────────


class TestPipelineStepAddition:
    """Tests for adding steps to pipelines."""

    def test_add_prebuilt_step(self):
        """Pipeline should accept pre-built steps."""
        prebuilt = (
            Step("transcribe")
            .capability(Capability.TRANSCRIPTION)
            .prefer_providers("deepgram")
            .build()
        )

        pipeline = (
            Pipeline("with_prebuilt")
            .add_step(prebuilt)
            .build()
        )

        assert len(pipeline.steps) == 1
        assert pipeline.steps[0].name == "transcribe"

    def test_add_multiple_prebuilt_steps(self):
        """Pipeline should accept multiple pre-built steps."""
        step1 = Step("step1").capability(Capability.TRANSCRIPTION).build()
        step2 = Step("step2").capability(Capability.PII_REDACTION).build()
        step3 = Step("step3").capability(Capability.SUMMARIZATION).build()

        pipeline = (
            Pipeline("multi_prebuilt")
            .add_steps(step1, step2, step3)
            .build()
        )

        assert len(pipeline.steps) == 3

    def test_mixed_step_addition(self):
        """Pipeline should support mixing inline and pre-built steps."""
        prebuilt = Step("prebuilt").capability(Capability.PII_REDACTION).build()

        pipeline = (
            Pipeline("mixed")
            .step("inline1")
                .capability(Capability.TRANSCRIPTION)
                .done()
            .add_step(prebuilt)
            .step("inline2")
                .capability(Capability.SUMMARIZATION)
                .done()
            .build()
        )

        assert len(pipeline.steps) == 3
        assert pipeline.steps[0].name == "inline1"
        assert pipeline.steps[1].name == "prebuilt"
        assert pipeline.steps[2].name == "inline2"


# ──────────────────────────────────────────────────────────────
# Test Complex Pipeline Building
# ──────────────────────────────────────────────────────────────


class TestComplexPipeline:
    """Tests for building complex multi-step pipelines."""

    def test_call_analysis_pipeline(self):
        """Build a complete call analysis pipeline."""
        pipeline = (
            Pipeline("call_analysis")
            .version("1.0.0")
            .description("Full call analysis with transcription, PII redaction, and insights")
            .tags("call-center", "audio", "analysis")
            .timeout(600)
            .estimated_duration(120)
            .estimated_cost("0.25")

            .step("transcribe")
                .capability(Capability.TRANSCRIPTION_DIARIZATION)
                .prefer_providers("deepgram", "openai")
                .output_as("transcript")
                .with_fallback(max_fallbacks=2)
                .with_retry(max_attempts=3)
                .timeout(300)
                .progress_weight(3.0)
                .done()

            .step("redact_pii")
                .capability(Capability.PII_REDACTION)
                .prefer_providers("accent_redaction")
                .input_from("transcript")
                .output_as("redacted")
                .done()

            .step("summarize")
                .capability(Capability.SUMMARIZATION)
                .prefer_providers("anthropic", "openai")
                .when(lambda ctx: len(ctx.get("redacted", {}).get("text", "")) > 500)
                .input_from("redacted")
                .output_as("summary")
                .optional()
                .done()

            .step("sentiment")
                .capability(Capability.SENTIMENT_ANALYSIS)
                .prefer_providers("anthropic")
                .input_from("redacted")
                .output_as("sentiment")
                .optional()
                .done()

            .build()
        )

        assert pipeline.name == "call_analysis"
        assert pipeline.version == "1.0.0"
        assert len(pipeline.steps) == 4
        assert len(pipeline.tags) == 3

        # Verify step properties
        transcribe = pipeline.steps[0]
        assert transcribe.capability == Capability.TRANSCRIPTION_DIARIZATION
        assert transcribe.provider_preference == ["deepgram", "openai"]
        assert transcribe.output_key == "transcript"
        assert transcribe.progress_weight == 3.0
        assert transcribe.fallback_config.max_fallbacks == 2
        assert transcribe.retry_policy.max_attempts == 3

        summarize = pipeline.steps[2]
        assert summarize.required is False
        assert summarize.condition is not None


# ──────────────────────────────────────────────────────────────
# Test Step done() Method
# ──────────────────────────────────────────────────────────────


class TestStepDone:
    """Tests for step done() method behavior."""

    def test_done_returns_pipeline_builder(self):
        """done() should return parent pipeline builder."""
        builder = Pipeline("test")
        returned = (
            builder
            .step("step1")
                .capability(Capability.TRANSCRIPTION)
                .done()
        )

        assert returned is builder

    def test_done_fails_without_parent(self):
        """done() should fail for standalone step builder."""
        step = StepBuilder("standalone")
        step.capability(Capability.TRANSCRIPTION)

        with pytest.raises(ValueError, match="only be called when building"):
            step.done()


# ──────────────────────────────────────────────────────────────
# Test Convenience Functions
# ──────────────────────────────────────────────────────────────


class TestConvenienceFunctions:
    """Tests for Pipeline() and Step() convenience functions."""

    def test_pipeline_function_creates_builder(self):
        """Pipeline() should create PipelineBuilder."""
        builder = Pipeline("test")
        assert isinstance(builder, PipelineBuilder)

    def test_step_function_creates_builder(self):
        """Step() should create StepBuilder."""
        builder = Step("test")
        assert isinstance(builder, StepBuilder)

    def test_step_function_is_standalone(self):
        """Step() should create standalone builder."""
        builder = Step("test")
        assert builder._pipeline_builder is None
