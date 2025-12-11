"""Pydantic schemas for AI agent management.

This module provides request/response schemas for the agent configuration API,
including agent CRUD, templates, tool management, testing, and monitoring.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
import uuid

from pydantic import BaseModel, Field

from example_service.utils.runtime_dependencies import require_runtime_dependency

require_runtime_dependency(dt.datetime, uuid.UUID)


# ============================================================================
# Tool Configuration Schemas
# ============================================================================


class ToolConfigSchema(BaseModel):
    """Tool configuration for an agent."""

    name: str = Field(..., description="Tool identifier")
    enabled: bool = Field(True, description="Whether tool is active")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Tool-specific configuration",
    )
    requires_confirmation: bool = Field(
        False, description="Require human confirmation before execution",
    )
    timeout_seconds: int | None = Field(None, gt=0, le=300)


class AvailableToolResponse(BaseModel):
    """Information about an available tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    is_dangerous: bool = False
    requires_confirmation: bool = False
    category: str | None = None


class ToolValidationRequest(BaseModel):
    """Validate tool configuration."""

    tools: list[ToolConfigSchema]


class ToolValidationResponse(BaseModel):
    """Tool validation results."""

    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# Agent CRUD Schemas
# ============================================================================


class AgentCreate(BaseModel):
    """Create custom agent from scratch."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    agent_type: str = Field(
        ..., description="Agent category (rag|code_generation|data_analysis|etc)",
    )
    system_prompt: str = Field(..., min_length=10, max_length=10000)

    # LLM Configuration
    model: str = Field("gpt-4o", description="LLM model identifier")
    provider: str = Field("openai", description="LLM provider")
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, gt=0, le=100000)

    # Tool Configuration
    tools: list[ToolConfigSchema] | None = Field(None, description="Tool configurations")

    # Additional Configuration
    config: dict[str, Any] | None = Field(
        None, description="Agent-specific configuration",
    )

    # Execution Limits
    max_iterations: int | None = Field(None, gt=0, le=100)
    timeout_seconds: int | None = Field(None, gt=0, le=3600)
    max_cost_usd: float | None = Field(None, gt=0)

    # Metadata
    tags: list[str] | None = Field(None, max_length=20)
    metadata: dict[str, Any] | None = None


class AgentUpdate(BaseModel):
    """Update agent configuration (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    system_prompt: str | None = Field(None, min_length=10, max_length=10000)
    model: str | None = None
    provider: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, gt=0, le=100000)
    tools: list[ToolConfigSchema] | None = None
    config: dict[str, Any] | None = None
    max_iterations: int | None = Field(None, gt=0, le=100)
    timeout_seconds: int | None = Field(None, gt=0, le=3600)
    max_cost_usd: float | None = Field(None, gt=0)
    tags: list[str] | None = None
    is_active: bool | None = None
    bump_version: bool = Field(
        False, description="Increment version number on update",
    )


class AgentResponse(BaseModel):
    """Agent details response with statistics."""

    # Core fields
    id: uuid.UUID
    agent_key: str
    name: str
    description: str | None
    tenant_id: str | None
    agent_type: str
    is_prebuilt: bool
    prebuilt_template: str | None

    # LLM Configuration
    model: str
    provider: str
    temperature: float | None
    max_tokens: int | None
    system_prompt: str

    # Tool & Config
    tools: dict[str, Any] | None
    config: dict[str, Any] | None

    # Limits
    max_iterations: int | None
    timeout_seconds: int | None
    max_cost_usd: float | None

    # Lifecycle
    is_active: bool
    version: str
    tags: list[str] | None
    metadata_json: dict[str, Any] | None

    # Audit
    created_at: dt.datetime
    updated_at: dt.datetime
    created_by_id: uuid.UUID | None
    updated_by_id: uuid.UUID | None

    # Execution Statistics (computed, optional)
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    avg_duration_seconds: float = 0.0
    avg_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    last_run_at: dt.datetime | None = None

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    """Paginated list of agents."""

    items: list[AgentResponse]
    total: int
    page: int
    limit: int
    has_next: bool


class AgentCloneRequest(BaseModel):
    """Clone agent with customizations."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    customizations: dict[str, Any] = Field(
        default_factory=dict, description="Fields to override from source agent",
    )


# ============================================================================
# Template Schemas
# ============================================================================


class AgentTemplateResponse(BaseModel):
    """Prebuilt template information."""

    name: str
    display_name: str
    description: str
    agent_type: str
    default_model: str
    default_provider: str
    default_temperature: float
    available_tools: list[str]
    use_cases: list[str]
    sample_prompts: list[str]
    configuration_schema: dict[str, Any]


class CreateFromTemplateRequest(BaseModel):
    """Create agent from template."""

    template_name: str = Field(..., description="Template identifier")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    customizations: dict[str, Any] = Field(
        default_factory=dict, description="Override template defaults",
    )


# ============================================================================
# Testing & Validation Schemas
# ============================================================================


class AgentTestRequest(BaseModel):
    """Test agent with sample input."""

    input_data: dict[str, Any] = Field(..., description="Test input for the agent")
    save_result: bool = Field(False, description="Save test result for history")
    runtime_overrides: dict[str, Any] | None = None


class AgentTestResponse(BaseModel):
    """Test execution results."""

    test_id: uuid.UUID
    success: bool
    output_data: dict[str, Any] | None
    error_message: str | None
    execution_time_seconds: float
    cost_usd: float
    tokens_used: int
    steps_executed: int
    warnings: list[str] = Field(default_factory=list)
    tested_at: dt.datetime


class AgentValidationResponse(BaseModel):
    """Configuration validation results."""

    valid: bool
    errors: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    suggestions: list[dict[str, str]] = Field(default_factory=list)


class AgentDryRunRequest(BaseModel):
    """Dry-run request (no DB persistence)."""

    input_data: dict[str, Any]
    runtime_overrides: dict[str, Any] | None = None


# ============================================================================
# Execution Schemas
# ============================================================================


class AgentExecuteRequest(BaseModel):
    """Execute agent with input."""

    input_data: dict[str, Any]
    run_name: str | None = Field(None, max_length=255)
    runtime_overrides: dict[str, Any] | None = Field(
        None, description="Override agent config for this run only",
    )
    async_execution: bool = Field(
        False, description="Return immediately, execute in background",
    )


class AgentExecuteResponse(BaseModel):
    """Agent execution result."""

    run_id: uuid.UUID
    agent_id: uuid.UUID
    status: str  # AgentRunStatus
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: dt.datetime
    completed_at: dt.datetime | None
    execution_time_seconds: float | None
    cost_usd: float = 0.0
    tokens_used: int = 0


# ============================================================================
# Statistics & Monitoring Schemas
# ============================================================================


class AgentStatsResponse(BaseModel):
    """Performance statistics for an agent."""

    agent_id: uuid.UUID
    time_period_days: int = 30
    total_runs: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int
    avg_duration_seconds: float
    p50_duration_seconds: float
    p95_duration_seconds: float
    p99_duration_seconds: float
    total_cost_usd: float
    avg_cost_per_run_usd: float
    total_tokens: int
    avg_tokens_per_run: int
    success_rate: float
    error_breakdown: dict[str, int]
    runs_by_day: list[dict[str, Any]]


class AgentCostResponse(BaseModel):
    """Cost breakdown for an agent."""

    agent_id: uuid.UUID
    time_period_days: int = 30
    total_cost_usd: float
    cost_by_model: dict[str, float]
    cost_by_day: list[dict[str, Any]]
    projected_monthly_cost_usd: float
    cost_per_run_trend: list[dict[str, Any]]


# ============================================================================
# Status Schemas
# ============================================================================


class AgentStatusResponse(BaseModel):
    """Agent health and status."""

    agent_id: uuid.UUID
    is_active: bool
    is_healthy: bool
    health_checks: dict[str, bool]
    last_successful_run: dt.datetime | None
    last_error: str | None
    configuration_valid: bool
    tools_available: bool
    provider_accessible: bool
