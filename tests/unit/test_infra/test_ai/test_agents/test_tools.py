"""Tests for the AI agent tool framework."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from example_service.infra.ai.agents.tools import (
    BaseTool,
    FunctionTool,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    get_tool_registry,
    reset_tool_registry,
    tool,
)


class TestToolResult:
    """Tests for ToolResult."""

    def test_success_result(self) -> None:
        """Test creating a success result."""
        result = ToolResult.success(data={"answer": 42})

        assert result.status == ToolResultStatus.SUCCESS
        assert result.data == {"answer": 42}
        assert result.error is None
        assert result.is_success is True
        assert result.is_failure is False

    def test_failure_result(self) -> None:
        """Test creating a failure result."""
        result = ToolResult.failure(error="Something went wrong", error_code="ERR001")

        assert result.status == ToolResultStatus.FAILURE
        assert result.error == "Something went wrong"
        assert result.error_code == "ERR001"
        assert result.is_success is False
        assert result.is_failure is True

    def test_partial_result(self) -> None:
        """Test creating a partial success result."""
        result = ToolResult.partial(
            data={"partial": True},
            error="Some items failed",
        )

        assert result.status == ToolResultStatus.PARTIAL
        assert result.data == {"partial": True}
        assert result.error == "Some items failed"

    def test_timeout_result(self) -> None:
        """Test creating a timeout result."""
        result = ToolResult.timeout()

        assert result.status == ToolResultStatus.TIMEOUT
        assert result.error_code == "timeout"

    def test_to_dict(self) -> None:
        """Test converting result to dictionary."""
        result = ToolResult.success(data={"test": True})
        d = result.to_dict()

        assert d["status"] == "success"
        assert d["data"] == {"test": True}
        assert "timestamp" in d

    def test_to_message_content_success(self) -> None:
        """Test converting success result to message content."""
        result = ToolResult.success(data={"key": "value"})
        content = result.to_message_content()

        assert "key" in content
        assert "value" in content

    def test_to_message_content_failure(self) -> None:
        """Test converting failure result to message content."""
        result = ToolResult.failure(error="Test error")
        content = result.to_message_content()

        assert "Error: Test error" == content


class TestBaseTool:
    """Tests for BaseTool."""

    def test_tool_requires_name(self) -> None:
        """Test that tool requires name."""

        class NoNameTool(BaseTool):
            description = "Test tool"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        with pytest.raises(ValueError, match="name"):
            NoNameTool()

    def test_tool_requires_description(self) -> None:
        """Test that tool requires description."""

        class NoDescTool(BaseTool):
            name = "test_tool"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        with pytest.raises(ValueError, match="description"):
            NoDescTool()

    def test_tool_definition_generation(self) -> None:
        """Test generating tool definition."""

        class SampleTool(BaseTool):
            name = "sample_tool"
            description = "A sample tool for testing"

            class InputSchema(BaseModel):
                query: str
                limit: int = 10

            async def execute(
                self, query: str, limit: int = 10
            ) -> ToolResult[dict[str, object]]:
                return ToolResult.success(data={"query": query, "limit": limit})

        tool = SampleTool()
        definition = tool.get_definition()

        assert definition.name == "sample_tool"
        assert definition.description == "A sample tool for testing"
        assert "query" in definition.parameters.get("properties", {})
        assert "limit" in definition.parameters.get("properties", {})
        assert "query" in definition.parameters.get("required", [])

    def test_openai_format(self) -> None:
        """Test converting to OpenAI format."""

        class TestTool(BaseTool):
            name = "test"
            description = "Test tool"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        tool_instance = TestTool()
        definition = tool_instance.get_definition()
        openai_format = definition.to_openai_format()

        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "test"
        assert openai_format["function"]["description"] == "Test tool"

    def test_anthropic_format(self) -> None:
        """Test converting to Anthropic format."""

        class TestTool(BaseTool):
            name = "test"
            description = "Test tool"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        tool_instance = TestTool()
        definition = tool_instance.get_definition()
        anthropic_format = definition.to_anthropic_format()

        assert anthropic_format["name"] == "test"
        assert anthropic_format["description"] == "Test tool"
        assert "input_schema" in anthropic_format

    @pytest.mark.anyio
    async def test_tool_validate_input(self) -> None:
        """Test input validation."""

        class ValidatedTool(BaseTool):
            name = "validated"
            description = "Validated tool"

            class InputSchema(BaseModel):
                value: int

            async def execute(self, value: int) -> ToolResult[int]:
                return ToolResult.success(data=value * 2)

        tool_instance = ValidatedTool()
        validated = tool_instance.validate_input(value=5)

        assert validated["value"] == 5

    @pytest.mark.anyio
    async def test_tool_callable(self) -> None:
        """Test calling tool directly."""

        class CallableTool(BaseTool):
            name = "callable"
            description = "Callable tool"

            async def execute(self, x: int = 1) -> ToolResult[int]:
                return ToolResult.success(data=x * 2)

        tool_instance = CallableTool()
        result = await tool_instance(x=5)

        assert result.is_success
        assert result.data == 10


class TestFunctionTool:
    """Tests for FunctionTool (decorator-based tools)."""

    @pytest.mark.anyio
    async def test_tool_decorator(self) -> None:
        """Test creating tool with decorator."""

        @tool(name="greet", description="Greet a person")
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        assert isinstance(greet, FunctionTool)
        assert greet.name == "greet"
        assert greet.description == "Greet a person"

        result = await greet(name="World")
        assert result.is_success
        assert result.data == "Hello, World!"

    @pytest.mark.anyio
    async def test_tool_decorator_default_name(self) -> None:
        """Test decorator uses function name as default."""

        @tool(description="Add two numbers")
        async def add_numbers(a: int, b: int) -> int:
            return a + b

        assert add_numbers.name == "add_numbers"

        result = await add_numbers(a=2, b=3)
        assert result.data == 5

    @pytest.mark.anyio
    async def test_tool_decorator_returns_toolresult(self) -> None:
        """Test decorator handles ToolResult returns."""

        @tool(description="Divide numbers")
        async def divide(a: float, b: float) -> ToolResult[float]:
            if b == 0:
                return ToolResult.failure(error="Division by zero")
            return ToolResult.success(data=a / b)

        result = await divide(a=10, b=2)
        assert result.is_success
        assert result.data == 5.0

        result = await divide(a=10, b=0)
        assert result.is_failure
        assert "Division by zero" in str(result.error)

    @pytest.mark.anyio
    async def test_tool_decorator_handles_exceptions(self) -> None:
        """Test decorator handles exceptions gracefully."""

        @tool(description="Failing tool")
        async def failing_tool() -> None:
            raise ValueError("Intentional error")

        result = await failing_tool()
        assert result.is_failure
        assert "Intentional error" in str(result.error)


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        reset_tool_registry()

    def test_register_tool(self) -> None:
        """Test registering a tool."""

        class TestTool(BaseTool):
            name = "test_tool"
            description = "Test tool"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TestTool())

        assert "test_tool" in registry
        assert len(registry) == 1

    def test_register_duplicate_raises(self) -> None:
        """Test registering duplicate tool raises error."""

        class TestTool(BaseTool):
            name = "duplicate"
            description = "Test"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TestTool())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(TestTool())

    def test_get_tool(self) -> None:
        """Test getting a tool by name."""

        class TestTool(BaseTool):
            name = "my_tool"
            description = "Test"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        tool_instance = TestTool()
        registry.register(tool_instance)

        retrieved = registry.get("my_tool")
        assert retrieved is tool_instance

        missing = registry.get("nonexistent")
        assert missing is None

    def test_get_required_tool(self) -> None:
        """Test getting required tool raises on missing."""
        registry = ToolRegistry()

        with pytest.raises(KeyError, match="not found"):
            registry.get_required("missing_tool")

    def test_unregister_tool(self) -> None:
        """Test unregistering a tool."""

        class TestTool(BaseTool):
            name = "removable"
            description = "Test"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TestTool())
        assert "removable" in registry

        registry.unregister("removable")
        assert "removable" not in registry

    def test_list_tools(self) -> None:
        """Test listing all tools."""

        class Tool1(BaseTool):
            name = "tool1"
            description = "Tool 1"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        class Tool2(BaseTool):
            name = "tool2"
            description = "Tool 2"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(Tool1())
        registry.register(Tool2())

        names = registry.list_names()
        assert "tool1" in names
        assert "tool2" in names

    def test_list_by_tag(self) -> None:
        """Test listing tools by tag."""

        class TaggedTool(BaseTool):
            name = "tagged"
            description = "Tagged tool"
            tags = ["search", "web"]

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        class UntaggedTool(BaseTool):
            name = "untagged"
            description = "Untagged tool"
            tags: list[str] = []

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TaggedTool())
        registry.register(UntaggedTool())

        search_tools = registry.list_by_tag("search")
        assert len(search_tools) == 1
        assert search_tools[0].name == "tagged"

    def test_get_definitions(self) -> None:
        """Test getting all tool definitions."""

        class Tool1(BaseTool):
            name = "tool1"
            description = "Tool 1"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        class Tool2(BaseTool):
            name = "tool2"
            description = "Tool 2"
            is_dangerous = True

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(Tool1())
        registry.register(Tool2())

        # All definitions
        all_defs = registry.get_definitions()
        assert len(all_defs) == 2

        # Exclude dangerous
        safe_defs = registry.get_definitions(exclude_dangerous=True)
        assert len(safe_defs) == 1
        assert safe_defs[0].name == "tool1"

    def test_get_openai_tools(self) -> None:
        """Test getting tools in OpenAI format."""

        class TestTool(BaseTool):
            name = "test"
            description = "Test"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TestTool())

        openai_tools = registry.get_openai_tools()
        assert len(openai_tools) == 1
        assert openai_tools[0]["type"] == "function"

    def test_get_anthropic_tools(self) -> None:
        """Test getting tools in Anthropic format."""

        class TestTool(BaseTool):
            name = "test"
            description = "Test"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TestTool())

        anthropic_tools = registry.get_anthropic_tools()
        assert len(anthropic_tools) == 1
        assert "input_schema" in anthropic_tools[0]

    def test_global_registry(self) -> None:
        """Test global registry singleton."""
        reset_tool_registry()

        registry1 = get_tool_registry()
        registry2 = get_tool_registry()

        assert registry1 is registry2

    def test_clear_registry(self) -> None:
        """Test clearing registry."""

        class TestTool(BaseTool):
            name = "test"
            description = "Test"

            async def execute(self, **kwargs: object) -> ToolResult[object]:
                return ToolResult.success()

        registry = ToolRegistry()
        registry.register(TestTool())
        assert len(registry) == 1

        registry.clear()
        assert len(registry) == 0
