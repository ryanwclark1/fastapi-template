"""Base Agent class for AI agent framework.

This module provides the core agent abstraction with:
- LLM integration (multi-provider support)
- Tool/function calling
- State management
- Checkpoint/resume capabilities
- Observability hooks

Design Principles:
1. Provider-agnostic: Works with OpenAI, Anthropic, and other providers
2. Observable: Full tracing and metrics integration
3. Resilient: Built-in retry and error handling
4. Composable: Agents can delegate to sub-agents

Example:
    from example_service.infra.ai.agents import BaseAgent, AgentConfig

    class ResearchAgent(BaseAgent):
        async def run(self, query: str) -> str:
            # Agent implementation
            messages = [{"role": "user", "content": query}]
            response = await self.llm_call(messages)
            return response

    # Create and execute agent
    agent = ResearchAgent(config=AgentConfig(model="gpt-4"))
    result = await agent.execute(query="What is quantum computing?")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from example_service.infra.ai.agents.tools import (
    ToolRegistry,
    ToolResult,
    get_tool_registry,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.infra.ai.agents.models import (
        AIAgentRun,
    )

logger = logging.getLogger(__name__)

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


class AgentConfig(BaseModel):
    """Configuration for an agent.

    This configuration controls agent behavior including:
    - LLM settings (model, temperature, etc.)
    - Tool configuration
    - Execution limits
    - Checkpoint behavior
    """

    # Agent configuration reference (optional - links to persisted Agent model)
    agent_id: UUID | None = Field(
        default=None,
        description="UUID of the Agent configuration in database (if using persisted config)",
    )

    # Model settings
    model: str = Field(
        default="gpt-4o",
        description="LLM model to use",
    )
    provider: str = Field(
        default="openai",
        description="LLM provider (openai, anthropic, etc.)",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum tokens in response",
    )

    # System prompt
    system_prompt: str | None = Field(
        default=None,
        description="System prompt for the agent",
    )

    # Execution limits
    max_iterations: int = Field(
        default=10,
        gt=0,
        description="Maximum number of agent iterations",
    )
    max_tool_calls_per_iteration: int = Field(
        default=5,
        gt=0,
        description="Maximum tool calls per iteration",
    )
    timeout_seconds: int = Field(
        default=300,
        gt=0,
        description="Overall execution timeout",
    )
    iteration_timeout_seconds: int = Field(
        default=60,
        gt=0,
        description="Per-iteration timeout",
    )

    # Retry settings
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts on failure",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0,
        description="Initial delay between retries",
    )
    retry_backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        description="Backoff multiplier for retries",
    )

    # Tool settings
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names to enable (empty = all)",
    )
    exclude_dangerous_tools: bool = Field(
        default=True,
        description="Whether to exclude dangerous tools",
    )

    # Checkpoint settings
    enable_checkpoints: bool = Field(
        default=True,
        description="Whether to create checkpoints",
    )
    checkpoint_interval: int = Field(
        default=3,
        gt=0,
        description="Create checkpoint every N steps",
    )

    # Cost controls
    max_cost_usd: float | None = Field(
        default=None,
        description="Maximum cost limit in USD",
    )
    max_tokens_total: int | None = Field(
        default=None,
        description="Maximum total tokens (input + output)",
    )

    # Structured output
    output_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON schema for structured output",
    )


@dataclass
class AgentState:
    """Current state of an agent execution.

    This state is persisted and can be used to:
    - Resume from checkpoints
    - Track progress
    - Debug execution
    """

    # Execution tracking
    iteration: int = 0
    step_count: int = 0
    tool_call_count: int = 0

    # Conversation history
    messages: list[dict[str, Any]] = field(default_factory=list)

    # Accumulated data
    context: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)

    # Cost tracking
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Status
    is_complete: bool = False
    needs_human_input: bool = False
    human_input_prompt: str | None = None

    # Error tracking
    last_error: str | None = None
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for persistence."""
        return {
            "iteration": self.iteration,
            "step_count": self.step_count,
            "tool_call_count": self.tool_call_count,
            "messages": self.messages,
            "context": self.context,
            "tool_results": self.tool_results,
            "total_cost_usd": str(self.total_cost_usd),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "is_complete": self.is_complete,
            "needs_human_input": self.needs_human_input,
            "human_input_prompt": self.human_input_prompt,
            "last_error": self.last_error,
            "error_count": self.error_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentState:
        """Create state from dictionary."""
        state = cls()
        state.iteration = data.get("iteration", 0)
        state.step_count = data.get("step_count", 0)
        state.tool_call_count = data.get("tool_call_count", 0)
        state.messages = data.get("messages", [])
        state.context = data.get("context", {})
        state.tool_results = data.get("tool_results", [])
        state.total_cost_usd = Decimal(data.get("total_cost_usd", "0"))
        state.total_input_tokens = data.get("total_input_tokens", 0)
        state.total_output_tokens = data.get("total_output_tokens", 0)
        state.is_complete = data.get("is_complete", False)
        state.needs_human_input = data.get("needs_human_input", False)
        state.human_input_prompt = data.get("human_input_prompt")
        state.last_error = data.get("last_error")
        state.error_count = data.get("error_count", 0)
        return state


@dataclass
class AgentResult[TOutput]:
    """Result from agent execution.

    Contains the final output, execution metadata, and any errors.
    """

    # Output
    success: bool
    output: TOutput | None = None
    error: str | None = None
    error_code: str | None = None

    # Execution metadata
    run_id: UUID | None = None
    iterations: int = 0
    steps: int = 0
    tool_calls: int = 0

    # Cost
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    # State (for debugging/resume)
    final_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls,
        output: TOutput,
        state: AgentState,
        run_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> AgentResult[TOutput]:
        """Create a successful result."""
        completed_at = datetime.now(UTC)
        duration = None
        if started_at:
            duration = (completed_at - started_at).total_seconds()

        return cls(
            success=True,
            output=output,
            run_id=run_id,
            iterations=state.iteration,
            steps=state.step_count,
            tool_calls=state.tool_call_count,
            total_cost_usd=state.total_cost_usd,
            total_input_tokens=state.total_input_tokens,
            total_output_tokens=state.total_output_tokens,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            final_state=state.to_dict(),
        )

    @classmethod
    def failure_result(
        cls,
        error: str,
        error_code: str | None = None,
        state: AgentState | None = None,
        run_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> AgentResult[TOutput]:
        """Create a failure result."""
        completed_at = datetime.now(UTC)
        duration = None
        if started_at:
            duration = (completed_at - started_at).total_seconds()

        return cls(
            success=False,
            error=error,
            error_code=error_code,
            run_id=run_id,
            iterations=state.iteration if state else 0,
            steps=state.step_count if state else 0,
            tool_calls=state.tool_call_count if state else 0,
            total_cost_usd=state.total_cost_usd if state else Decimal(0),
            total_input_tokens=state.total_input_tokens if state else 0,
            total_output_tokens=state.total_output_tokens if state else 0,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            final_state=state.to_dict() if state else {},
        )


class LLMResponse(BaseModel):
    """Response from an LLM call."""

    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None

    # Usage
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Field(default_factory=lambda: Decimal(0))

    # Metadata
    model: str | None = None
    provider: str | None = None
    latency_ms: float | None = None


class BaseAgent[TInput, TOutput](ABC):
    """Abstract base class for AI agents.

    Provides the foundation for building autonomous agents with:
    - Multi-turn conversation management
    - Tool/function calling
    - State persistence
    - Checkpoint/resume
    - Cost tracking

    Subclasses must implement:
    - agent_type: Unique identifier for the agent type
    - run(): The main agent logic

    Example:
        class QAAgent(BaseAgent[str, str]):
            agent_type = "qa_agent"

            async def run(self, question: str) -> str:
                # Prepare messages
                messages = [{"role": "user", "content": question}]

                # Get LLM response
                response = await self.llm_call(messages)

                # Process tool calls if any
                while response.tool_calls:
                    tool_results = await self.execute_tools(response.tool_calls)
                    messages.extend(tool_results)
                    response = await self.llm_call(messages)

                return response.content or ""
    """

    # Class attributes to be overridden
    agent_type: str
    agent_version: str = "1.0.0"
    default_config: AgentConfig | None = None

    def __init__(
        self,
        config: AgentConfig | None = None,
        tool_registry: ToolRegistry | None = None,
        db_session: AsyncSession | None = None,
        tenant_id: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
        """Initialize the agent.

        Args:
            config: Agent configuration (uses default_config if None)
            tool_registry: Tool registry (uses global if None)
            db_session: Database session for persistence
            tenant_id: Tenant ID for multi-tenancy
            user_id: User ID for tracking
        """
        if not hasattr(self, "agent_type") or not self.agent_type:
            msg = "Agent must define agent_type"
            raise ValueError(msg)

        self.config = config or self.default_config or AgentConfig()
        self.tool_registry = tool_registry or get_tool_registry()
        self.db_session = db_session
        self.tenant_id = tenant_id
        self.user_id = user_id

        # Runtime state
        self._state: AgentState = AgentState()
        self._run_id: UUID | None = None
        self._db_run: AIAgentRun | None = None
        self._started_at: datetime | None = None
        self._cancelled = False

        # LLM client (lazy initialized)
        self._llm_client: Any = None

    @property
    def state(self) -> AgentState:
        """Get current agent state."""
        return self._state

    @abstractmethod
    async def run(self, input_data: TInput) -> TOutput:
        """Execute the agent logic.

        This is the main entry point that subclasses must implement.
        The method should handle the complete agent workflow.

        Args:
            input_data: Input data for the agent

        Returns:
            Agent output
        """

    async def execute(
        self,
        input_data: TInput,
        run_name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        resume_from_checkpoint: UUID | None = None,
    ) -> AgentResult[TOutput]:
        """Execute the agent with full tracking.

        This method wraps run() with:
        - State initialization
        - Database persistence
        - Error handling
        - Cost tracking
        - Checkpoint management

        Args:
            input_data: Input data for the agent
            run_name: Human-readable name for the run
            tags: Tags for categorization
            metadata: Additional metadata
            resume_from_checkpoint: Checkpoint ID to resume from

        Returns:
            AgentResult with output and execution metadata
        """
        self._started_at = datetime.now(UTC)
        self._run_id = uuid4()
        self._cancelled = False

        try:
            # Initialize or restore state
            if resume_from_checkpoint:
                await self._restore_from_checkpoint(resume_from_checkpoint)
            else:
                self._state = AgentState()
                if self.config.system_prompt:
                    self._state.messages.append({
                        "role": "system",
                        "content": self.config.system_prompt,
                    })

            # Create database run record if session available
            if self.db_session and self.tenant_id:
                await self._create_db_run(input_data, run_name, tags, metadata)

            # Execute with timeout
            try:
                output = await asyncio.wait_for(
                    self._execute_with_tracking(input_data),
                    timeout=self.config.timeout_seconds,
                )
                self._state.is_complete = True

                # Update database
                if self._db_run:
                    await self._complete_db_run(output)

                return AgentResult.success_result(
                    output=output,
                    state=self._state,
                    run_id=self._run_id,
                    started_at=self._started_at,
                )

            except TimeoutError:
                error = f"Agent execution timed out after {self.config.timeout_seconds}s"
                if self._db_run:
                    await self._fail_db_run(error, "timeout")
                return AgentResult.failure_result(
                    error=error,
                    error_code="timeout",
                    state=self._state,
                    run_id=self._run_id,
                    started_at=self._started_at,
                )

            except asyncio.CancelledError:
                error = "Agent execution was cancelled"
                if self._db_run:
                    await self._fail_db_run(error, "cancelled")
                return AgentResult.failure_result(
                    error=error,
                    error_code="cancelled",
                    state=self._state,
                    run_id=self._run_id,
                    started_at=self._started_at,
                )

        except Exception as e:
            logger.exception(f"Agent {self.agent_type} execution failed")
            error = str(e)
            if self._db_run:
                await self._fail_db_run(error, "execution_error")
            return AgentResult.failure_result(
                error=error,
                error_code="execution_error",
                state=self._state,
                run_id=self._run_id,
                started_at=self._started_at,
            )

    async def _execute_with_tracking(self, input_data: TInput) -> TOutput:
        """Execute with iteration tracking and checkpoints."""
        while self._state.iteration < self.config.max_iterations:
            if self._cancelled:
                raise asyncio.CancelledError

            self._state.iteration += 1

            # Check cost limits
            if (
                self.config.max_cost_usd
                and float(self._state.total_cost_usd) >= self.config.max_cost_usd
            ):
                msg = f"Cost limit exceeded: ${self._state.total_cost_usd}"
                raise RuntimeError(
                    msg,
                )

            # Check token limits
            if self.config.max_tokens_total:
                total_tokens = (
                    self._state.total_input_tokens +
                    self._state.total_output_tokens
                )
                if total_tokens >= self.config.max_tokens_total:
                    msg = f"Token limit exceeded: {total_tokens}"
                    raise RuntimeError(msg)

            # Create checkpoint if needed
            if (
                self.config.enable_checkpoints
                and self._state.iteration % self.config.checkpoint_interval == 0
            ):
                await self._create_checkpoint(f"iteration_{self._state.iteration}")

            # Run agent logic
            output = await self.run(input_data)

            if self._state.is_complete:
                return output

        msg = f"Agent exceeded maximum iterations: {self.config.max_iterations}"
        raise RuntimeError(
            msg,
        )

    async def llm_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Make an LLM call with the configured provider.

        Args:
            messages: Conversation messages
            tools: Specific tools to enable (None = use config)
            temperature: Override temperature
            max_tokens: Override max tokens
            **kwargs: Additional provider-specific arguments

        Returns:
            LLMResponse with content and/or tool calls
        """
        self._state.step_count += 1

        # Get tool definitions
        tool_defs = None
        if tools is not None or self.config.tools:
            tool_names = tools or self.config.tools or None
            tool_defs = self.tool_registry.get_definitions(
                names=tool_names,
                exclude_dangerous=self.config.exclude_dangerous_tools,
            )

        # Make LLM call based on provider
        response = await self._call_llm_provider(
            messages=messages,
            tools=tool_defs,
            temperature=temperature or self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            **kwargs,
        )

        # Update state with costs
        self._state.messages = messages.copy()
        self._state.total_input_tokens += response.input_tokens
        self._state.total_output_tokens += response.output_tokens
        self._state.total_cost_usd += response.cost_usd

        return response

    async def _call_llm_provider(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call the LLM provider.

        This method handles provider-specific API calls.
        Override this for custom provider integration.
        """
        # Get orchestrator for actual LLM calls
        from example_service.infra.ai import get_instrumented_orchestrator

        orchestrator = get_instrumented_orchestrator()

        # Build request based on provider
        if self.config.provider == "openai":
            return await self._call_openai(
                orchestrator, messages, tools, temperature, max_tokens, **kwargs,
            )
        if self.config.provider == "anthropic":
            return await self._call_anthropic(
                orchestrator, messages, tools, temperature, max_tokens, **kwargs,
            )
        msg = f"Unsupported provider: {self.config.provider}"
        raise ValueError(msg)

    async def _call_openai(
        self,
        orchestrator: Any,
        messages: list[dict[str, Any]],
        tools: list[Any] | None,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Make OpenAI API call."""
        from example_service.infra.ai.capabilities.types import Capability

        # Prepare options
        options = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        if tools:
            options["tools"] = [t.to_openai_format() for t in tools]

        # Use capability registry
        result = await orchestrator.execute_capability(
            capability=Capability.LLM_FUNCTION_CALLING if tools else Capability.LLM_GENERATION,
            input_data=options,
            tenant_id=self.tenant_id,
            provider_preference=["openai"],
        )

        if not result.success:
            msg = f"LLM call failed: {result.error}"
            raise RuntimeError(msg)

        data = result.data or {}
        usage = result.usage or {}

        return LLMResponse(
            content=data.get("content"),
            tool_calls=data.get("tool_calls", []),
            finish_reason=data.get("finish_reason"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cost_usd=result.cost_usd or Decimal(0),
            model=self.config.model,
            provider="openai",
            latency_ms=result.latency_ms,
        )

    async def _call_anthropic(
        self,
        orchestrator: Any,
        messages: list[dict[str, Any]],
        tools: list[Any] | None,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """Make Anthropic API call."""
        from example_service.infra.ai.capabilities.types import Capability

        # Prepare options
        options = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        if tools:
            options["tools"] = [t.to_anthropic_format() for t in tools]

        # Use capability registry
        result = await orchestrator.execute_capability(
            capability=Capability.LLM_FUNCTION_CALLING if tools else Capability.LLM_GENERATION,
            input_data=options,
            tenant_id=self.tenant_id,
            provider_preference=["anthropic"],
        )

        if not result.success:
            msg = f"LLM call failed: {result.error}"
            raise RuntimeError(msg)

        data = result.data or {}
        usage = result.usage or {}

        return LLMResponse(
            content=data.get("content"),
            tool_calls=data.get("tool_calls", []),
            finish_reason=data.get("finish_reason"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cost_usd=result.cost_usd or Decimal(0),
            model=self.config.model,
            provider="anthropic",
            latency_ms=result.latency_ms,
        )

    async def execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_call_id: str | None = None,
    ) -> ToolResult[Any]:
        """Execute a single tool.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments for the tool
            tool_call_id: ID for correlation

        Returns:
            ToolResult from tool execution
        """
        self._state.tool_call_count += 1
        started_at = datetime.now(UTC)

        tool = self.tool_registry.get(tool_name)
        if tool is None:
            return ToolResult.failure(
                error=f"Tool '{tool_name}' not found",
                error_code="tool_not_found",
            )

        try:
            # Check if tool requires confirmation
            if tool.requires_confirmation:
                self._state.needs_human_input = True
                self._state.human_input_prompt = (
                    f"Tool '{tool_name}' requires confirmation. "
                    f"Args: {tool_args}"
                )
                return ToolResult.failure(
                    error="Tool requires human confirmation",
                    error_code="confirmation_required",
                )

            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(**tool_args),
                timeout=tool.timeout_seconds,
            )

            duration = (datetime.now(UTC) - started_at).total_seconds() * 1000
            result.duration_ms = duration

            # Store result
            self._state.tool_results.append({
                "tool_name": tool_name,
                "tool_args": tool_args,
                "tool_call_id": tool_call_id,
                "result": result.to_dict(),
            })

            return result

        except TimeoutError:
            return ToolResult.timeout(
                error=f"Tool '{tool_name}' timed out after {tool.timeout_seconds}s",
            )
        except Exception as e:
            logger.exception(f"Tool {tool_name} execution failed")
            return ToolResult.failure(error=str(e))

    async def execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute multiple tool calls and format results for LLM.

        Args:
            tool_calls: List of tool calls from LLM response

        Returns:
            List of tool result messages for LLM
        """
        results = []

        for call in tool_calls:
            tool_name = call.get("function", {}).get("name") or call.get("name")
            tool_args = call.get("function", {}).get("arguments") or call.get("input", {})
            tool_call_id = call.get("id") or call.get("tool_call_id")

            # Parse arguments if string
            if isinstance(tool_args, str):
                import json
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {"raw_input": tool_args}

            result = await self.execute_tool(tool_name, tool_args, tool_call_id)

            # Format for LLM consumption
            results.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result.to_message_content(),
            })

        return results

    def cancel(self) -> None:
        """Request cancellation of the agent execution."""
        self._cancelled = True

    async def pause(self) -> UUID | None:
        """Pause execution and create checkpoint.

        Returns:
            Checkpoint ID if created, None otherwise
        """
        return await self._create_checkpoint("manual_pause")

    async def _create_checkpoint(self, name: str) -> UUID | None:
        """Create a checkpoint of current state."""
        if not self.db_session or not self._db_run:
            return None

        from example_service.infra.ai.agents.models import AIAgentCheckpoint

        checkpoint = AIAgentCheckpoint(
            run_id=self._db_run.id,
            checkpoint_name=name,
            step_number=self._state.step_count,
            state_snapshot=self._state.to_dict(),
            context_snapshot=self._state.context,
            messages_snapshot=self._state.messages,
            is_automatic=True,
            trigger_reason=name,
        )

        self.db_session.add(checkpoint)
        await self.db_session.flush()

        logger.debug(f"Created checkpoint: {checkpoint.id} ({name})")
        return checkpoint.id

    async def _restore_from_checkpoint(self, checkpoint_id: UUID) -> None:
        """Restore state from a checkpoint."""
        if not self.db_session:
            msg = "Database session required for checkpoint restore"
            raise RuntimeError(msg)

        from sqlalchemy import select

        from example_service.infra.ai.agents.models import AIAgentCheckpoint

        result = await self.db_session.execute(
            select(AIAgentCheckpoint).where(AIAgentCheckpoint.id == checkpoint_id),
        )
        checkpoint = result.scalar_one_or_none()

        if not checkpoint:
            msg = f"Checkpoint {checkpoint_id} not found"
            raise ValueError(msg)

        if not checkpoint.is_valid:
            msg = f"Checkpoint {checkpoint_id} is invalid: {checkpoint.invalidated_reason}"
            raise ValueError(
                msg,
            )

        self._state = AgentState.from_dict(checkpoint.state_snapshot)
        self._state.context = checkpoint.context_snapshot
        self._state.messages = checkpoint.messages_snapshot

        logger.info(f"Restored from checkpoint: {checkpoint_id}")

    async def _create_db_run(
        self,
        input_data: TInput,
        run_name: str | None,
        tags: list[str] | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        """Create database run record."""
        from example_service.infra.ai.agents.models import AIAgentRun

        # Serialize input
        if isinstance(input_data, BaseModel):
            input_dict = input_data.model_dump()
        elif isinstance(input_data, dict):
            input_dict = input_data
        else:
            input_dict = {"value": input_data}

        self._db_run = AIAgentRun(
            id=self._run_id,
            tenant_id=self.tenant_id,
            agent_id=self.config.agent_id,  # Link to Agent configuration if available
            agent_type=self.agent_type,
            agent_version=self.agent_version,
            run_name=run_name,
            status="running",
            input_data=input_dict,
            config=self.config.model_dump(),
            started_at=self._started_at,
            tags=tags or [],
            metadata_json=metadata or {},
            created_by_id=self.user_id,
            timeout_seconds=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )

        self.db_session.add(self._db_run)
        await self.db_session.flush()

    async def _complete_db_run(self, output: TOutput) -> None:
        """Update database run as completed."""
        if not self._db_run:
            return

        # Serialize output
        if isinstance(output, BaseModel):
            output_dict = output.model_dump()
        elif isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {"value": output}

        self._db_run.status = "completed"
        self._db_run.output_data = output_dict
        self._db_run.completed_at = datetime.now(UTC)
        self._db_run.current_step = self._state.step_count
        self._db_run.progress_percent = 100.0
        self._db_run.total_cost_usd = float(self._state.total_cost_usd)
        self._db_run.total_input_tokens = self._state.total_input_tokens
        self._db_run.total_output_tokens = self._state.total_output_tokens
        self._db_run.state = self._state.to_dict()
        self._db_run.context = self._state.context

        await self.db_session.flush()

    async def _fail_db_run(self, error: str, error_code: str) -> None:
        """Update database run as failed."""
        if not self._db_run:
            return

        self._db_run.status = "failed"
        self._db_run.error_message = error
        self._db_run.error_code = error_code
        self._db_run.completed_at = datetime.now(UTC)
        self._db_run.current_step = self._state.step_count
        self._db_run.total_cost_usd = float(self._state.total_cost_usd)
        self._db_run.total_input_tokens = self._state.total_input_tokens
        self._db_run.total_output_tokens = self._state.total_output_tokens
        self._db_run.state = self._state.to_dict()

        await self.db_session.flush()

    def __repr__(self) -> str:
        """Return agent runtime summary for debugging."""
        return f"<{self.__class__.__name__}(type={self.agent_type})>"
