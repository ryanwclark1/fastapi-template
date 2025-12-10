"""Tests for the AI agent workflow system."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from example_service.infra.ai.agents.workflows import (
    ConditionalNode,
    FunctionNode,
    HumanApprovalNode,
    HumanApprovalRequest,
    NodeResult,
    NodeStatus,
    ParallelNode,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowState,
    WorkflowStatus,
    conditional_branch,
    human_approval,
    parallel_branches,
)


class TestNodeStatus:
    """Tests for NodeStatus enum."""

    def test_status_values(self) -> None:
        """Test status enum values."""
        assert NodeStatus.PENDING.value == "pending"
        assert NodeStatus.RUNNING.value == "running"
        assert NodeStatus.COMPLETED.value == "completed"
        assert NodeStatus.FAILED.value == "failed"
        assert NodeStatus.WAITING_APPROVAL.value == "waiting_approval"


class TestWorkflowStatus:
    """Tests for WorkflowStatus enum."""

    def test_status_values(self) -> None:
        """Test workflow status values."""
        assert WorkflowStatus.PENDING.value == "pending"
        assert WorkflowStatus.RUNNING.value == "running"
        assert WorkflowStatus.PAUSED.value == "paused"
        assert WorkflowStatus.WAITING_INPUT.value == "waiting_input"
        assert WorkflowStatus.COMPLETED.value == "completed"
        assert WorkflowStatus.FAILED.value == "failed"


class TestHumanApprovalRequest:
    """Tests for HumanApprovalRequest."""

    def test_create_request(self) -> None:
        """Test creating approval request."""
        request = HumanApprovalRequest(
            node_name="review",
            prompt="Please review this",
            options=["approve", "reject", "needs_changes"],
        )

        assert request.request_id is not None
        assert request.node_name == "review"
        assert request.prompt == "Please review this"
        assert len(request.options) == 3
        assert request.response is None

    def test_default_options(self) -> None:
        """Test default approval options."""
        request = HumanApprovalRequest(
            node_name="test",
            prompt="Test",
        )

        assert request.options == ["approve", "reject"]


class TestNodeResult:
    """Tests for NodeResult."""

    def test_successful_result(self) -> None:
        """Test successful node result."""
        result = NodeResult(
            node_name="process",
            status=NodeStatus.COMPLETED,
            output={"processed": True},
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

        assert result.node_name == "process"
        assert result.status == NodeStatus.COMPLETED
        assert result.output["processed"] is True
        assert result.error is None

    def test_failed_result(self) -> None:
        """Test failed node result."""
        result = NodeResult(
            node_name="process",
            status=NodeStatus.FAILED,
            error="Something went wrong",
        )

        assert result.status == NodeStatus.FAILED
        assert result.error == "Something went wrong"

    def test_duration_calculation(self) -> None:
        """Test duration calculation."""
        start = datetime.now(UTC)
        end = start.replace(second=start.second + 1)

        result = NodeResult(
            node_name="test",
            status=NodeStatus.COMPLETED,
            started_at=start,
            completed_at=end,
        )

        assert result.duration_ms is not None
        assert result.duration_ms >= 1000

    def test_duration_without_times(self) -> None:
        """Test duration when times not set."""
        result = NodeResult(
            node_name="test",
            status=NodeStatus.COMPLETED,
        )

        assert result.duration_ms is None


class TestWorkflowState:
    """Tests for WorkflowState."""

    def test_create_state(self) -> None:
        """Test creating workflow state."""
        state = WorkflowState(
            workflow_name="test_workflow",
            data={"input": "value"},
        )

        assert state.workflow_id is not None
        assert state.workflow_name == "test_workflow"
        assert state.status == WorkflowStatus.PENDING
        assert state.data["input"] == "value"

    def test_state_serialization(self) -> None:
        """Test state serialization."""
        state = WorkflowState(
            workflow_name="test",
            status=WorkflowStatus.RUNNING,
            data={"key": "value"},
            started_at=datetime.now(UTC),
        )

        d = state.to_dict()

        assert d["workflow_name"] == "test"
        assert d["status"] == "running"
        assert d["data"]["key"] == "value"
        assert "started_at" in d


class TestFunctionNode:
    """Tests for FunctionNode."""

    @pytest.mark.anyio
    async def test_execute_success(self) -> None:
        """Test successful function execution."""

        async def process(data: dict[str, Any]) -> dict[str, Any]:
            return {"result": data.get("input", 0) * 2}

        node = FunctionNode("process", process)
        state = WorkflowState(data={"input": 5})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.status == NodeStatus.COMPLETED
        assert result.output["result"] == 10
        assert state.data["result"] == 10  # State updated

    @pytest.mark.anyio
    async def test_execute_failure(self) -> None:
        """Test function execution failure."""

        async def failing_process(data: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("Test error")

        node = FunctionNode("process", failing_process)
        state = WorkflowState(data={})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.status == NodeStatus.FAILED
        assert "Test error" in result.error  # type: ignore

    @pytest.mark.anyio
    async def test_execute_with_retry(self) -> None:
        """Test function execution with retry."""
        call_count = 0

        async def flaky_process(data: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Temporary failure")
            return {"success": True}

        node = FunctionNode("process", flaky_process, retry_count=3)
        state = WorkflowState(data={})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.status == NodeStatus.COMPLETED
        assert call_count == 3


class TestHumanApprovalNode:
    """Tests for HumanApprovalNode."""

    @pytest.mark.anyio
    async def test_execute_creates_request(self) -> None:
        """Test that execution creates approval request."""
        node = HumanApprovalNode(
            name="review",
            prompt="Please review",
            options=["approve", "reject"],
            context_keys=["summary"],
        )
        state = WorkflowState(data={"summary": "Test summary"})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.status == NodeStatus.WAITING_APPROVAL
        assert result.approval_request is not None
        assert result.approval_request.prompt == "Please review"
        assert result.approval_request.context["summary"] == "Test summary"
        assert len(state.pending_approvals) == 1

    @pytest.mark.anyio
    async def test_approval_handler_called(self) -> None:
        """Test that approval handler is called."""
        handler_called = False
        received_request = None

        async def approval_handler(request: HumanApprovalRequest) -> None:
            nonlocal handler_called, received_request
            handler_called = True
            received_request = request

        node = HumanApprovalNode(name="review", prompt="Test")
        state = WorkflowState(data={})
        context = WorkflowContext(
            workflow=None,  # type: ignore
            approval_handler=approval_handler,
        )

        await node.execute(state, context)

        assert handler_called is True
        assert received_request is not None
        assert received_request.prompt == "Test"


class TestConditionalNode:
    """Tests for ConditionalNode."""

    @pytest.mark.anyio
    async def test_execute_routes_correctly(self) -> None:
        """Test conditional routing."""

        def condition(data: dict[str, Any]) -> str:
            return "positive" if data.get("score", 0) > 0 else "negative"

        node = ConditionalNode(
            name="route",
            condition=condition,
            branches={"positive": "celebrate", "negative": "investigate"},
        )
        state = WorkflowState(data={"score": 10})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.status == NodeStatus.COMPLETED
        assert result.output["branch"] == "positive"
        assert result.output["next_node"] == "celebrate"

    @pytest.mark.anyio
    async def test_execute_with_async_condition(self) -> None:
        """Test with async condition."""

        async def async_condition(data: dict[str, Any]) -> str:
            return "approved" if data.get("valid") else "rejected"

        node = ConditionalNode(
            name="route",
            condition=async_condition,
            branches={"approved": "process", "rejected": "end"},
        )
        state = WorkflowState(data={"valid": True})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.output["next_node"] == "process"

    @pytest.mark.anyio
    async def test_execute_uses_default_branch(self) -> None:
        """Test default branch fallback."""

        def condition(data: dict[str, Any]) -> str:
            return "unknown"

        node = ConditionalNode(
            name="route",
            condition=condition,
            branches={"known": "process"},
            default_branch="fallback",
        )
        state = WorkflowState(data={})
        context = WorkflowContext(workflow=None)  # type: ignore

        result = await node.execute(state, context)

        assert result.output["next_node"] == "fallback"


class TestParallelNode:
    """Tests for ParallelNode."""

    @pytest.mark.anyio
    async def test_execute_parallel_branches(self) -> None:
        """Test parallel execution."""

        async def branch_a(data: dict[str, Any]) -> dict[str, Any]:
            return {"a_result": "from_a"}

        async def branch_b(data: dict[str, Any]) -> dict[str, Any]:
            return {"b_result": "from_b"}

        # Create a workflow with the branches
        nodes = {
            "branch_a": FunctionNode("branch_a", branch_a),
            "branch_b": FunctionNode("branch_b", branch_b),
        }
        workflow = Workflow(
            name="test",
            nodes=nodes,
            edges={},
            entry_point="branch_a",
        )

        node = ParallelNode(
            name="parallel",
            branches=["branch_a", "branch_b"],
            merge_strategy="merge",
        )
        state = WorkflowState(data={})
        context = WorkflowContext(workflow=workflow)

        result = await node.execute(state, context)

        assert result.status == NodeStatus.COMPLETED
        assert len(result.output) == 2

    @pytest.mark.anyio
    async def test_missing_branch_fails(self) -> None:
        """Test missing branch fails."""
        workflow = Workflow(
            name="test",
            nodes={},
            edges={},
            entry_point="start",
        )

        node = ParallelNode(
            name="parallel",
            branches=["missing_branch"],
        )
        state = WorkflowState(data={})
        context = WorkflowContext(workflow=workflow)

        result = await node.execute(state, context)

        assert result.status == NodeStatus.FAILED
        assert "missing_branch" in result.error  # type: ignore


class TestWorkflow:
    """Tests for Workflow execution."""

    @pytest.fixture
    def simple_workflow(self) -> Workflow:
        """Create a simple workflow for testing."""

        async def step1(data: dict[str, Any]) -> dict[str, Any]:
            return {"step1_done": True}

        async def step2(data: dict[str, Any]) -> dict[str, Any]:
            return {"step2_done": True, "result": "complete"}

        return (
            WorkflowBuilder("simple")
            .add_node("step1", step1)
            .add_node("step2", step2)
            .add_edge("step1", "step2")
            .set_entry_point("step1")
            .set_end_nodes(["step2"])
            .compile()
        )

    @pytest.mark.anyio
    async def test_run_simple_workflow(self, simple_workflow: Workflow) -> None:
        """Test running simple workflow."""
        state = await simple_workflow.run({"input": "test"})

        assert state.status == WorkflowStatus.COMPLETED
        assert state.data["step1_done"] is True
        assert state.data["step2_done"] is True
        assert len(state.executed_nodes) == 2

    @pytest.mark.anyio
    async def test_run_workflow_failure(self) -> None:
        """Test workflow failure handling."""

        async def failing_step(data: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Step failed")

        workflow = (
            WorkflowBuilder("failing")
            .add_node("fail", failing_step)
            .set_entry_point("fail")
            .compile()
        )

        state = await workflow.run({})

        assert state.status == WorkflowStatus.FAILED
        assert state.error is not None
        assert state.failed_node == "fail"

    @pytest.mark.anyio
    async def test_run_workflow_with_conditional(self) -> None:
        """Test workflow with conditional routing."""

        async def process(data: dict[str, Any]) -> dict[str, Any]:
            return {"processed": True}

        async def good_path(data: dict[str, Any]) -> dict[str, Any]:
            return {"path": "good"}

        async def bad_path(data: dict[str, Any]) -> dict[str, Any]:
            return {"path": "bad"}

        workflow = (
            WorkflowBuilder("conditional")
            .add_node("process", process)
            .add_conditional(
                "route",
                lambda d: "good" if d.get("score", 0) > 50 else "bad",
                {"good": "good_path", "bad": "bad_path"},
            )
            .add_node("good_path", good_path)
            .add_node("bad_path", bad_path)
            .add_edge("process", "route")
            .set_entry_point("process")
            .set_end_nodes(["good_path", "bad_path"])
            .compile()
        )

        # Test good path
        state = await workflow.run({"score": 80})
        assert state.data["path"] == "good"

        # Test bad path
        state = await workflow.run({"score": 30})
        assert state.data["path"] == "bad"

    @pytest.mark.anyio
    async def test_workflow_pauses_for_approval(self) -> None:
        """Test workflow pauses for human approval."""

        async def prepare(data: dict[str, Any]) -> dict[str, Any]:
            return {"prepared": True}

        workflow = (
            WorkflowBuilder("approval")
            .add_node("prepare", prepare)
            .add_human_approval("review", "Please review")
            .add_edge("prepare", "review")
            .set_entry_point("prepare")
            .compile()
        )

        state = await workflow.run({"input": "test"})

        assert state.status == WorkflowStatus.WAITING_INPUT
        assert len(state.pending_approvals) == 1
        assert state.pending_approvals[0].prompt == "Please review"

    @pytest.mark.anyio
    async def test_submit_approval_continues(self) -> None:
        """Test submitting approval continues workflow."""

        async def prepare(data: dict[str, Any]) -> dict[str, Any]:
            return {"prepared": True}

        async def finalize(data: dict[str, Any]) -> dict[str, Any]:
            return {"finalized": True}

        workflow = (
            WorkflowBuilder("approval")
            .add_node("prepare", prepare)
            .add_human_approval("review", "Please review")
            .add_node("finalize", finalize)
            .add_edge("prepare", "review")
            .add_edge("review", "finalize")
            .set_entry_point("prepare")
            .set_end_nodes(["finalize"])
            .compile()
        )

        # Run until approval
        state = await workflow.run({})
        assert state.status == WorkflowStatus.WAITING_INPUT

        # Submit approval
        request_id = state.pending_approvals[0].request_id
        state = await workflow.submit_approval(
            state,
            request_id,
            "approve",
            response_data={"approved_by": "admin"},
        )

        assert state.status == WorkflowStatus.COMPLETED
        assert state.data["finalized"] is True
        assert state.data["approved_by"] == "admin"

    @pytest.mark.anyio
    async def test_submit_rejection_fails(self) -> None:
        """Test submitting rejection fails workflow."""

        async def prepare(data: dict[str, Any]) -> dict[str, Any]:
            return {"prepared": True}

        workflow = (
            WorkflowBuilder("approval")
            .add_node("prepare", prepare)
            .add_human_approval("review", "Please review")
            .add_edge("prepare", "review")
            .set_entry_point("prepare")
            .compile()
        )

        state = await workflow.run({})
        request_id = state.pending_approvals[0].request_id

        state = await workflow.submit_approval(
            state,
            request_id,
            "reject",
        )

        assert state.status == WorkflowStatus.FAILED
        assert "rejected" in state.error.lower()  # type: ignore


class TestWorkflowBuilder:
    """Tests for WorkflowBuilder."""

    def test_build_simple_workflow(self) -> None:
        """Test building simple workflow."""

        async def process(data: dict[str, Any]) -> dict[str, Any]:
            return {}

        workflow = (
            WorkflowBuilder("test")
            .add_node("process", process)
            .set_entry_point("process")
            .compile()
        )

        assert workflow.name == "test"
        assert "process" in workflow.nodes
        assert workflow.entry_point == "process"

    def test_build_with_edges(self) -> None:
        """Test building workflow with edges."""

        async def step(data: dict[str, Any]) -> dict[str, Any]:
            return {}

        workflow = (
            WorkflowBuilder("test")
            .add_node("a", step)
            .add_node("b", step)
            .add_node("c", step)
            .add_edge("a", "b")
            .add_edge("b", "c")
            .set_entry_point("a")
            .compile()
        )

        assert workflow.edges["a"] == ["b"]
        assert workflow.edges["b"] == ["c"]

    def test_build_missing_entry_point(self) -> None:
        """Test that missing entry point uses first node."""

        async def process(data: dict[str, Any]) -> dict[str, Any]:
            return {}

        workflow = WorkflowBuilder("test").add_node("only_node", process).compile()

        assert workflow.entry_point == "only_node"

    def test_build_invalid_entry_point(self) -> None:
        """Test that invalid entry point raises error."""

        async def process(data: dict[str, Any]) -> dict[str, Any]:
            return {}

        with pytest.raises(ValueError, match="Entry point not found"):
            (
                WorkflowBuilder("test")
                .add_node("process", process)
                .set_entry_point("missing")
                .compile()
            )

    def test_build_invalid_edge(self) -> None:
        """Test that invalid edge raises error."""

        async def process(data: dict[str, Any]) -> dict[str, Any]:
            return {}

        with pytest.raises(ValueError, match="Edge target not found"):
            (
                WorkflowBuilder("test")
                .add_node("a", process)
                .add_edge("a", "missing")
                .compile()
            )


class TestConvenienceFunctions:
    """Tests for convenience factory functions."""

    def test_human_approval_factory(self) -> None:
        """Test human_approval factory."""
        factory = human_approval("Please approve", options=["yes", "no"])
        node = factory("review")

        assert isinstance(node, HumanApprovalNode)
        assert node.name == "review"
        assert node.prompt == "Please approve"
        assert node.options == ["yes", "no"]

    def test_conditional_branch_factory(self) -> None:
        """Test conditional_branch factory."""
        factory = conditional_branch(
            lambda d: "yes",
            {"yes": "next", "no": "end"},
            default="end",
        )
        node = factory("route")

        assert isinstance(node, ConditionalNode)
        assert node.name == "route"
        assert node.default_branch == "end"

    def test_parallel_branches_factory(self) -> None:
        """Test parallel_branches factory."""
        factory = parallel_branches(["a", "b", "c"], merge="all")
        node = factory("parallel")

        assert isinstance(node, ParallelNode)
        assert node.name == "parallel"
        assert node.branches == ["a", "b", "c"]
        assert node.merge_strategy == "all"
