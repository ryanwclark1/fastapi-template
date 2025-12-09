"""Structured output enforcement for AI agents.

This module provides Pydantic-based structured output from LLMs:
- Type-safe outputs with validation
- Automatic retry with self-correction
- Multiple extraction strategies (JSON mode, function calling, parsing)
- Support for OpenAI, Anthropic, and other providers

Similar to Pydantic AI and Instructor patterns.

Example:
    from pydantic import BaseModel
    from example_service.infra.ai.agents.structured_output import (
        StructuredOutputParser,
        extract_structured,
    )

    class MovieReview(BaseModel):
        title: str
        rating: float
        summary: str
        pros: list[str]
        cons: list[str]

    # Extract structured data from LLM
    result = await extract_structured(
        model="gpt-4o",
        response_model=MovieReview,
        messages=[{"role": "user", "content": "Review the movie Inception"}],
    )

    print(result.title)  # "Inception"
    print(result.rating)  # 9.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
import json
import logging
import re
from typing import TYPE_CHECKING, Any, Generic, TypeVar, get_type_hints

from pydantic import BaseModel, ValidationError, create_model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ExtractionStrategy(str, Enum):
    """Strategy for extracting structured output."""

    JSON_MODE = "json_mode"  # Use provider's JSON mode
    FUNCTION_CALLING = "function_calling"  # Use function/tool calling
    MARKDOWN_JSON = "markdown_json"  # Parse JSON from markdown code blocks
    INLINE_JSON = "inline_json"  # Parse JSON from response text
    AUTO = "auto"  # Automatically select best strategy


@dataclass
class ExtractionResult(Generic[T]):
    """Result from structured extraction."""

    success: bool
    data: T | None = None
    raw_response: str | None = None
    error: str | None = None
    validation_errors: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 1
    strategy_used: ExtractionStrategy | None = None

    # Cost tracking
    total_tokens: int = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    include_error_in_prompt: bool = True
    include_raw_response: bool = True
    self_correction_prompt: str | None = None


class StructuredOutputParser(Generic[T]):
    """Parser for extracting structured output from LLM responses.

    Supports multiple extraction strategies and automatic retry
    with self-correction on parse failures.

    Example:
        parser = StructuredOutputParser(
            response_model=MovieReview,
            strategy=ExtractionStrategy.AUTO,
        )

        result = parser.parse(llm_response)
        if result.success:
            print(result.data.title)
    """

    def __init__(
        self,
        response_model: type[T],
        strategy: ExtractionStrategy = ExtractionStrategy.AUTO,
        strict: bool = True,
    ) -> None:
        """Initialize parser.

        Args:
            response_model: Pydantic model for output
            strategy: Extraction strategy to use
            strict: Whether to require exact schema match
        """
        self.response_model = response_model
        self.strategy = strategy
        self.strict = strict
        self._schema = response_model.model_json_schema()

    def get_json_schema(self) -> dict[str, Any]:
        """Get JSON schema for the response model."""
        return self._schema

    def get_function_schema(self) -> dict[str, Any]:
        """Get function calling schema for OpenAI/Anthropic."""
        return {
            "name": f"extract_{self.response_model.__name__.lower()}",
            "description": f"Extract {self.response_model.__name__} from the content",
            "parameters": self._schema,
        }

    def get_system_prompt(self) -> str:
        """Get system prompt for JSON extraction."""
        schema_str = json.dumps(self._schema, indent=2)
        return f"""You must respond with valid JSON that matches this schema:

{schema_str}

Important:
- Return ONLY valid JSON, no other text
- All required fields must be present
- Follow the exact types specified in the schema"""

    def parse(self, response: str) -> ExtractionResult[T]:
        """Parse LLM response into structured output.

        Args:
            response: Raw LLM response text

        Returns:
            ExtractionResult with parsed data or errors
        """
        strategies = self._get_strategies()

        for strategy in strategies:
            try:
                json_str = self._extract_json(response, strategy)
                if json_str:
                    data = json.loads(json_str)
                    validated = self.response_model.model_validate(data)
                    return ExtractionResult(
                        success=True,
                        data=validated,
                        raw_response=response,
                        strategy_used=strategy,
                    )
            except json.JSONDecodeError as e:
                logger.debug(f"JSON decode failed with {strategy}: {e}")
                continue
            except ValidationError as e:
                return ExtractionResult(
                    success=False,
                    raw_response=response,
                    error=f"Validation failed: {e}",
                    validation_errors=[err for err in e.errors()],
                    strategy_used=strategy,
                )

        return ExtractionResult(
            success=False,
            raw_response=response,
            error="Failed to extract valid JSON from response",
        )

    def parse_function_call(
        self,
        arguments: str | dict[str, Any],
    ) -> ExtractionResult[T]:
        """Parse function call arguments.

        Args:
            arguments: Function call arguments (JSON string or dict)

        Returns:
            ExtractionResult with parsed data
        """
        try:
            if isinstance(arguments, str):
                data = json.loads(arguments)
            else:
                data = arguments

            validated = self.response_model.model_validate(data)
            return ExtractionResult(
                success=True,
                data=validated,
                raw_response=json.dumps(data) if isinstance(data, dict) else arguments,
                strategy_used=ExtractionStrategy.FUNCTION_CALLING,
            )
        except json.JSONDecodeError as e:
            return ExtractionResult(
                success=False,
                raw_response=arguments if isinstance(arguments, str) else None,
                error=f"Invalid JSON in function arguments: {e}",
            )
        except ValidationError as e:
            return ExtractionResult(
                success=False,
                raw_response=arguments if isinstance(arguments, str) else None,
                error=f"Validation failed: {e}",
                validation_errors=[err for err in e.errors()],
            )

    def _get_strategies(self) -> list[ExtractionStrategy]:
        """Get strategies to try based on configuration."""
        if self.strategy == ExtractionStrategy.AUTO:
            return [
                ExtractionStrategy.MARKDOWN_JSON,
                ExtractionStrategy.INLINE_JSON,
            ]
        return [self.strategy]

    def _extract_json(
        self,
        response: str,
        strategy: ExtractionStrategy,
    ) -> str | None:
        """Extract JSON string from response using strategy."""
        if strategy == ExtractionStrategy.MARKDOWN_JSON:
            return self._extract_markdown_json(response)
        elif strategy == ExtractionStrategy.INLINE_JSON:
            return self._extract_inline_json(response)
        elif strategy == ExtractionStrategy.JSON_MODE:
            # Response should already be JSON
            return response.strip()
        return None

    def _extract_markdown_json(self, response: str) -> str | None:
        """Extract JSON from markdown code blocks."""
        # Try ```json blocks first
        pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        matches = re.findall(pattern, response)

        for match in matches:
            try:
                # Verify it's valid JSON
                json.loads(match.strip())
                return match.strip()
            except json.JSONDecodeError:
                continue

        return None

    def _extract_inline_json(self, response: str) -> str | None:
        """Extract JSON object from inline response."""
        # Try to find JSON object
        # Look for balanced braces
        depth = 0
        start = -1

        for i, char in enumerate(response):
            if char == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    json_str = response[start : i + 1]
                    try:
                        json.loads(json_str)
                        return json_str
                    except json.JSONDecodeError:
                        start = -1
                        continue

        return None


class StructuredOutputExtractor(Generic[T]):
    """High-level extractor with retry and self-correction.

    Handles the full extraction workflow including:
    - Initial extraction attempt
    - Retry with error feedback
    - Self-correction prompts
    - Cost tracking

    Example:
        extractor = StructuredOutputExtractor(
            response_model=MovieReview,
            llm_call=my_llm_function,
            retry_config=RetryConfig(max_retries=3),
        )

        result = await extractor.extract(
            messages=[{"role": "user", "content": "Review Inception"}]
        )
    """

    def __init__(
        self,
        response_model: type[T],
        llm_call: Callable[..., Awaitable[dict[str, Any]]],
        strategy: ExtractionStrategy = ExtractionStrategy.AUTO,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """Initialize extractor.

        Args:
            response_model: Pydantic model for output
            llm_call: Async function to call LLM
            strategy: Extraction strategy
            retry_config: Retry configuration
        """
        self.response_model = response_model
        self.llm_call = llm_call
        self.strategy = strategy
        self.retry_config = retry_config or RetryConfig()
        self._parser = StructuredOutputParser(response_model, strategy)

    async def extract(
        self,
        messages: list[dict[str, Any]],
        **llm_kwargs: Any,
    ) -> ExtractionResult[T]:
        """Extract structured output from LLM.

        Args:
            messages: Conversation messages
            **llm_kwargs: Additional arguments for LLM call

        Returns:
            ExtractionResult with parsed data or errors
        """
        total_tokens = 0
        total_cost = Decimal("0")

        # Prepare messages with system prompt
        extraction_messages = self._prepare_messages(messages)

        for attempt in range(1, self.retry_config.max_retries + 1):
            try:
                # Call LLM
                if self.strategy == ExtractionStrategy.FUNCTION_CALLING:
                    response = await self._call_with_function(
                        extraction_messages, **llm_kwargs
                    )
                else:
                    response = await self._call_for_json(
                        extraction_messages, **llm_kwargs
                    )

                # Track usage
                if "usage" in response:
                    total_tokens += response["usage"].get("total_tokens", 0)
                if "cost" in response:
                    total_cost += Decimal(str(response.get("cost", 0)))

                # Parse response
                if self.strategy == ExtractionStrategy.FUNCTION_CALLING:
                    result = self._parse_function_response(response)
                else:
                    result = self._parser.parse(response.get("content", ""))

                result.attempts = attempt
                result.total_tokens = total_tokens
                result.total_cost_usd = total_cost

                if result.success:
                    return result

                # Prepare retry with error feedback
                if attempt < self.retry_config.max_retries:
                    extraction_messages = self._prepare_retry_messages(
                        extraction_messages, result
                    )

            except Exception as e:
                logger.warning(f"Extraction attempt {attempt} failed: {e}")
                if attempt >= self.retry_config.max_retries:
                    return ExtractionResult(
                        success=False,
                        error=str(e),
                        attempts=attempt,
                        total_tokens=total_tokens,
                        total_cost_usd=total_cost,
                    )

        return ExtractionResult(
            success=False,
            error="Max retries exceeded",
            attempts=self.retry_config.max_retries,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
        )

    def _prepare_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prepare messages with extraction instructions."""
        # Add system prompt if not using function calling
        if self.strategy != ExtractionStrategy.FUNCTION_CALLING:
            system_prompt = self._parser.get_system_prompt()

            # Check if there's already a system message
            has_system = any(m.get("role") == "system" for m in messages)

            if has_system:
                # Append to existing system message
                return [
                    {
                        **m,
                        "content": f"{m['content']}\n\n{system_prompt}"
                        if m.get("role") == "system"
                        else m.get("content"),
                    }
                    for m in messages
                ]
            else:
                # Add new system message
                return [
                    {"role": "system", "content": system_prompt},
                    *messages,
                ]

        return messages

    def _prepare_retry_messages(
        self,
        messages: list[dict[str, Any]],
        failed_result: ExtractionResult[T],
    ) -> list[dict[str, Any]]:
        """Prepare messages for retry with error feedback."""
        correction_prompt = self.retry_config.self_correction_prompt or (
            "The previous response had validation errors. Please fix them and try again."
        )

        error_info = []
        if self.retry_config.include_error_in_prompt and failed_result.error:
            error_info.append(f"Error: {failed_result.error}")

        if failed_result.validation_errors:
            error_details = "\n".join(
                f"- {e.get('loc')}: {e.get('msg')}"
                for e in failed_result.validation_errors
            )
            error_info.append(f"Validation errors:\n{error_details}")

        if self.retry_config.include_raw_response and failed_result.raw_response:
            error_info.append(
                f"Your response was:\n```\n{failed_result.raw_response[:500]}\n```"
            )

        error_message = "\n\n".join(error_info)
        retry_content = f"{correction_prompt}\n\n{error_message}"

        return [
            *messages,
            {"role": "user", "content": retry_content},
        ]

    async def _call_for_json(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call LLM expecting JSON response."""
        # Add JSON mode if supported
        if self.strategy == ExtractionStrategy.JSON_MODE:
            kwargs["response_format"] = {"type": "json_object"}

        return await self.llm_call(messages=messages, **kwargs)

    async def _call_with_function(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call LLM with function calling."""
        function_schema = self._parser.get_function_schema()

        kwargs["tools"] = [
            {
                "type": "function",
                "function": function_schema,
            }
        ]
        kwargs["tool_choice"] = {
            "type": "function",
            "function": {"name": function_schema["name"]},
        }

        return await self.llm_call(messages=messages, **kwargs)

    def _parse_function_response(
        self,
        response: dict[str, Any],
    ) -> ExtractionResult[T]:
        """Parse function call response."""
        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            return ExtractionResult(
                success=False,
                error="No function call in response",
                raw_response=response.get("content"),
            )

        # Get first function call
        call = tool_calls[0]
        if isinstance(call, dict):
            arguments = call.get("function", {}).get("arguments", "{}")
        else:
            arguments = call.function.arguments if hasattr(call, "function") else "{}"

        return self._parser.parse_function_call(arguments)


# Convenience function for simple extraction
async def extract_structured(
    response_model: type[T],
    messages: list[dict[str, Any]],
    llm_call: Callable[..., Awaitable[dict[str, Any]]],
    strategy: ExtractionStrategy = ExtractionStrategy.AUTO,
    max_retries: int = 3,
    **llm_kwargs: Any,
) -> ExtractionResult[T]:
    """Extract structured output from LLM.

    Convenience function for one-off extractions.

    Args:
        response_model: Pydantic model for output
        messages: Conversation messages
        llm_call: Async function to call LLM
        strategy: Extraction strategy
        max_retries: Maximum retry attempts
        **llm_kwargs: Additional LLM arguments

    Returns:
        ExtractionResult with parsed data

    Example:
        class Person(BaseModel):
            name: str
            age: int

        result = await extract_structured(
            response_model=Person,
            messages=[{"role": "user", "content": "Extract: John is 30"}],
            llm_call=my_llm_function,
        )
    """
    extractor = StructuredOutputExtractor(
        response_model=response_model,
        llm_call=llm_call,
        strategy=strategy,
        retry_config=RetryConfig(max_retries=max_retries),
    )
    return await extractor.extract(messages, **llm_kwargs)


# Output validation decorators
def validate_output(response_model: type[T]) -> Callable[..., Any]:
    """Decorator to validate agent output against a Pydantic model.

    Example:
        @validate_output(MovieReview)
        async def analyze_movie(self, title: str) -> MovieReview:
            response = await self.llm_call([...])
            return response  # Will be validated against MovieReview
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            result = await func(*args, **kwargs)

            if isinstance(result, response_model):
                return result

            if isinstance(result, dict):
                return response_model.model_validate(result)

            if isinstance(result, str):
                parser = StructuredOutputParser(response_model)
                extraction = parser.parse(result)
                if extraction.success:
                    return extraction.data  # type: ignore
                raise ValueError(f"Failed to parse output: {extraction.error}")

            raise TypeError(
                f"Expected {response_model.__name__}, got {type(result).__name__}"
            )

        return wrapper

    return decorator


# Schema utilities
def create_response_model(
    name: str,
    fields: dict[str, tuple[type, Any]],
    description: str | None = None,
) -> type[BaseModel]:
    """Dynamically create a response model.

    Args:
        name: Model name
        fields: Dict of field_name -> (type, default)
        description: Optional model description

    Returns:
        Dynamically created Pydantic model

    Example:
        Model = create_response_model(
            "SearchResult",
            {
                "title": (str, ...),
                "url": (str, ...),
                "snippet": (str, ""),
            },
        )
    """
    model = create_model(name, **fields)  # type: ignore
    if description:
        model.__doc__ = description
    return model
