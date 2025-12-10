"""add_ai_agent_tables

Revision ID: add_ai_agent_tables
Revises: 02aeb38ec26e
Create Date: 2025-12-09 00:01:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_ai_agent_tables"
down_revision: str | None = "02aeb38ec26e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create new enums for AI agent framework
    sa.Enum(
        "pending",
        "running",
        "paused",
        "waiting_input",
        "completed",
        "failed",
        "cancelled",
        "timeout",
        name="aiagentrunstatus",
    ).create(op.get_bind())

    sa.Enum(
        "llm_call",
        "tool_call",
        "human_input",
        "checkpoint",
        "branch",
        "parallel",
        "subagent",
        name="aiagentsteptype",
    ).create(op.get_bind())

    sa.Enum(
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
        "retrying",
        name="aiagentstepstatus",
    ).create(op.get_bind())

    sa.Enum(
        "system",
        "user",
        "assistant",
        "tool",
        "function",
        name="aiagentmessagerole",
    ).create(op.get_bind())

    # Create ai_agent_runs table
    op.create_table(
        "ai_agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column(
            "agent_type",
            sa.String(length=255),
            nullable=False,
            comment="Type/name of the agent (e.g., 'research_agent', 'code_review')",
        ),
        sa.Column(
            "agent_version",
            sa.String(length=50),
            nullable=False,
            server_default="1.0.0",
            comment="Version of the agent definition",
        ),
        sa.Column(
            "run_name",
            sa.String(length=255),
            nullable=True,
            comment="Human-readable name for the run",
        ),
        sa.Column(
            "parent_run_id",
            sa.UUID(),
            nullable=True,
            comment="Parent run ID if this is a sub-agent run",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "paused",
                "waiting_input",
                "completed",
                "failed",
                "cancelled",
                "timeout",
                name="aiagentrunstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "status_message",
            sa.Text(),
            nullable=True,
            comment="Human-readable status message",
        ),
        sa.Column(
            "input_data",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Input data for the agent",
        ),
        sa.Column(
            "output_data",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Final output from the agent",
        ),
        sa.Column(
            "config",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Agent configuration (model, temperature, tools, etc.)",
        ),
        sa.Column(
            "state",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Current agent state (for pause/resume)",
        ),
        sa.Column(
            "context",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Shared context data between steps",
        ),
        sa.Column(
            "current_step",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Current step number",
        ),
        sa.Column(
            "total_steps",
            sa.Integer(),
            nullable=True,
            comment="Total expected steps (if known)",
        ),
        sa.Column(
            "progress_percent",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="Progress percentage 0-100",
        ),
        sa.Column(
            "total_cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="Total cost in USD",
        ),
        sa.Column(
            "total_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total input tokens consumed",
        ),
        sa.Column(
            "total_output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total output tokens generated",
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of retry attempts",
        ),
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
            server_default="3",
            comment="Maximum retry attempts",
        ),
        sa.Column(
            "last_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of last retry attempt",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Error message if failed",
        ),
        sa.Column(
            "error_code",
            sa.String(length=100),
            nullable=True,
            comment="Error code for programmatic handling",
        ),
        sa.Column(
            "error_details",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Detailed error information (stack trace, etc.)",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When execution started",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When execution completed",
        ),
        sa.Column(
            "paused_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When execution was paused",
        ),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=True,
            comment="Timeout in seconds",
        ),
        sa.Column(
            "tags",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Tags for filtering/categorization",
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Additional metadata",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["ai_agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_agent_runs_tenant_status",
        "ai_agent_runs",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_ai_agent_runs_tenant_agent",
        "ai_agent_runs",
        ["tenant_id", "agent_type"],
    )
    op.create_index(
        "ix_ai_agent_runs_created_at",
        "ai_agent_runs",
        ["created_at"],
    )
    op.create_index(
        "ix_ai_agent_runs_parent",
        "ai_agent_runs",
        ["parent_run_id"],
    )
    op.create_index(
        "ix_ai_agent_runs_status_created",
        "ai_agent_runs",
        ["status", "created_at"],
    )

    # Create ai_agent_steps table
    op.create_table(
        "ai_agent_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column(
            "step_number",
            sa.Integer(),
            nullable=False,
            comment="Sequential step number within run",
        ),
        sa.Column(
            "step_type",
            postgresql.ENUM(
                "llm_call",
                "tool_call",
                "human_input",
                "checkpoint",
                "branch",
                "parallel",
                "subagent",
                name="aiagentsteptype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "step_name",
            sa.String(length=255),
            nullable=False,
            comment="Descriptive name for the step",
        ),
        sa.Column(
            "parent_step_id",
            sa.UUID(),
            nullable=True,
            comment="Parent step ID for nested/parallel steps",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "completed",
                "failed",
                "skipped",
                "retrying",
                name="aiagentstepstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "input_data",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Input data for the step",
        ),
        sa.Column(
            "output_data",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Output data from the step",
        ),
        sa.Column(
            "provider_name",
            sa.String(length=100),
            nullable=True,
            comment="Provider used (openai, anthropic, etc.)",
        ),
        sa.Column(
            "model_name",
            sa.String(length=255),
            nullable=True,
            comment="Model used for LLM calls",
        ),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "duration_ms",
            sa.Float(),
            nullable=True,
            comment="Step duration in milliseconds",
        ),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("is_retryable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "metadata_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_step_id"],
            ["ai_agent_steps.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_steps_run", "ai_agent_steps", ["run_id"])
    op.create_index(
        "ix_ai_agent_steps_run_step",
        "ai_agent_steps",
        ["run_id", "step_number"],
    )
    op.create_index("ix_ai_agent_steps_status", "ai_agent_steps", ["status"])

    # Create ai_agent_messages table
    op.create_table(
        "ai_agent_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column(
            "step_id",
            sa.UUID(),
            nullable=True,
            comment="Step that generated this message",
        ),
        sa.Column(
            "sequence_number",
            sa.Integer(),
            nullable=False,
            comment="Order in conversation",
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "system",
                "user",
                "assistant",
                "tool",
                "function",
                name="aiagentmessagerole",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=True,
            comment="Message text content",
        ),
        sa.Column(
            "content_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Structured content (for multi-modal or tool results)",
        ),
        sa.Column(
            "function_name",
            sa.String(length=255),
            nullable=True,
            comment="Function name for function calls",
        ),
        sa.Column(
            "function_args",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Function arguments",
        ),
        sa.Column(
            "tool_call_id",
            sa.String(length=255),
            nullable=True,
            comment="Tool call ID for correlation",
        ),
        sa.Column(
            "token_count",
            sa.Integer(),
            nullable=True,
            comment="Token count for this message",
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["ai_agent_steps.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_messages_run", "ai_agent_messages", ["run_id"])
    op.create_index(
        "ix_ai_agent_messages_run_seq",
        "ai_agent_messages",
        ["run_id", "sequence_number"],
    )

    # Create ai_agent_tool_calls table
    op.create_table(
        "ai_agent_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=True),
        sa.Column(
            "tool_call_id",
            sa.String(length=255),
            nullable=False,
            comment="Unique tool call ID from LLM",
        ),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column(
            "tool_args",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "result",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Tool execution result",
        ),
        sa.Column(
            "result_text",
            sa.Text(),
            nullable=True,
            comment="Text representation of result",
        ),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["ai_agent_steps.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_tool_calls_run", "ai_agent_tool_calls", ["run_id"])
    op.create_index("ix_ai_agent_tool_calls_tool", "ai_agent_tool_calls", ["tool_name"])
    op.create_index(
        "ix_ai_agent_tool_calls_call_id",
        "ai_agent_tool_calls",
        ["tool_call_id"],
    )

    # Create ai_agent_checkpoints table
    op.create_table(
        "ai_agent_checkpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column(
            "checkpoint_name",
            sa.String(length=255),
            nullable=False,
            comment="Human-readable checkpoint name",
        ),
        sa.Column(
            "step_number",
            sa.Integer(),
            nullable=False,
            comment="Step number at checkpoint",
        ),
        sa.Column(
            "state_snapshot",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Agent state at checkpoint",
        ),
        sa.Column(
            "context_snapshot",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Context data at checkpoint",
        ),
        sa.Column(
            "messages_snapshot",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="Conversation messages at checkpoint",
        ),
        sa.Column(
            "is_automatic",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Whether checkpoint was auto-created",
        ),
        sa.Column(
            "trigger_reason",
            sa.String(length=255),
            nullable=True,
            comment="Reason for checkpoint creation",
        ),
        sa.Column(
            "is_valid",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Whether checkpoint is valid for resume",
        ),
        sa.Column(
            "invalidated_reason",
            sa.String(length=255),
            nullable=True,
            comment="Reason if checkpoint was invalidated",
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_agent_checkpoints_run",
        "ai_agent_checkpoints",
        ["run_id"],
    )
    op.create_index(
        "ix_ai_agent_checkpoints_run_step",
        "ai_agent_checkpoints",
        ["run_id", "step_number"],
    )
    op.create_index(
        "ix_ai_agent_checkpoints_valid",
        "ai_agent_checkpoints",
        ["run_id", "is_valid"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop tables in reverse order
    op.drop_table("ai_agent_checkpoints")
    op.drop_table("ai_agent_tool_calls")
    op.drop_table("ai_agent_messages")
    op.drop_table("ai_agent_steps")
    op.drop_table("ai_agent_runs")

    # Drop enums
    sa.Enum(name="aiagentmessagerole").drop(op.get_bind())
    sa.Enum(name="aiagentstepstatus").drop(op.get_bind())
    sa.Enum(name="aiagentsteptype").drop(op.get_bind())
    sa.Enum(name="aiagentrunstatus").drop(op.get_bind())
