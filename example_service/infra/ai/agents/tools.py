"""Tool framework for AI agents.

This module provides the foundation for tool/function calling:
- BaseTool: Abstract base class for all tools
- ToolRegistry: Central registry for tool discovery
- ToolResult: Standardized result from tool execution
- Built-in tool decorators for easy tool creation

Design Principles:
1. Type-safe: Tools are defined with Pydantic models for inputs
2. Observable: All tool executions are traced and metered
3. Composable: Tools can call other tools
4. Resilient: Built-in retry and error handling

Example:
    from example_service.infra.ai.agents.tools import (
        BaseTool,
        ToolResult,
        tool_registry,
    )

    class WebSearchTool(BaseTool):
        name = "web_search"
        description = "Search the web for information"

        class InputSchema(BaseModel):
            query: str
            max_results: int = 10

        async def execute(self, query: str, max_results: int = 10) -> ToolResult:
            # Perform search
            results = await search_web(query, max_results)
            return ToolResult.success(data=results)

    # Register tool
    tool_registry.register(WebSearchTool())
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import inspect
import logging
from typing import TYPE_CHECKING, Any, TypeVar, get_type_hints

from pydantic import BaseModel, Field, create_model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ToolResultStatus(str, Enum):
    """Status of a tool execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"  # Partial success
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolResult[T]:
    """Result from tool execution.

    Provides a standardized way to return results from tools,
    including success/failure status, data, and error information.

    Examples:
        # Success
        return ToolResult.success(data={"answer": 42})

        # Failure
        return ToolResult.failure(error="Connection timeout")

        # Partial success
        return ToolResult.partial(
            data={"partial_results": [...]},
            error="Some items failed to process"
        )
    """

    status: ToolResultStatus
    data: T | None = None
    error: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def success(
        cls,
        data: T | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult[T]:
        """Create a successful result."""
        return cls(
            status=ToolResultStatus.SUCCESS,
            data=data,
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls,
        error: str,
        error_code: str | None = None,
        data: T | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult[T]:
        """Create a failure result."""
        return cls(
            status=ToolResultStatus.FAILURE,
            error=error,
            error_code=error_code,
            data=data,
            metadata=metadata or {},
        )

    @classmethod
    def partial(
        cls,
        data: T | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult[T]:
        """Create a partial success result."""
        return cls(
            status=ToolResultStatus.PARTIAL,
            data=data,
            error=error,
            metadata=metadata or {},
        )

    @classmethod
    def timeout(
        cls,
        error: str = "Tool execution timed out",
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult[T]:
        """Create a timeout result."""
        return cls(
            status=ToolResultStatus.TIMEOUT,
            error=error,
            error_code="timeout",
            metadata=metadata or {},
        )

    @property
    def is_success(self) -> bool:
        """Check if result is successful."""
        return self.status == ToolResultStatus.SUCCESS

    @property
    def is_failure(self) -> bool:
        """Check if result is a failure."""
        return self.status == ToolResultStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "error_code": self.error_code,
            "metadata": self.metadata,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_message_content(self) -> str:
        """Convert result to string for LLM consumption."""
        if self.is_success:
            if isinstance(self.data, str):
                return self.data
            if isinstance(self.data, dict):
                import json

                return json.dumps(self.data, indent=2, default=str)
            return str(self.data)
        return f"Error: {self.error}"


class ToolParameter(BaseModel):
    """Definition of a tool parameter."""

    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[Any] | None = None


class ToolDefinition(BaseModel):
    """JSON Schema-compatible tool definition.

    This format is compatible with OpenAI function calling
    and Anthropic tool use APIs.
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_format(self) -> dict[str, Any]:
        """Convert to Anthropic tool use format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class BaseTool(ABC):
    """Abstract base class for tools.

    Subclasses must implement:
    - name: Tool name (used in function calls)
    - description: Human-readable description
    - execute(): The actual tool logic

    Optionally define:
    - InputSchema: Pydantic model for input validation
    - timeout_seconds: Execution timeout
    - retry_policy: Retry configuration

    Example:
        class CalculatorTool(BaseTool):
            name = "calculator"
            description = "Perform mathematical calculations"

            class InputSchema(BaseModel):
                expression: str

            async def execute(self, expression: str) -> ToolResult:
                try:
                    result = eval(expression)  # Note: Use safe eval in production
                    return ToolResult.success(data=result)
                except Exception as e:
                    return ToolResult.failure(error=str(e))
    """

    # Required class attributes
    name: str
    description: str

    # Optional class attributes
    InputSchema: type[BaseModel] | None = None
    timeout_seconds: int = 30
    requires_confirmation: bool = False  # Require human confirmation before execution
    is_dangerous: bool = False  # Mark tools that can cause side effects
    tags: list[str] = []

    def __init__(self) -> None:
        """Initialize the tool."""
        if not hasattr(self, "name") or not self.name:
            msg = "Tool must have a name"
            raise ValueError(msg)
        if not hasattr(self, "description") or not self.description:
            msg = "Tool must have a description"
            raise ValueError(msg)

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult[Any]:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool arguments (validated against InputSchema if defined)

        Returns:
            ToolResult with execution outcome
        """

    def validate_input(self, **kwargs: Any) -> dict[str, Any]:
        """Validate input against InputSchema if defined.

        Args:
            **kwargs: Raw input arguments

        Returns:
            Validated and potentially transformed arguments

        Raises:
            ValidationError: If validation fails
        """
        if self.InputSchema is not None:
            validated = self.InputSchema(**kwargs)
            return validated.model_dump()
        return kwargs

    def get_definition(self) -> ToolDefinition:
        """Get JSON Schema definition for this tool.

        Returns:
            ToolDefinition compatible with OpenAI/Anthropic APIs
        """
        parameters: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        if self.InputSchema is not None:
            # Use Pydantic's JSON schema generation
            schema = self.InputSchema.model_json_schema()
            parameters["properties"] = schema.get("properties", {})
            parameters["required"] = schema.get("required", [])
            if "definitions" in schema:
                parameters["definitions"] = schema["definitions"]
        else:
            # Infer from execute method signature
            sig = inspect.signature(self.execute)
            hints = get_type_hints(self.execute)

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "kwargs"):
                    continue

                param_type = hints.get(param_name, Any)
                json_type = self._python_type_to_json(param_type)

                parameters["properties"][param_name] = {
                    "type": json_type,
                }

                if param.default is inspect.Parameter.empty:
                    parameters["required"].append(param_name)

        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=parameters,
        )

    def _python_type_to_json(self, python_type: type) -> str:
        """Convert Python type to JSON Schema type."""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        return type_map.get(python_type, "string")

    async def __call__(self, **kwargs: Any) -> ToolResult[Any]:
        """Make tool callable directly.

        Validates input and calls execute().
        """
        validated = self.validate_input(**kwargs)
        return await self.execute(**validated)

    def __repr__(self) -> str:
        """Return tool summary for debugging."""
        return f"<{self.__class__.__name__}(name={self.name})>"


class FunctionTool(BaseTool):
    """Tool created from a function using decorator.

    This allows creating tools from simple functions without
    defining a full class.

    Example:
        @tool(name="greet", description="Greet a person")
        async def greet(name: str) -> str:
            return f"Hello, {name}!"
    """

    def __init__(
        self,
        func: Callable[..., Awaitable[Any]],
        name: str,
        description: str,
        input_schema: type[BaseModel] | None = None,
        timeout_seconds: int = 30,
        requires_confirmation: bool = False,
        is_dangerous: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.InputSchema = input_schema
        self.timeout_seconds = timeout_seconds
        self.requires_confirmation = requires_confirmation
        self.is_dangerous = is_dangerous
        self.tags = tags or []
        self._func = func
        super().__init__()

    async def execute(self, **kwargs: Any) -> ToolResult[Any]:
        """Execute the wrapped function."""
        try:
            result = await self._func(**kwargs)

            # If function returns ToolResult, use it directly
            if isinstance(result, ToolResult):
                return result

            # Otherwise wrap in success result
            return ToolResult.success(data=result)

        except Exception as e:
            logger.exception(f"Tool {self.name} execution failed")
            return ToolResult.failure(error=str(e))


def tool(
    name: str | None = None,
    description: str | None = None,
    input_schema: type[BaseModel] | None = None,
    timeout_seconds: int = 30,
    requires_confirmation: bool = False,
    is_dangerous: bool = False,
    tags: list[str] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], FunctionTool]:
    """Decorator to create a tool from a function.

    Args:
        name: Tool name (defaults to function name)
        description: Tool description (defaults to function docstring)
        input_schema: Pydantic model for input validation
        timeout_seconds: Execution timeout
        requires_confirmation: Whether to require human confirmation
        is_dangerous: Mark as potentially dangerous
        tags: Tags for categorization

    Example:
        @tool(description="Search the web")
        async def web_search(query: str, max_results: int = 10) -> list[dict]:
            return await perform_search(query, max_results)
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> FunctionTool:
        tool_name = name or func.__name__
        tool_description = description or func.__doc__ or f"Execute {tool_name}"

        # Auto-generate input schema from function signature if not provided
        schema = input_schema
        if schema is None:
            sig = inspect.signature(func)
            hints = get_type_hints(func)
            fields: dict[str, Any] = {}

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "kwargs", "args"):
                    continue

                param_type = hints.get(param_name, Any)
                if param.default is inspect.Parameter.empty:
                    fields[param_name] = (param_type, ...)
                else:
                    fields[param_name] = (param_type, param.default)

            if fields:
                schema = create_model(f"{tool_name.title()}Input", **fields)

        return FunctionTool(
            func=func,
            name=tool_name,
            description=tool_description,
            input_schema=schema,
            timeout_seconds=timeout_seconds,
            requires_confirmation=requires_confirmation,
            is_dangerous=is_dangerous,
            tags=tags,
        )

    return decorator


class ToolRegistry:
    """Central registry for tool management.

    Provides:
    - Tool registration and discovery
    - Tool lookup by name or tags
    - Tool definition export for LLM APIs

    Example:
        registry = ToolRegistry()

        # Register tools
        registry.register(WebSearchTool())
        registry.register(CalculatorTool())

        # Get tool by name
        tool = registry.get("web_search")

        # Get all tool definitions for LLM
        definitions = registry.get_definitions()
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._tags_index: dict[str, set[str]] = {}  # tag -> tool names

    def register(self, tool: BaseTool) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register

        Raises:
            ValueError: If tool with same name already exists
        """
        if tool.name in self._tools:
            msg = f"Tool '{tool.name}' is already registered"
            raise ValueError(msg)

        self._tools[tool.name] = tool

        # Index by tags
        for tag in tool.tags:
            if tag not in self._tags_index:
                self._tags_index[tag] = set()
            self._tags_index[tag].add(tool.name)

        logger.debug(f"Registered tool: {tool.name}")

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        if name in self._tools:
            tool = self._tools[name]
            del self._tools[name]

            # Remove from tags index
            for tag in tool.tags:
                if tag in self._tags_index:
                    self._tags_index[tag].discard(name)

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_required(self, name: str) -> BaseTool:
        """Get a tool by name, raising if not found."""
        tool = self.get(name)
        if tool is None:
            msg = f"Tool '{name}' not found"
            raise KeyError(msg)
        return tool

    def list_all(self) -> list[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())

    def list_by_tag(self, tag: str) -> list[BaseTool]:
        """List tools with a specific tag."""
        names = self._tags_index.get(tag, set())
        return [self._tools[name] for name in names if name in self._tools]

    def get_definitions(
        self,
        names: list[str] | None = None,
        exclude_dangerous: bool = False,
    ) -> list[ToolDefinition]:
        """Get tool definitions for LLM API.

        Args:
            names: Specific tool names to include (None = all)
            exclude_dangerous: Whether to exclude dangerous tools

        Returns:
            List of ToolDefinition objects
        """
        definitions = []

        tools = (
            [self._tools[n] for n in names if n in self._tools]
            if names
            else self._tools.values()
        )

        for tool in tools:
            if exclude_dangerous and tool.is_dangerous:
                continue
            definitions.append(tool.get_definition())

        return definitions

    def get_openai_tools(
        self,
        names: list[str] | None = None,
        exclude_dangerous: bool = False,
    ) -> list[dict[str, Any]]:
        """Get tools in OpenAI function calling format."""
        return [
            d.to_openai_format() for d in self.get_definitions(names, exclude_dangerous)
        ]

    def get_anthropic_tools(
        self,
        names: list[str] | None = None,
        exclude_dangerous: bool = False,
    ) -> list[dict[str, Any]]:
        """Get tools in Anthropic tool use format."""
        return [
            d.to_anthropic_format()
            for d in self.get_definitions(names, exclude_dangerous)
        ]

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._tags_index.clear()

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Return True if a tool with the given name exists."""
        return name in self._tools


# Global registry singleton
_global_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_tool_registry() -> None:
    """Reset the global tool registry."""
    global _global_registry
    _global_registry = None


def register_tool(tool: BaseTool) -> None:
    """Register a tool in the global registry."""
    get_tool_registry().register(tool)
