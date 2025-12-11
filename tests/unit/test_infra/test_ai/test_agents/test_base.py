"""Tests for the AI agent base class."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from example_service.infra.ai.agents.base import (
    AgentConfig,
    AgentResult,
    AgentState,
    BaseAgent,
    LLMResponse,
)
from example_service.infra.ai.agents.tools import (
    ToolRegistry,
    ToolResult,
    tool,
)


class TestAgentConfig:
    """Tests for AgentConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = AgentConfig()

        assert config.model == "gpt-4o"
        assert config.provider == "openai"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.max_iterations == 10
        assert config.max_retries == 3
        assert config.timeout_seconds == 300

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = AgentConfig(
            model="claude-3-opus",
            provider="anthropic",
            temperature=0.5,
            max_iterations=5,
        )

        assert config.model == "claude-3-opus"
        assert config.provider == "anthropic"
        assert config.temperature == 0.5
        assert config.max_iterations == 5

    def test_config_validation(self) -> None:
        """Test configuration validation."""
        # Temperature out of range
        with pytest.raises(ValueError):
            AgentConfig(temperature=-0.1)

        with pytest.raises(ValueError):
            AgentConfig(temperature=2.1)

        # Invalid max_iterations
        with pytest.raises(ValueError):
            AgentConfig(max_iterations=0)


class TestAgentState:
    """Tests for AgentState."""

    def test_default_state(self) -> None:
        """Test default state values."""
        state = AgentState()

        assert state.iteration == 0
        assert state.step_count == 0
        assert state.tool_call_count == 0
        assert state.messages == []
        assert state.context == {}
        assert state.total_cost_usd == Decimal(0)
        assert state.is_complete is False

    def test_state_to_dict(self) -> None:
        """Test state serialization."""
        state = AgentState()
        state.iteration = 5
        state.step_count = 10
        state.total_cost_usd = Decimal("0.05")

        d = state.to_dict()

        assert d["iteration"] == 5
        assert d["step_count"] == 10
        assert d["total_cost_usd"] == "0.05"

    def test_state_from_dict(self) -> None:
        """Test state deserialization."""
        data = {
            "iteration": 3,
            "step_count": 7,
            "messages": [{"role": "user", "content": "test"}],
            "total_cost_usd": "0.10",
            "is_complete": True,
        }

        state = AgentState.from_dict(data)

        assert state.iteration == 3
        assert state.step_count == 7
        assert len(state.messages) == 1
        assert state.total_cost_usd == Decimal("0.10")
        assert state.is_complete is True


class TestAgentResult:
    """Tests for AgentResult."""

    def test_success_result(self) -> None:
        """Test creating success result."""
        state = AgentState()
        state.iteration = 3
        state.total_cost_usd = Decimal("0.05")

        result = AgentResult.success_result(
            output="Test output",
            state=state,
        )

        assert result.success is True
        assert result.output == "Test output"
        assert result.error is None
        assert result.iterations == 3
        assert result.total_cost_usd == Decimal("0.05")

    def test_failure_result(self) -> None:
        """Test creating failure result."""
        state = AgentState()
        state.iteration = 2

        result = AgentResult.failure_result(
            error="Something failed",
            error_code="ERR001",
            state=state,
        )

        assert result.success is False
        assert result.error == "Something failed"
        assert result.error_code == "ERR001"
        assert result.iterations == 2


class TestLLMResponse:
    """Tests for LLMResponse."""

    def test_response_creation(self) -> None:
        """Test creating LLM response."""
        response = LLMResponse(
            content="Hello, world!",
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0.001"),
            model="gpt-4",
            provider="openai",
        )

        assert response.content == "Hello, world!"
        assert response.input_tokens == 10
        assert response.output_tokens == 5
        assert response.cost_usd == Decimal("0.001")
        assert response.tool_calls == []

    def test_response_with_tool_calls(self) -> None:
        """Test response with tool calls."""
        response = LLMResponse(
            content=None,
            tool_calls=[
                {
                    "id": "call_123",
                    "function": {
                        "name": "search",
                        "arguments": '{"query": "test"}',
                    },
                },
            ],
        )

        assert response.content is None
        assert len(response.tool_calls) == 1


class TestBaseAgent:
    """Tests for BaseAgent."""

    def test_agent_requires_type(self) -> None:
        """Test that agent requires agent_type."""

        class NoTypeAgent(BaseAgent[str, str]):
            async def run(self, input_data: str) -> str:
                return input_data

        with pytest.raises(ValueError, match="agent_type"):
            NoTypeAgent()

    def test_agent_initialization(self) -> None:
        """Test basic agent initialization."""

        class SimpleAgent(BaseAgent[str, str]):
            agent_type = "simple_agent"

            async def run(self, input_data: str) -> str:
                return f"Processed: {input_data}"

        agent = SimpleAgent()

        assert agent.agent_type == "simple_agent"
        assert agent.config is not None
        assert agent.tool_registry is not None

    def test_agent_with_custom_config(self) -> None:
        """Test agent with custom configuration."""

        class CustomAgent(BaseAgent[str, str]):
            agent_type = "custom_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        config = AgentConfig(model="claude-3-sonnet", max_iterations=5)
        agent = CustomAgent(config=config)

        assert agent.config.model == "claude-3-sonnet"
        assert agent.config.max_iterations == 5

    def test_agent_with_default_config(self) -> None:
        """Test agent with class-level default config."""

        class DefaultConfigAgent(BaseAgent[str, str]):
            agent_type = "default_agent"
            default_config = AgentConfig(temperature=0.3)

            async def run(self, input_data: str) -> str:
                return input_data

        agent = DefaultConfigAgent()

        assert agent.config.temperature == 0.3

    def test_agent_state_property(self) -> None:
        """Test accessing agent state."""

        class StatefulAgent(BaseAgent[str, str]):
            agent_type = "stateful_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        agent = StatefulAgent()
        state = agent.state

        assert isinstance(state, AgentState)
        assert state.iteration == 0

    @pytest.mark.anyio
    async def test_agent_execute_tool(self) -> None:
        """Test executing a tool from agent."""

        @tool(description="Double a number")
        async def double(x: int) -> int:
            return x * 2

        class ToolAgent(BaseAgent[str, str]):
            agent_type = "tool_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        registry = ToolRegistry()
        registry.register(double)

        agent = ToolAgent(tool_registry=registry)
        result = await agent.execute_tool("double", {"x": 5})

        assert result.is_success
        assert result.data == 10

    @pytest.mark.anyio
    async def test_agent_execute_missing_tool(self) -> None:
        """Test executing a missing tool."""

        class NoToolAgent(BaseAgent[str, str]):
            agent_type = "no_tool_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        agent = NoToolAgent(tool_registry=ToolRegistry())
        result = await agent.execute_tool("nonexistent", {})

        assert result.is_failure
        assert "not found" in str(result.error)

    @pytest.mark.anyio
    async def test_agent_cancel(self) -> None:
        """Test agent cancellation."""

        class CancellableAgent(BaseAgent[str, str]):
            agent_type = "cancellable_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        agent = CancellableAgent()
        assert agent._cancelled is False

        agent.cancel()
        assert agent._cancelled is True

    @pytest.mark.anyio
    async def test_simple_agent_execute(self) -> None:
        """Test simple agent execution without LLM calls."""

        class EchoAgent(BaseAgent[str, str]):
            agent_type = "echo_agent"

            async def run(self, input_data: str) -> str:
                self._state.is_complete = True
                return f"Echo: {input_data}"

        agent = EchoAgent()
        result = await agent.execute("Hello")

        assert result.success is True
        assert result.output == "Echo: Hello"
        assert result.iterations == 1


class TestAgentToolExecution:
    """Tests for agent tool execution."""

    @pytest.mark.anyio
    async def test_execute_tools_formats_results(self) -> None:
        """Test that execute_tools formats results for LLM."""

        @tool(description="Get weather")
        async def get_weather(city: str) -> str:
            return f"Weather in {city}: Sunny, 22°C"

        class WeatherAgent(BaseAgent[str, str]):
            agent_type = "weather_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        registry = ToolRegistry()
        registry.register(get_weather)

        agent = WeatherAgent(tool_registry=registry)

        tool_calls = [
            {
                "id": "call_123",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "Paris"}',
                },
            },
        ]

        results = await agent.execute_tools(tool_calls)

        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "call_123"
        assert "Paris" in results[0]["content"]
        assert "Sunny" in results[0]["content"]

    @pytest.mark.anyio
    async def test_execute_tools_handles_errors(self) -> None:
        """Test that execute_tools handles tool errors."""

        @tool(description="Failing tool")
        async def failing_tool() -> None:
            msg = "Intentional error"
            raise ValueError(msg)

        class FailingAgent(BaseAgent[str, str]):
            agent_type = "failing_agent"

            async def run(self, input_data: str) -> str:
                return input_data

        registry = ToolRegistry()
        registry.register(failing_tool)

        agent = FailingAgent(tool_registry=registry)

        tool_calls = [
            {
                "id": "call_456",
                "function": {
                    "name": "failing_tool",
                    "arguments": "{}",
                },
            },
        ]

        results = await agent.execute_tools(tool_calls)

        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert "Error" in results[0]["content"]
