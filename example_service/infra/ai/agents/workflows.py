"""Advanced workflow capabilities for AI agents.

This module provides LangGraph-like workflow features:
- Human-in-the-loop checkpoints and approvals
- Parallel execution branches
- Conditional routing based on LLM decisions
- Workflow state machines
- Subgraph composition

Example:
    from example_service.infra.ai.agents.workflows import (
        WorkflowBuilder,
        human_approval,
        conditional_branch,
        parallel,
    )

    # Build a workflow with human approval
    workflow = (
        WorkflowBuilder("review_workflow")
        .add_node("analyze", analyze_document)
        .add_node("review", human_approval("Please review the analysis"))
        .add_node("finalize", finalize_report)
        .add_edge("analyze", "review")
        .add_edge("review", "finalize")
        .compile()
    )

    result = await workflow.run({"document": "..."})
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar
from uuid import UUID, uuid4
import logging

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)

T = TypeVar("T")
StateT = TypeVar("StateT", bound=dict[str, Any])


class NodeStatus(str, Enum):
    """Status of a workflow node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class WorkflowStatus(str, Enum):
    """Status of a workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class HumanApprovalRequest:
    """Request for human approval."""

    request_id: UUID = field(default_factory=uuid4)
    workflow_id: UUID | None = None
    node_name: str = ""
    prompt: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    options: list[str] = field(default_factory=lambda: ["approve", "reject"])
    timeout_seconds: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Response (filled when approved/rejected)
    response: str | None = None
    response_data: dict[str, Any] | None = None
    responded_at: datetime | None = None
    responded_by: str | None = None


@dataclass
class NodeResult:
    """Result from a workflow node execution."""

    node_name: str
    status: NodeStatus
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    approval_request: HumanApprovalRequest | None = None

    @property
    def duration_ms(self) -> float | None:
        """Get execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None


@dataclass
class WorkflowState(Generic[StateT]):
    """State of a workflow execution."""

    workflow_id: UUID = field(default_factory=uuid4)
    workflow_name: str = ""
    status: WorkflowStatus = WorkflowStatus.PENDING

    # State data
    data: StateT = field(default_factory=dict)  # type: ignore
    initial_input: dict[str, Any] = field(default_factory=dict)

    # Execution tracking
    current_node: str | None = None
    executed_nodes: list[str] = field(default_factory=list)
    node_results: dict[str, NodeResult] = field(default_factory=dict)

    # Approval tracking
    pending_approvals: list[HumanApprovalRequest] = field(default_factory=list)

    # Timing
    started_at: datetime | None = None
    completed_at: datetime | None = None
    paused_at: datetime | None = None

    # Error tracking
    error: str | None = None
    failed_node: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence."""
        return {
            "workflow_id": str(self.workflow_id),
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "data": self.data,
            "initial_input": self.initial_input,
            "current_node": self.current_node,
            "executed_nodes": self.executed_nodes,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "error": self.error,
            "failed_node": self.failed_node,
        }


# Type for node functions
NodeFunc = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ConditionFunc = Callable[[dict[str, Any]], str | Awaitable[str]]


class WorkflowNode(ABC):
    """Abstract base for workflow nodes."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def execute(
        self,
        state: WorkflowState[Any],
        context: WorkflowContext,
    ) -> NodeResult:
        """Execute the node.

        Args:
            state: Current workflow state
            context: Workflow execution context

        Returns:
            NodeResult with output or approval request
        """
        pass


class FunctionNode(WorkflowNode):
    """Node that executes a function."""

    def __init__(
        self,
        name: str,
        func: NodeFunc,
        retry_count: int = 0,
    ) -> None:
        super().__init__(name)
        self.func = func
        self.retry_count = retry_count

    async def execute(
        self,
        state: WorkflowState[Any],
        context: WorkflowContext,
    ) -> NodeResult:
        """Execute the function."""
        started_at = datetime.now(UTC)
        attempts = 0

        while attempts <= self.retry_count:
            try:
                output = await self.func(state.data)

                # Update state with output
                if isinstance(output, dict):
                    state.data.update(output)

                return NodeResult(
                    node_name=self.name,
                    status=NodeStatus.COMPLETED,
                    output=output,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )
            except Exception as e:
                attempts += 1
                if attempts > self.retry_count:
                    return NodeResult(
                        node_name=self.name,
                        status=NodeStatus.FAILED,
                        error=str(e),
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                    )
                logger.warning(f"Node {self.name} failed, retry {attempts}")

        # Should not reach here
        return NodeResult(
            node_name=self.name,
            status=NodeStatus.FAILED,
            error="Unknown error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )


class HumanApprovalNode(WorkflowNode):
    """Node that requires human approval."""

    def __init__(
        self,
        name: str,
        prompt: str,
        options: list[str] | None = None,
        timeout_seconds: int | None = None,
        context_keys: list[str] | None = None,
    ) -> None:
        """Initialize human approval node.

        Args:
            name: Node name
            prompt: Prompt to show for approval
            options: Available options (default: approve/reject)
            timeout_seconds: Timeout for approval
            context_keys: State keys to include in context
        """
        super().__init__(name)
        self.prompt = prompt
        self.options = options or ["approve", "reject"]
        self.timeout_seconds = timeout_seconds
        self.context_keys = context_keys or []

    async def execute(
        self,
        state: WorkflowState[Any],
        context: WorkflowContext,
    ) -> NodeResult:
        """Request human approval."""
        started_at = datetime.now(UTC)

        # Build context for approval
        approval_context = {}
        for key in self.context_keys:
            if key in state.data:
                approval_context[key] = state.data[key]

        # Create approval request
        request = HumanApprovalRequest(
            workflow_id=state.workflow_id,
            node_name=self.name,
            prompt=self.prompt,
            context=approval_context,
            options=self.options,
            timeout_seconds=self.timeout_seconds,
        )

        # Add to pending approvals
        state.pending_approvals.append(request)

        # Notify approval handler if available
        if context.approval_handler:
            await context.approval_handler(request)

        return NodeResult(
            node_name=self.name,
            status=NodeStatus.WAITING_APPROVAL,
            approval_request=request,
            started_at=started_at,
        )


class ConditionalNode(WorkflowNode):
    """Node that routes based on condition."""

    def __init__(
        self,
        name: str,
        condition: ConditionFunc,
        branches: dict[str, str],
        default_branch: str | None = None,
    ) -> None:
        """Initialize conditional node.

        Args:
            name: Node name
            condition: Function that returns branch name
            branches: Mapping of condition results to next nodes
            default_branch: Default branch if condition result not in branches
        """
        super().__init__(name)
        self.condition = condition
        self.branches = branches
        self.default_branch = default_branch

    async def execute(
        self,
        state: WorkflowState[Any],
        context: WorkflowContext,
    ) -> NodeResult:
        """Evaluate condition and route."""
        started_at = datetime.now(UTC)

        try:
            result = self.condition(state.data)
            if asyncio.iscoroutine(result):
                result = await result

            next_node = self.branches.get(result, self.default_branch)

            return NodeResult(
                node_name=self.name,
                status=NodeStatus.COMPLETED,
                output={"branch": result, "next_node": next_node},
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
        except Exception as e:
            return NodeResult(
                node_name=self.name,
                status=NodeStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )


class ParallelNode(WorkflowNode):
    """Node that executes multiple nodes in parallel."""

    def __init__(
        self,
        name: str,
        branches: list[str],
        merge_strategy: str = "merge",  # merge, first, all
    ) -> None:
        """Initialize parallel node.

        Args:
            name: Node name
            branches: List of node names to execute in parallel
            merge_strategy: How to merge results (merge, first, all)
        """
        super().__init__(name)
        self.branches = branches
        self.merge_strategy = merge_strategy

    async def execute(
        self,
        state: WorkflowState[Any],
        context: WorkflowContext,
    ) -> NodeResult:
        """Execute branches in parallel."""
        started_at = datetime.now(UTC)

        # Get nodes for branches
        nodes = [context.get_node(name) for name in self.branches]
        missing = [name for name, node in zip(self.branches, nodes) if node is None]
        if missing:
            return NodeResult(
                node_name=self.name,
                status=NodeStatus.FAILED,
                error=f"Missing branch nodes: {missing}",
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        # Execute in parallel
        tasks = [
            node.execute(state, context)  # type: ignore
            for node in nodes
            if node is not None
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        outputs = []
        errors = []
        for branch, result in zip(self.branches, results):
            if isinstance(result, Exception):
                errors.append(f"{branch}: {result}")
            elif isinstance(result, NodeResult):
                if result.status == NodeStatus.FAILED:
                    errors.append(f"{branch}: {result.error}")
                else:
                    outputs.append({branch: result.output})
            else:
                outputs.append({branch: result})

        if errors:
            return NodeResult(
                node_name=self.name,
                status=NodeStatus.FAILED,
                error="; ".join(errors),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        # Merge outputs based on strategy
        if self.merge_strategy == "merge":
            merged = {}
            for output in outputs:
                merged.update(output)
            state.data.update(merged)
        elif self.merge_strategy == "all":
            state.data["parallel_results"] = outputs

        return NodeResult(
            node_name=self.name,
            status=NodeStatus.COMPLETED,
            output=outputs,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )


@dataclass
class WorkflowContext:
    """Context for workflow execution."""

    workflow: Workflow
    approval_handler: Callable[[HumanApprovalRequest], Awaitable[None]] | None = None
    state_store: Any = None  # StateStore for persistence
    tracer: Any = None  # Tracer for observability

    def get_node(self, name: str) -> WorkflowNode | None:
        """Get a node by name."""
        return self.workflow.nodes.get(name)


class Workflow:
    """Executable workflow definition.

    A workflow is a directed graph of nodes with edges defining
    the execution flow.
    """

    def __init__(
        self,
        name: str,
        nodes: dict[str, WorkflowNode],
        edges: dict[str, list[str]],
        entry_point: str,
        end_nodes: list[str] | None = None,
    ) -> None:
        """Initialize workflow.

        Args:
            name: Workflow name
            nodes: Dict of node name to WorkflowNode
            edges: Dict of node name to list of next node names
            entry_point: Starting node name
            end_nodes: Terminal node names (workflow ends after these)
        """
        self.name = name
        self.nodes = nodes
        self.edges = edges
        self.entry_point = entry_point
        self.end_nodes = end_nodes or []

    async def run(
        self,
        input_data: dict[str, Any],
        context: WorkflowContext | None = None,
        resume_state: WorkflowState[Any] | None = None,
    ) -> WorkflowState[Any]:
        """Execute the workflow.

        Args:
            input_data: Initial input data
            context: Execution context
            resume_state: State to resume from (for paused workflows)

        Returns:
            Final workflow state
        """
        # Initialize or resume state
        if resume_state:
            state = resume_state
            state.status = WorkflowStatus.RUNNING
            state.paused_at = None
        else:
            state = WorkflowState(
                workflow_name=self.name,
                status=WorkflowStatus.RUNNING,
                data=input_data.copy(),
                initial_input=input_data.copy(),
                started_at=datetime.now(UTC),
            )

        context = context or WorkflowContext(workflow=self)
        context.workflow = self

        # Determine starting node
        current_node = state.current_node or self.entry_point

        while current_node:
            state.current_node = current_node

            # Get node
            node = self.nodes.get(current_node)
            if not node:
                state.status = WorkflowStatus.FAILED
                state.error = f"Node not found: {current_node}"
                break

            # Execute node
            logger.debug(f"Executing node: {current_node}")
            result = await node.execute(state, context)
            state.node_results[current_node] = result
            state.executed_nodes.append(current_node)

            # Handle result
            if result.status == NodeStatus.FAILED:
                state.status = WorkflowStatus.FAILED
                state.error = result.error
                state.failed_node = current_node
                break

            if result.status == NodeStatus.WAITING_APPROVAL:
                state.status = WorkflowStatus.WAITING_INPUT
                state.paused_at = datetime.now(UTC)
                break

            # Determine next node
            if current_node in self.end_nodes:
                current_node = None
            elif isinstance(node, ConditionalNode) and result.output:
                current_node = result.output.get("next_node")
            else:
                next_nodes = self.edges.get(current_node, [])
                current_node = next_nodes[0] if next_nodes else None

        # Finalize
        if state.status == WorkflowStatus.RUNNING:
            state.status = WorkflowStatus.COMPLETED
            state.completed_at = datetime.now(UTC)

        return state

    async def submit_approval(
        self,
        state: WorkflowState[Any],
        request_id: UUID,
        response: str,
        response_data: dict[str, Any] | None = None,
        responded_by: str | None = None,
    ) -> WorkflowState[Any]:
        """Submit approval response and continue workflow.

        Args:
            state: Current workflow state
            request_id: Approval request ID
            response: Approval response (e.g., "approve", "reject")
            response_data: Additional response data
            responded_by: Who responded

        Returns:
            Updated workflow state
        """
        # Find the approval request
        request = None
        for req in state.pending_approvals:
            if req.request_id == request_id:
                request = req
                break

        if not request:
            raise ValueError(f"Approval request not found: {request_id}")

        # Update request
        request.response = response
        request.response_data = response_data
        request.responded_at = datetime.now(UTC)
        request.responded_by = responded_by

        # Update node result
        node_result = state.node_results.get(request.node_name)
        if node_result:
            if response == "approve":
                node_result.status = NodeStatus.APPROVED
            else:
                node_result.status = NodeStatus.REJECTED
            node_result.completed_at = datetime.now(UTC)

        # Remove from pending
        state.pending_approvals.remove(request)

        # Add response data to state
        if response_data:
            state.data.update(response_data)

        # Handle rejection
        if response != "approve":
            state.status = WorkflowStatus.FAILED
            state.error = f"Approval rejected at {request.node_name}"
            return state

        # Continue workflow from next node
        next_nodes = self.edges.get(request.node_name, [])
        if next_nodes:
            state.current_node = next_nodes[0]
            return await self.run({}, context=WorkflowContext(workflow=self), resume_state=state)
        else:
            state.status = WorkflowStatus.COMPLETED
            state.completed_at = datetime.now(UTC)

        return state


class WorkflowBuilder:
    """Builder for creating workflows.

    Provides a fluent API for defining workflow graphs.

    Example:
        workflow = (
            WorkflowBuilder("my_workflow")
            .add_node("start", process_input)
            .add_node("analyze", analyze_data)
            .add_conditional(
                "route",
                lambda s: "positive" if s["score"] > 0 else "negative",
                {"positive": "celebrate", "negative": "investigate"},
            )
            .add_node("celebrate", send_celebration)
            .add_node("investigate", start_investigation)
            .add_edge("start", "analyze")
            .add_edge("analyze", "route")
            .set_entry_point("start")
            .set_end_nodes(["celebrate", "investigate"])
            .compile()
        )
    """

    def __init__(self, name: str) -> None:
        """Initialize builder.

        Args:
            name: Workflow name
        """
        self.name = name
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: dict[str, list[str]] = defaultdict(list)
        self._entry_point: str | None = None
        self._end_nodes: list[str] = []

    def add_node(
        self,
        name: str,
        func: NodeFunc,
        retry_count: int = 0,
    ) -> WorkflowBuilder:
        """Add a function node.

        Args:
            name: Node name
            func: Async function to execute
            retry_count: Number of retries on failure

        Returns:
            Self for chaining
        """
        self._nodes[name] = FunctionNode(name, func, retry_count)
        return self

    def add_human_approval(
        self,
        name: str,
        prompt: str,
        options: list[str] | None = None,
        timeout_seconds: int | None = None,
        context_keys: list[str] | None = None,
    ) -> WorkflowBuilder:
        """Add a human approval node.

        Args:
            name: Node name
            prompt: Approval prompt
            options: Available options
            timeout_seconds: Approval timeout
            context_keys: State keys for context

        Returns:
            Self for chaining
        """
        self._nodes[name] = HumanApprovalNode(
            name, prompt, options, timeout_seconds, context_keys
        )
        return self

    def add_conditional(
        self,
        name: str,
        condition: ConditionFunc,
        branches: dict[str, str],
        default_branch: str | None = None,
    ) -> WorkflowBuilder:
        """Add a conditional routing node.

        Args:
            name: Node name
            condition: Function returning branch name
            branches: Mapping of results to next nodes
            default_branch: Default if result not in branches

        Returns:
            Self for chaining
        """
        self._nodes[name] = ConditionalNode(name, condition, branches, default_branch)
        return self

    def add_parallel(
        self,
        name: str,
        branches: list[str],
        merge_strategy: str = "merge",
    ) -> WorkflowBuilder:
        """Add a parallel execution node.

        Args:
            name: Node name
            branches: Nodes to execute in parallel
            merge_strategy: How to merge results

        Returns:
            Self for chaining
        """
        self._nodes[name] = ParallelNode(name, branches, merge_strategy)
        return self

    def add_edge(self, from_node: str, to_node: str) -> WorkflowBuilder:
        """Add an edge between nodes.

        Args:
            from_node: Source node
            to_node: Target node

        Returns:
            Self for chaining
        """
        self._edges[from_node].append(to_node)
        return self

    def set_entry_point(self, node: str) -> WorkflowBuilder:
        """Set the entry point node.

        Args:
            node: Entry point node name

        Returns:
            Self for chaining
        """
        self._entry_point = node
        return self

    def set_end_nodes(self, nodes: list[str]) -> WorkflowBuilder:
        """Set the end nodes.

        Args:
            nodes: List of terminal node names

        Returns:
            Self for chaining
        """
        self._end_nodes = nodes
        return self

    def compile(self) -> Workflow:
        """Compile the workflow definition.

        Returns:
            Executable Workflow

        Raises:
            ValueError: If workflow is invalid
        """
        if not self._entry_point:
            # Default to first node
            if self._nodes:
                self._entry_point = next(iter(self._nodes))
            else:
                raise ValueError("Workflow must have at least one node")

        if self._entry_point not in self._nodes:
            raise ValueError(f"Entry point not found: {self._entry_point}")

        # Validate edges
        for from_node, to_nodes in self._edges.items():
            if from_node not in self._nodes:
                raise ValueError(f"Edge source not found: {from_node}")
            for to_node in to_nodes:
                if to_node not in self._nodes:
                    raise ValueError(f"Edge target not found: {to_node}")

        return Workflow(
            name=self.name,
            nodes=self._nodes,
            edges=dict(self._edges),
            entry_point=self._entry_point,
            end_nodes=self._end_nodes,
        )


# Convenience functions for common patterns
def human_approval(
    prompt: str,
    options: list[str] | None = None,
    context_keys: list[str] | None = None,
) -> Callable[[str], HumanApprovalNode]:
    """Create a human approval node factory.

    Example:
        builder.add_node("review", human_approval("Please review")("review"))
    """
    def factory(name: str) -> HumanApprovalNode:
        return HumanApprovalNode(name, prompt, options, context_keys=context_keys)
    return factory


def conditional_branch(
    condition: ConditionFunc,
    branches: dict[str, str],
    default: str | None = None,
) -> Callable[[str], ConditionalNode]:
    """Create a conditional node factory.

    Example:
        builder.add_node(
            "route",
            conditional_branch(
                lambda s: "yes" if s["approved"] else "no",
                {"yes": "process", "no": "reject"},
            )("route")
        )
    """
    def factory(name: str) -> ConditionalNode:
        return ConditionalNode(name, condition, branches, default)
    return factory


def parallel_branches(
    branches: list[str],
    merge: str = "merge",
) -> Callable[[str], ParallelNode]:
    """Create a parallel node factory.

    Example:
        builder.add_node(
            "parallel_analysis",
            parallel_branches(["analyze_text", "analyze_images"])("parallel_analysis")
        )
    """
    def factory(name: str) -> ParallelNode:
        return ParallelNode(name, branches, merge)
    return factory
