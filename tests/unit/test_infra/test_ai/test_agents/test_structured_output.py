"""Tests for the AI agent structured output module."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
import pytest

from example_service.infra.ai.agents.structured_output import (
    ExtractionResult,
    ExtractionStrategy,
    RetryConfig,
    StructuredOutputExtractor,
    StructuredOutputParser,
    create_response_model,
    extract_structured,
    validate_output,
)


# Test models
class Person(BaseModel):
    """Test model for a person."""

    name: str
    age: int
    email: str | None = None


class MovieReview(BaseModel):
    """Test model for movie review."""

    title: str
    rating: float = Field(ge=0, le=10)
    summary: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class TestExtractionResult:
    """Tests for ExtractionResult."""

    def test_successful_result(self) -> None:
        """Test creating successful result."""
        result = ExtractionResult[Person](
            success=True,
            data=Person(name="John", age=30),
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "John"
        assert result.error is None

    def test_failed_result(self) -> None:
        """Test creating failed result."""
        result = ExtractionResult[Person](
            success=False,
            error="Failed to parse",
            validation_errors=[{"loc": ("age",), "msg": "must be integer"}],
        )

        assert result.success is False
        assert result.data is None
        assert result.error == "Failed to parse"
        assert len(result.validation_errors) == 1

    def test_result_with_cost_tracking(self) -> None:
        """Test result with cost tracking."""
        result = ExtractionResult[Person](
            success=True,
            data=Person(name="Jane", age=25),
            attempts=2,
            total_tokens=500,
            total_cost_usd=Decimal("0.015"),
        )

        assert result.attempts == 2
        assert result.total_tokens == 500
        assert result.total_cost_usd == Decimal("0.015")


class TestStructuredOutputParser:
    """Tests for StructuredOutputParser."""

    def test_get_json_schema(self) -> None:
        """Test getting JSON schema."""
        parser = StructuredOutputParser(Person)

        schema = parser.get_json_schema()

        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]

    def test_get_function_schema(self) -> None:
        """Test getting function calling schema."""
        parser = StructuredOutputParser(Person)

        schema = parser.get_function_schema()

        assert schema["name"] == "extract_person"
        assert "parameters" in schema
        assert "description" in schema

    def test_get_system_prompt(self) -> None:
        """Test getting system prompt."""
        parser = StructuredOutputParser(Person)

        prompt = parser.get_system_prompt()

        assert "JSON" in prompt
        assert "name" in prompt
        assert "age" in prompt

    def test_parse_valid_json(self) -> None:
        """Test parsing valid JSON response."""
        parser = StructuredOutputParser(Person)
        response = '{"name": "John", "age": 30}'

        result = parser.parse(response)

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "John"
        assert result.data.age == 30

    def test_parse_markdown_json(self) -> None:
        """Test parsing JSON in markdown code block."""
        parser = StructuredOutputParser(Person)
        response = """Here's the extracted data:

```json
{
    "name": "Jane",
    "age": 25
}
```

That's the person's information."""

        result = parser.parse(response)

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Jane"

    def test_parse_inline_json(self) -> None:
        """Test parsing inline JSON."""
        parser = StructuredOutputParser(Person)
        response = 'The person is {"name": "Bob", "age": 40} and they live in NYC.'

        result = parser.parse(response)

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Bob"

    def test_parse_invalid_json(self) -> None:
        """Test parsing invalid JSON."""
        parser = StructuredOutputParser(Person)
        response = "This is not JSON at all"

        result = parser.parse(response)

        assert result.success is False
        assert result.error is not None

    def test_parse_validation_error(self) -> None:
        """Test handling validation errors."""
        parser = StructuredOutputParser(Person)
        response = '{"name": "John", "age": "not a number"}'

        result = parser.parse(response)

        assert result.success is False
        assert len(result.validation_errors) > 0

    def test_parse_function_call_dict(self) -> None:
        """Test parsing function call arguments (dict)."""
        parser = StructuredOutputParser(Person)
        arguments = {"name": "Alice", "age": 28}

        result = parser.parse_function_call(arguments)

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Alice"
        assert result.strategy_used == ExtractionStrategy.FUNCTION_CALLING

    def test_parse_function_call_string(self) -> None:
        """Test parsing function call arguments (JSON string)."""
        parser = StructuredOutputParser(Person)
        arguments = '{"name": "Charlie", "age": 35}'

        result = parser.parse_function_call(arguments)

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Charlie"

    def test_parse_with_optional_field(self) -> None:
        """Test parsing with optional fields."""
        parser = StructuredOutputParser(Person)
        response = '{"name": "John", "age": 30, "email": "john@example.com"}'

        result = parser.parse(response)

        assert result.success is True
        assert result.data is not None
        assert result.data.email == "john@example.com"

    def test_parse_with_missing_optional(self) -> None:
        """Test parsing without optional fields."""
        parser = StructuredOutputParser(Person)
        response = '{"name": "John", "age": 30}'

        result = parser.parse(response)

        assert result.success is True
        assert result.data is not None
        assert result.data.email is None


class TestStructuredOutputExtractor:
    """Tests for StructuredOutputExtractor."""

    async def mock_llm_call(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mock LLM call that returns JSON."""
        return {
            "content": '{"name": "Test User", "age": 25}',
            "usage": {"total_tokens": 100},
            "cost": 0.001,
        }

    async def mock_llm_call_markdown(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mock LLM call that returns markdown JSON."""
        return {
            "content": '```json\n{"name": "Test User", "age": 25}\n```',
            "usage": {"total_tokens": 100},
        }

    async def mock_llm_call_invalid(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mock LLM call that returns invalid JSON."""
        return {
            "content": "Sorry, I can't help with that.",
            "usage": {"total_tokens": 50},
        }

    @pytest.mark.anyio
    async def test_extract_success(self) -> None:
        """Test successful extraction."""
        extractor = StructuredOutputExtractor(
            response_model=Person,
            llm_call=self.mock_llm_call,
        )

        result = await extractor.extract(
            messages=[{"role": "user", "content": "Extract person info"}]
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Test User"
        assert result.total_tokens == 100

    @pytest.mark.anyio
    async def test_extract_with_retry(self) -> None:
        """Test extraction with retry."""
        call_count = 0

        async def flaky_llm(
            messages: list[dict[str, Any]], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return {"content": "invalid", "usage": {"total_tokens": 10}}
            return {
                "content": '{"name": "Success", "age": 30}',
                "usage": {"total_tokens": 100},
            }

        extractor = StructuredOutputExtractor(
            response_model=Person,
            llm_call=flaky_llm,
            retry_config=RetryConfig(max_retries=3),
        )

        result = await extractor.extract(
            messages=[{"role": "user", "content": "Extract"}]
        )

        assert result.success is True
        assert result.attempts == 2
        assert call_count == 2

    @pytest.mark.anyio
    async def test_extract_max_retries_exceeded(self) -> None:
        """Test extraction fails after max retries."""
        extractor = StructuredOutputExtractor(
            response_model=Person,
            llm_call=self.mock_llm_call_invalid,
            retry_config=RetryConfig(max_retries=2),
        )

        result = await extractor.extract(
            messages=[{"role": "user", "content": "Extract"}]
        )

        assert result.success is False
        assert result.attempts == 2

    @pytest.mark.anyio
    async def test_extract_with_function_calling(self) -> None:
        """Test extraction with function calling strategy."""

        async def function_llm(
            messages: list[dict[str, Any]], **kwargs: Any
        ) -> dict[str, Any]:
            # Check that tools were passed
            assert "tools" in kwargs
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "extract_person",
                            "arguments": '{"name": "Function User", "age": 35}',
                        }
                    }
                ],
                "usage": {"total_tokens": 150},
            }

        extractor = StructuredOutputExtractor(
            response_model=Person,
            llm_call=function_llm,
            strategy=ExtractionStrategy.FUNCTION_CALLING,
        )

        result = await extractor.extract(
            messages=[{"role": "user", "content": "Extract"}]
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Function User"


class TestExtractStructured:
    """Tests for the extract_structured convenience function."""

    @pytest.mark.anyio
    async def test_simple_extraction(self) -> None:
        """Test simple extraction."""

        async def llm_call(
            messages: list[dict[str, Any]], **kwargs: Any
        ) -> dict[str, Any]:
            return {
                "content": '{"name": "Quick", "age": 22}',
                "usage": {"total_tokens": 50},
            }

        result = await extract_structured(
            response_model=Person,
            messages=[{"role": "user", "content": "Extract"}],
            llm_call=llm_call,
        )

        assert result.success is True
        assert result.data is not None
        assert result.data.name == "Quick"


class TestValidateOutput:
    """Tests for the validate_output decorator."""

    @pytest.mark.anyio
    async def test_validate_dict_output(self) -> None:
        """Test validating dict output."""

        @validate_output(Person)
        async def get_person() -> dict[str, Any]:
            return {"name": "Decorated", "age": 40}

        result = await get_person()

        assert isinstance(result, Person)
        assert result.name == "Decorated"

    @pytest.mark.anyio
    async def test_validate_model_output(self) -> None:
        """Test validating model output (passthrough)."""

        @validate_output(Person)
        async def get_person() -> Person:
            return Person(name="Direct", age=45)

        result = await get_person()

        assert isinstance(result, Person)
        assert result.name == "Direct"

    @pytest.mark.anyio
    async def test_validate_string_output(self) -> None:
        """Test validating string output (JSON parsing)."""

        @validate_output(Person)
        async def get_person() -> str:
            return '{"name": "Parsed", "age": 50}'

        result = await get_person()

        assert isinstance(result, Person)
        assert result.name == "Parsed"

    @pytest.mark.anyio
    async def test_validate_invalid_string_raises(self) -> None:
        """Test that invalid string raises error."""

        @validate_output(Person)
        async def get_person() -> str:
            return "not json"

        with pytest.raises(ValueError, match="Failed to parse"):
            await get_person()

    @pytest.mark.anyio
    async def test_validate_wrong_type_raises(self) -> None:
        """Test that wrong type raises error."""

        @validate_output(Person)
        async def get_person() -> int:
            return 123

        with pytest.raises(TypeError, match="Expected Person"):
            await get_person()


class TestCreateResponseModel:
    """Tests for the create_response_model function."""

    def test_create_simple_model(self) -> None:
        """Test creating simple model."""
        Model = create_response_model(
            "SearchResult",
            {
                "title": (str, ...),
                "url": (str, ...),
            },
        )

        instance = Model(title="Test", url="http://example.com")

        assert instance.title == "Test"
        assert instance.url == "http://example.com"

    def test_create_model_with_defaults(self) -> None:
        """Test creating model with default values."""
        Model = create_response_model(
            "SearchResult",
            {
                "title": (str, ...),
                "score": (float, 0.0),
            },
        )

        instance = Model(title="Test")

        assert instance.title == "Test"
        assert instance.score == 0.0

    def test_create_model_with_description(self) -> None:
        """Test creating model with description."""
        Model = create_response_model(
            "SearchResult",
            {"title": (str, ...)},
            description="A search result",
        )

        assert Model.__doc__ == "A search result"


class TestExtractionStrategy:
    """Tests for ExtractionStrategy enum."""

    def test_strategy_values(self) -> None:
        """Test strategy enum values."""
        assert ExtractionStrategy.JSON_MODE.value == "json_mode"
        assert ExtractionStrategy.FUNCTION_CALLING.value == "function_calling"
        assert ExtractionStrategy.MARKDOWN_JSON.value == "markdown_json"
        assert ExtractionStrategy.INLINE_JSON.value == "inline_json"
        assert ExtractionStrategy.AUTO.value == "auto"


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert config.include_error_in_prompt is True
        assert config.include_raw_response is True
        assert config.self_correction_prompt is None

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = RetryConfig(
            max_retries=5,
            include_error_in_prompt=False,
            self_correction_prompt="Please fix the JSON",
        )

        assert config.max_retries == 5
        assert config.include_error_in_prompt is False
        assert config.self_correction_prompt == "Please fix the JSON"
