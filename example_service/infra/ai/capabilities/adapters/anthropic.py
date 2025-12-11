"""Anthropic Claude provider adapter.

Provides LLM capabilities using Anthropic's Claude models:
- Claude 3.5 Sonnet: Premium quality for complex tasks
- Claude 3.5 Haiku: Fast and cost-effective

Features:
- Native structured output via tool_use
- Streaming support
- Extended context windows
- Superior summarization and analysis

Pricing (as of 2025-01):
- Claude 3.5 Sonnet: $3.00/1M input, $15.00/1M output
- Claude 3.5 Haiku: $0.80/1M input, $4.00/1M output
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any, ClassVar

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
from example_service.infra.ai.providers.base import LLMMessage, LLMResponse

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnthropicAdapter(ProviderAdapter):
    """Anthropic Claude adapter for LLM capabilities.

    Capabilities:
        - LLM_GENERATION: Text generation with Claude models
        - LLM_STRUCTURED: Structured output via tool_use
        - LLM_STREAMING: Streaming responses
        - SUMMARIZATION: Optimized for summarization (priority 5)

    Claude is particularly well-suited for:
        - Summarization and analysis
        - Complex reasoning
        - Long-form content generation
        - Following nuanced instructions

    Usage:
        adapter = AnthropicAdapter(
            api_key="sk-ant-...",
            model_name="claude-sonnet-4-5-20250929",
        )

        result = await adapter.execute(
            Capability.LLM_GENERATION,
            {"messages": [{"role": "user", "content": "Summarize this..."}]},
        )
    """

    # Pricing per million tokens (2025-01)
    MODEL_PRICING: ClassVar[dict[str, dict[str, Decimal]]] = {
        "claude-sonnet-4-5-20250929": {
            "input": Decimal("3.00"),
            "output": Decimal("15.00"),
        },
        "claude-3-5-sonnet-20241022": {
            "input": Decimal("3.00"),
            "output": Decimal("15.00"),
        },
        "claude-3-5-haiku-20241022": {
            "input": Decimal("0.80"),
            "output": Decimal("4.00"),
        },
        "claude-3-opus-20240229": {
            "input": Decimal("15.00"),
            "output": Decimal("75.00"),
        },
        "claude-3-sonnet-20240229": {
            "input": Decimal("3.00"),
            "output": Decimal("15.00"),
        },
        "claude-3-haiku-20240307": {
            "input": Decimal("0.25"),
            "output": Decimal("1.25"),
        },
    }

    # Model aliases for convenience
    MODEL_ALIASES: ClassVar[dict[str, str]] = {
        "claude-sonnet": "claude-sonnet-4-5-20250929",
        "claude-haiku": "claude-3-5-haiku-20241022",
        "claude-opus": "claude-3-opus-20240229",
    }

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-sonnet-4-5-20250929",
        timeout: int = 120,
        max_retries: int = 3,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        """Initialize Anthropic adapter.

        Args:
            api_key: Anthropic API key
            model_name: Model to use (or alias like "claude-sonnet")
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            max_tokens: Default max tokens for responses
            **kwargs: Additional adapter-specific options.
        """
        self.api_key = api_key
        # Resolve alias if provided
        self.model_name = self.MODEL_ALIASES.get(model_name, model_name)
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_max_tokens = max_tokens

        # Lazy initialization
        self._client = None

    def _get_client(self) -> Any:
        """Lazy initialize Anthropic client."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic  # type: ignore[import-not-found]

                self._client = AsyncAnthropic(
                    api_key=self.api_key,
                    timeout=self.timeout,
                    max_retries=self.max_retries,
                )
            except ImportError as e:
                msg = (
                    "anthropic package is required for Anthropic provider. "
                    "Install with: pip install anthropic"
                )
                raise ImportError(msg) from e
        return self._client

    def get_registration(self) -> ProviderRegistration:
        """Get provider registration with all capabilities."""
        pricing = self.MODEL_PRICING.get(
            self.model_name,
            {"input": Decimal("3.00"), "output": Decimal("15.00")},
        )

        # Determine quality tier based on model
        if "opus" in self.model_name.lower():
            quality_tier = QualityTier.PREMIUM
            llm_priority = 5
        elif "sonnet" in self.model_name.lower():
            quality_tier = QualityTier.PREMIUM
            llm_priority = 10
        else:  # haiku
            quality_tier = QualityTier.STANDARD
            llm_priority = 30

        return ProviderRegistration(
            provider_name="anthropic",
            provider_type=ProviderType.EXTERNAL,
            capabilities=[
                # General LLM generation
                CapabilityMetadata(
                    capability=Capability.LLM_GENERATION,
                    provider_name="anthropic",
                    cost_per_unit=pricing["input"],
                    output_cost_per_unit=pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=quality_tier,
                    priority=llm_priority,
                    supports_streaming=True,
                    max_input_size=200000,  # 200k context window
                    model_name=self.model_name,
                ),
                # Structured output via tool_use
                CapabilityMetadata(
                    capability=Capability.LLM_STRUCTURED,
                    provider_name="anthropic",
                    cost_per_unit=pricing["input"],
                    output_cost_per_unit=pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=quality_tier,
                    priority=llm_priority,
                    model_name=self.model_name,
                ),
                # Streaming
                CapabilityMetadata(
                    capability=Capability.LLM_STREAMING,
                    provider_name="anthropic",
                    cost_per_unit=pricing["input"],
                    output_cost_per_unit=pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=quality_tier,
                    priority=llm_priority,
                    supports_streaming=True,
                    model_name=self.model_name,
                ),
                # Summarization - Anthropic excels here
                CapabilityMetadata(
                    capability=Capability.SUMMARIZATION,
                    provider_name="anthropic",
                    cost_per_unit=pricing["input"],
                    output_cost_per_unit=pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=QualityTier.PREMIUM,
                    priority=5,  # Highest priority for summarization
                    model_name=self.model_name,
                ),
                # Sentiment analysis
                CapabilityMetadata(
                    capability=Capability.SENTIMENT_ANALYSIS,
                    provider_name="anthropic",
                    cost_per_unit=pricing["input"],
                    output_cost_per_unit=pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=quality_tier,
                    priority=llm_priority,
                    model_name=self.model_name,
                ),
                # Coaching analysis
                CapabilityMetadata(
                    capability=Capability.COACHING_ANALYSIS,
                    provider_name="anthropic",
                    cost_per_unit=pricing["input"],
                    output_cost_per_unit=pricing["output"],
                    cost_unit=CostUnit.PER_1M_TOKENS,
                    quality_tier=quality_tier,
                    priority=llm_priority,
                    model_name=self.model_name,
                ),
            ],
            requires_api_key=True,
            documentation_url="https://docs.anthropic.com/claude/reference",
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
        # All capabilities route to LLM generation (with different prompts)
        if capability in (
            Capability.LLM_GENERATION,
            Capability.LLM_STREAMING,
            Capability.SUMMARIZATION,
            Capability.SENTIMENT_ANALYSIS,
            Capability.COACHING_ANALYSIS,
        ):
            return await self._execute_generation(capability, input_data, **options)
        if capability == Capability.LLM_STRUCTURED:
            return await self._execute_structured(input_data, **options)
        return self._create_error_result(
            capability,
            f"Unsupported capability: {capability}",
            error_code="UNSUPPORTED_CAPABILITY",
            retryable=False,
        )

    async def _execute_generation(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute text generation.

        Expected input_data:
            messages: List of message dicts with role/content
            system: Optional system message

        Options:
            temperature: float (0.0-1.0)
            max_tokens: int
        """
        async with TimedExecution() as timer:
            try:
                messages = input_data.get("messages", [])
                if not messages:
                    return self._create_error_result(
                        capability,
                        "No messages provided",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                # Extract system message if present
                system_message = input_data.get("system")
                anthropic_messages = []

                for msg in messages:
                    if isinstance(msg, LLMMessage):
                        role = msg.role
                        content = msg.content
                    else:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")

                    # Handle system messages
                    if role == "system":
                        system_message = content
                    else:
                        # Anthropic uses "user" and "assistant" roles
                        anthropic_messages.append({
                            "role": role if role in ("user", "assistant") else "user",
                            "content": content,
                        })

                client = self._get_client()

                # Build request params
                params = {
                    "model": self.model_name,
                    "max_tokens": options.get("max_tokens", self.default_max_tokens),
                    "messages": anthropic_messages,
                }

                if system_message:
                    params["system"] = system_message

                if "temperature" in options:
                    params["temperature"] = options["temperature"]

                # Make API call
                response = await client.messages.create(**params)

                # Extract content
                content = ""
                if response.content:
                    for block in response.content:
                        if hasattr(block, "text"):
                            content += block.text

                # Build usage metrics
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }

                # Build LLMResponse for compatibility
                llm_response = LLMResponse(
                    content=content,
                    model=response.model,
                    usage=usage,
                    finish_reason=response.stop_reason,
                    provider_metadata={"id": response.id},
                )

                return self._create_success_result(
                    capability,
                    data=llm_response,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                    request_id=response.id,
                )

            except Exception as e:
                logger.exception(f"Anthropic generation failed: {e}")
                return self._create_error_result(
                    capability,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    async def _execute_structured(
        self,
        input_data: dict[str, Any],
        **options: Any,
    ) -> OperationResult:
        """Execute structured output generation via tool_use.

        Expected input_data:
            messages: List of message dicts
            response_model: Pydantic model class for structured output
            system: Optional system message
        """
        async with TimedExecution() as timer:
            try:
                messages = input_data.get("messages", [])
                response_model: type[BaseModel] | None = input_data.get(
                    "response_model",
                )
                system_message = input_data.get("system")

                if not messages or not response_model:
                    return self._create_error_result(
                        Capability.LLM_STRUCTURED,
                        "Both messages and response_model are required",
                        error_code="INVALID_INPUT",
                        retryable=False,
                    )

                # Build tool from Pydantic model
                tool_name = response_model.__name__.lower()
                tool_schema = response_model.model_json_schema()

                # Remove $defs and resolve refs for Anthropic compatibility
                if "$defs" in tool_schema:
                    # Simple ref resolution for common cases
                    tool_schema = self._resolve_schema_refs(tool_schema)

                tool = {
                    "name": tool_name,
                    "description": f"Generate a structured {response_model.__name__} response",
                    "input_schema": tool_schema,
                }

                # Prepare messages
                anthropic_messages = []
                for msg in messages:
                    if isinstance(msg, LLMMessage):
                        role = msg.role
                        content = msg.content
                    else:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")

                    if role == "system":
                        system_message = content
                    else:
                        anthropic_messages.append({
                            "role": role if role in ("user", "assistant") else "user",
                            "content": content,
                        })

                client = self._get_client()

                # Build request params
                params = {
                    "model": self.model_name,
                    "max_tokens": options.get("max_tokens", self.default_max_tokens),
                    "messages": anthropic_messages,
                    "tools": [tool],
                    "tool_choice": {"type": "tool", "name": tool_name},
                }

                if system_message:
                    params["system"] = system_message

                # Make API call
                response = await client.messages.create(**params)

                # Extract tool use result
                result_data = None
                for block in response.content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        result_data = block.input
                        break

                if result_data is None:
                    return self._create_error_result(
                        Capability.LLM_STRUCTURED,
                        "No structured output returned",
                        error_code="INVALID_RESPONSE",
                        retryable=True,
                    )

                # Parse into Pydantic model
                parsed_result = response_model.model_validate(result_data)

                # Build usage metrics
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }

                return self._create_success_result(
                    Capability.LLM_STRUCTURED,
                    data=parsed_result,
                    usage=usage,
                    latency_ms=timer.elapsed_ms,
                    request_id=response.id,
                )

            except Exception as e:
                logger.exception(f"Anthropic structured generation failed: {e}")
                return self._create_error_result(
                    Capability.LLM_STRUCTURED,
                    str(e),
                    error_code=self._get_error_code(e),
                    retryable=self._is_retryable_error(e),
                    latency_ms=timer.elapsed_ms,
                )

    def _resolve_schema_refs(self, schema: dict) -> dict:
        """Resolve $ref references in JSON schema for Anthropic compatibility.

        Simple implementation that handles common cases.
        """
        if "$defs" not in schema:
            return schema

        defs = schema.pop("$defs")

        def resolve(obj: Any) -> Any:
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref_path = obj["$ref"]
                    # Handle #/$defs/ModelName format
                    if ref_path.startswith("#/$defs/"):
                        def_name = ref_path.split("/")[-1]
                        if def_name in defs:
                            return resolve(defs[def_name])
                    return obj
                return {k: resolve(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [resolve(item) for item in obj]
            return obj

        return resolve(schema)  # type: ignore[no-any-return]

    async def health_check(self) -> bool:
        """Check if Anthropic API is accessible."""
        try:
            client = self._get_client()
            await client.messages.create(
                model=self.model_name,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception as e:
            logger.warning(f"Anthropic health check failed: {e}")
            return False

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if error is retryable for Anthropic."""
        error_str = str(error).lower()

        # Anthropic-specific retryable errors
        retryable_patterns = [
            "rate_limit",
            "overloaded",
            "service_unavailable",
            "timeout",
            "connection",
            "529",  # Overloaded
            "529",
            "503",
            "504",
        ]

        return any(pattern in error_str for pattern in retryable_patterns)
