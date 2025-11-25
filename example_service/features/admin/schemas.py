"""Pydantic schemas for admin API endpoints.

This module defines the request/response models for task observability endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskExecutionResponse(BaseModel):
    """Response model for a task execution record.

    Contains full details about a completed or running task execution.
    """

    task_id: str = Field(..., description="Unique identifier for this task execution")
    task_name: str = Field(..., description="Name of the task function")
    status: Literal["running", "success", "failure"] = Field(
        ..., description="Current status of the task"
    )
    started_at: datetime = Field(..., description="When the task started executing")
    finished_at: datetime | None = Field(
        None, description="When the task finished (null if still running)"
    )
    duration_ms: int | None = Field(
        None, description="Execution duration in milliseconds"
    )
    return_value: Any | None = Field(
        None, description="Task return value (success only)"
    )
    error_message: str | None = Field(
        None, description="Error message (failure only)"
    )
    error_type: str | None = Field(
        None, description="Exception type name (failure only)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "task_id": "abc123-def456",
                    "task_name": "backup_database",
                    "status": "success",
                    "started_at": "2024-01-15T02:00:00Z",
                    "finished_at": "2024-01-15T02:00:45Z",
                    "duration_ms": 45000,
                    "return_value": {"backup_path": "/var/backups/db.sql.gz"},
                    "error_message": None,
                    "error_type": None,
                }
            ]
        }
    }


class RunningTaskResponse(BaseModel):
    """Response model for a currently running task.

    Contains information about a task that is currently executing.
    """

    task_id: str = Field(..., description="Unique identifier for this task execution")
    task_name: str = Field(..., description="Name of the task function")
    started_at: datetime = Field(..., description="When the task started executing")
    running_for_ms: int = Field(
        ..., description="How long the task has been running (milliseconds)"
    )
    worker_id: str | None = Field(
        None, description="Identifier of the worker executing the task"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "task_id": "xyz789",
                    "task_name": "export_data_csv",
                    "started_at": "2024-01-15T02:05:00Z",
                    "running_for_ms": 30000,
                    "worker_id": None,
                }
            ]
        }
    }


class TaskStatsResponse(BaseModel):
    """Response model for task execution statistics.

    Provides aggregate statistics about task executions over the last 24 hours.
    """

    total_24h: int = Field(
        ..., description="Total number of task executions in the last 24 hours"
    )
    success_count: int = Field(
        ..., description="Number of successful task executions"
    )
    failure_count: int = Field(
        ..., description="Number of failed task executions"
    )
    running_count: int = Field(
        ..., description="Number of currently running tasks"
    )
    by_task_name: dict[str, int] = Field(
        ..., description="Execution count by task name"
    )
    avg_duration_ms: float | None = Field(
        None, description="Average execution duration in milliseconds"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "total_24h": 1440,
                    "success_count": 1430,
                    "failure_count": 10,
                    "running_count": 2,
                    "by_task_name": {
                        "check_due_reminders": 1440,
                        "backup_database": 1,
                        "warm_cache": 48,
                    },
                    "avg_duration_ms": 250.5,
                }
            ]
        }
    }


class TaskHistoryParams(BaseModel):
    """Query parameters for task history endpoint."""

    limit: int = Field(default=100, ge=1, le=500, description="Maximum results to return")
    offset: int = Field(default=0, ge=0, description="Number of results to skip")
    task_name: str | None = Field(default=None, description="Filter by task name")
    status: Literal["success", "failure"] | None = Field(
        default=None, description="Filter by status"
    )
