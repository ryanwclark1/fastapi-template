"""AI Agent Framework.

This package provides a complete agent framework for building
autonomous AI agents with:

- Multi-provider LLM support (OpenAI, Anthropic, etc.)
- Tool/function calling
- State management and persistence
- Checkpoint/resume capabilities
- Full observability (tracing, metrics, logging)
- Run management (retry, resume, cancel)

Quick Start:
    from example_service.infra.ai.agents import (
        BaseAgent,
        AgentConfig,
        AgentResult,
        ToolRegistry,
        BaseTool,
        ToolResult,
        tool,
    )

    # Define a simple agent
    class QAAgent(BaseAgent[str, str]):
        agent_type = "qa_agent"

        async def run(self, question: str) -> str:
            messages = [{"role": "user", "content": question}]
            response = await self.llm_call(messages)

            while response.tool_calls:
                tool_results = await self.execute_tools(response.tool_calls)
                messages.extend(tool_results)
                response = await self.llm_call(messages)

            return response.content or ""

    # Execute the agent
    agent = QAAgent(config=AgentConfig(model="gpt-4o"))
    result = await agent.execute(question="What is the capital of France?")

    print(f"Answer: {result.output}")
    print(f"Cost: ${result.total_cost_usd}")

Architecture:
    BaseAgent (core abstraction)
        ├── AgentConfig (configuration)
        ├── AgentState (runtime state)
        └── AgentResult (execution result)

    ToolRegistry (tool management)
        ├── BaseTool (tool base class)
        ├── FunctionTool (decorator-based tools)
        └── ToolResult (execution result)

    RunManager (run lifecycle)
        ├── Run tracking
        ├── Retry/resume
        └── Cost reporting

    Observability
        ├── AgentTracer (OpenTelemetry)
        ├── Prometheus metrics
        └── Structured logging
"""

from __future__ import annotations

# Base agent
from example_service.infra.ai.agents.base import (
    AgentConfig,
    AgentResult,
    AgentState,
    BaseAgent,
    LLMResponse,
)

# Database models
from example_service.infra.ai.agents.models import (
    AgentMessageRole,
    AgentRunStatus,
    AgentStepStatus,
    AgentStepType,
    AIAgentCheckpoint,
    AIAgentMessage,
    AIAgentRun,
    AIAgentStep,
    AIAgentToolCall,
)

# Observability
from example_service.infra.ai.agents.observability import (
    AgentLogger,
    AgentTracer,
    configure_agent_tracer,
    get_agent_tracer,
)

# Run manager
from example_service.infra.ai.agents.run_manager import (
    CostSummary,
    RunFilter,
    RunListResult,
    RunManager,
    RunStats,
)

# Tools
from example_service.infra.ai.agents.tools import (
    BaseTool,
    FunctionTool,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    get_tool_registry,
    register_tool,
    reset_tool_registry,
    tool,
)

__all__ = [
    # Agent base
    "AgentConfig",
    "AgentResult",
    "AgentState",
    "BaseAgent",
    "LLMResponse",
    # Models
    "AgentMessageRole",
    "AgentRunStatus",
    "AgentStepStatus",
    "AgentStepType",
    "AIAgentCheckpoint",
    "AIAgentMessage",
    "AIAgentRun",
    "AIAgentStep",
    "AIAgentToolCall",
    # Run manager
    "CostSummary",
    "RunFilter",
    "RunListResult",
    "RunManager",
    "RunStats",
    # Tools
    "BaseTool",
    "FunctionTool",
    "ToolDefinition",
    "ToolParameter",
    "ToolRegistry",
    "ToolResult",
    "ToolResultStatus",
    "get_tool_registry",
    "register_tool",
    "reset_tool_registry",
    "tool",
    # Observability
    "AgentLogger",
    "AgentTracer",
    "configure_agent_tracer",
    "get_agent_tracer",
]
