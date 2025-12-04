"""Provider Adapters for AI Capabilities.

Adapters wrap existing provider implementations and add:
- Capability declarations with metadata
- Standardized result format (OperationResult)
- Cost tracking and usage metrics
- Health check support

Architecture:
    ProviderAdapter (base)
        ├── OpenAIAdapter (wraps OpenAILLMProvider, OpenAITranscriptionProvider)
        ├── AnthropicAdapter (new implementation)
        ├── DeepgramAdapter (wraps DeepgramProvider)
        ├── AccentRedactionAdapter (wraps AccentRedactionProvider)
        ├── AccentSTTAdapter (internal transcription)
        └── OllamaAdapter (local LLM)

Usage:
    from example_service.infra.ai.capabilities.adapters import (
        OpenAIAdapter,
        DeepgramAdapter,
    )

    # Create adapter
    adapter = OpenAIAdapter(api_key="sk-...", model_name="gpt-4o-mini")

    # Execute operation
    result = await adapter.execute(
        Capability.LLM_GENERATION,
        input_data={"messages": [...]},
        temperature=0.7,
    )

    # Result is standardized
    if result.success:
        print(f"Cost: ${result.cost_usd}")
        print(f"Tokens: {result.input_tokens} in, {result.output_tokens} out")
"""

from example_service.infra.ai.capabilities.adapters.accent_redaction import (
    AccentRedactionAdapter,
)
from example_service.infra.ai.capabilities.adapters.anthropic import AnthropicAdapter
from example_service.infra.ai.capabilities.adapters.base import (
    ProviderAdapter,
    TimedExecution,
)
from example_service.infra.ai.capabilities.adapters.deepgram import DeepgramAdapter
from example_service.infra.ai.capabilities.adapters.openai import OpenAIAdapter

__all__ = [
    "AccentRedactionAdapter",
    "AnthropicAdapter",
    "DeepgramAdapter",
    # Adapters
    "OpenAIAdapter",
    # Base
    "ProviderAdapter",
    "TimedExecution",
]
