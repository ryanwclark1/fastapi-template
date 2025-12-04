"""Anthropic Claude provider implementation for LLM.

Provides:
- AnthropicProvider: Claude models for text generation
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
)

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseProvider):
    """Anthropic Claude LLM provider.

    Supports:
    - Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku models
    - Structured output via tool use
    - Streaming responses
    - Extended context windows (up to 200K tokens)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "claude-sonnet-4-20250514",
        timeout: int = 120,
        max_retries: int = 3,
        max_tokens: int = 4096,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize Anthropic LLM provider.

        Args:
            api_key: Anthropic API key
            model_name: Model to use (claude-sonnet-4-20250514, claude-3-opus-20240229, etc.)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            max_tokens: Default maximum tokens to generate
            **kwargs: Additional arguments
        """
        super().__init__(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model_name = model_name
        self.default_max_tokens = max_tokens
        self._validate_api_key()

        try:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        except ImportError as e:
            raise ImportError(
                "anthropic package is required for Anthropic provider. "
                "Install with: pip install anthropic"
            ) from e

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "anthropic"

    async def generate(
        self,
        messages: list[LLMMessage] | list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate text completion using Anthropic API.

        Args:
            messages: Conversation history
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional Anthropic parameters

        Returns:
            LLMResponse with generated text

        Raises:
            ProviderError: If generation fails
        """
        try:
            # Extract system message if present
            system_content: str | None = None
            conversation_messages: list[dict[str, str]] = []

            for msg in messages:
                if isinstance(msg, LLMMessage):
                    role = msg.role
                    content = msg.content
                elif isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                else:
                    role = getattr(msg, "role", "user")
                    content = getattr(msg, "content", str(msg))

                if role == "system":
                    system_content = content
                else:
                    # Anthropic uses "user" and "assistant" roles
                    anthropic_role = "assistant" if role == "assistant" else "user"
                    conversation_messages.append({
                        "role": anthropic_role,
                        "content": content,
                    })

            # Ensure conversation starts with user message (Anthropic requirement)
            if conversation_messages and conversation_messages[0]["role"] != "user":
                conversation_messages.insert(0, {
                    "role": "user",
                    "content": "Hello",
                })

            # Build request parameters
            request_params: dict[str, Any] = {
                "model": self.model_name,
                "messages": conversation_messages,
                "temperature": temperature,
                "max_tokens": max_tokens or self.default_max_tokens,
            }

            if system_content:
                request_params["system"] = system_content

            # Add any additional kwargs
            request_params.update(kwargs)

            # Call Anthropic API
            response = await self.client.messages.create(**request_params)

            # Extract response content
            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            # Build usage info
            usage = None
            if response.usage:
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                }

            return LLMResponse(
                content=content,
                model=response.model,
                usage=usage,
                finish_reason=response.stop_reason,
                provider_metadata={"id": response.id},
            )

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "authentication" in error_msg.lower() or "api_key" in error_msg.lower():
                raise ProviderAuthenticationError(
                    "Invalid Anthropic API key",
                    provider="anthropic",
                    operation="llm_generation",
                    original_error=e,
                ) from e

            raise ProviderError(
                f"Anthropic generation failed: {error_msg}",
                provider="anthropic",
                operation="llm_generation",
                original_error=e,
            ) from e

    async def generate_structured(
        self,
        messages: list[LLMMessage] | list[dict[str, str]],
        response_model: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Generate structured output using tool use.

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
            import instructor

            # Patch client with instructor
            client = instructor.from_anthropic(self.client)

            # Extract system message
            system_content: str | None = None
            conversation_messages: list[dict[str, str]] = []

            for msg in messages:
                if isinstance(msg, LLMMessage):
                    role = msg.role
                    content = msg.content
                else:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")

                if role == "system":
                    system_content = content
                else:
                    anthropic_role = "assistant" if role == "assistant" else "user"
                    conversation_messages.append({
                        "role": anthropic_role,
                        "content": content,
                    })

            # Build request
            request_params: dict[str, Any] = {
                "model": self.model_name,
                "messages": conversation_messages,
                "response_model": response_model,
                "max_tokens": kwargs.pop("max_tokens", self.default_max_tokens),
            }

            if system_content:
                request_params["system"] = system_content

            request_params.update(kwargs)

            # Generate with structured output
            result = await client.messages.create(**request_params)

            return result  # type: ignore[no-any-return]

        except ImportError as e:
            raise ImportError(
                "instructor package is required for structured output. "
                "Install with: pip install instructor"
            ) from e
        except Exception as e:
            raise ProviderError(
                f"Structured generation failed: {e}",
                provider="anthropic",
                operation="structured_generation",
                original_error=e,
            ) from e

    def supports_streaming(self) -> bool:
        """Check if provider supports streaming."""
        return True

    def get_model_name(self) -> str:
        """Get the model name being used."""
        return self.model_name
