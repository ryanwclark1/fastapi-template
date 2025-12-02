"""Audit log REST API endpoints.

Provides endpoints for querying and retrieving audit logs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.dependencies.auth import get_current_user
from example_service.core.dependencies.database import get_session
from example_service.core.exceptions import NotFoundException

from .models import AuditAction
from .schemas import (
    AuditLogListResponse,
    AuditLogQuery,
    AuditLogResponse,
    AuditSummary,
    EntityAuditHistory,
)
from .service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/logs",
    response_model=AuditLogListResponse,
    summary="Query audit logs",
    description="Query audit logs with filtering, sorting, and pagination.",
)
async def query_audit_logs(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    entity_type: Annotated[str | None, Query(description="Filter by entity type")] = None,
    entity_id: Annotated[str | None, Query(description="Filter by entity ID")] = None,
    user_id: Annotated[str | None, Query(description="Filter by user who performed action")] = None,
    tenant_id: Annotated[str | None, Query(description="Filter by tenant")] = None,
    action: Annotated[AuditAction | None, Query(description="Filter by action type")] = None,
    success: Annotated[bool | None, Query(description="Filter by success status")] = None,
    request_id: Annotated[str | None, Query(description="Filter by request ID")] = None,
    start_time: Annotated[datetime | None, Query(description="Filter logs after this time")] = None,
    end_time: Annotated[datetime | None, Query(description="Filter logs before this time")] = None,
    order_by: Annotated[str, Query(description="Field to order by")] = "timestamp",
    order_desc: Annotated[bool, Query(description="Order descending")] = True,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum results")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of results to skip")] = 0,
) -> AuditLogListResponse:
    """Query audit logs with various filters.

    Returns a paginated list of audit log entries matching the specified criteria.
    """
    query = AuditLogQuery(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        tenant_id=tenant_id,
        action=action,
        success=success,
        request_id=request_id,
        start_time=start_time,
        end_time=end_time,
        order_by=order_by,
        order_desc=order_desc,
        limit=limit,
        offset=offset,
    )

    service = AuditService(session)
    return await service.query(query)


@router.get(
    "/logs/{audit_id}",
    response_model=AuditLogResponse,
    summary="Get audit log by ID",
    description="Retrieve a specific audit log entry by its ID.",
)
async def get_audit_log(
    audit_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
) -> AuditLogResponse:
    """Get a specific audit log entry.

    Args:
        audit_id: The audit log ID.

    Returns:
        The audit log entry.

    Raises:
        NotFoundException: If audit log not found.
    """
    service = AuditService(session)
    audit_log = await service.get_by_id(audit_id)

    if audit_log is None:
        raise NotFoundException(f"Audit log {audit_id} not found")

    return AuditLogResponse.model_validate(audit_log)


@router.get(
    "/entity/{entity_type}/{entity_id}/history",
    response_model=EntityAuditHistory,
    summary="Get entity audit history",
    description="Get complete audit history for a specific entity.",
)
async def get_entity_history(
    entity_type: str,
    entity_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum entries")] = 100,
) -> EntityAuditHistory:
    """Get the complete audit trail for an entity.

    Shows all changes made to the entity over time, including who made
    them and when.

    Args:
        entity_type: Type of entity (e.g., "reminder", "file").
        entity_id: ID of the entity.
        limit: Maximum number of entries to return.

    Returns:
        Complete audit history for the entity.
    """
    service = AuditService(session)
    return await service.get_entity_history(entity_type, entity_id, limit)


@router.get(
    "/summary",
    response_model=AuditSummary,
    summary="Get audit summary",
    description="Get summary statistics for audit logs.",
)
async def get_audit_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    tenant_id: Annotated[str | None, Query(description="Filter by tenant")] = None,
    start_time: Annotated[datetime | None, Query(description="Start of time range")] = None,
    end_time: Annotated[datetime | None, Query(description="End of time range")] = None,
) -> AuditSummary:
    """Get audit log summary statistics.

    Provides aggregated statistics including:
    - Total number of entries
    - Breakdown by action type
    - Breakdown by entity type
    - Success rate
    - Number of unique users
    - Time range of logs

    Args:
        tenant_id: Optional tenant filter.
        start_time: Optional start time filter.
        end_time: Optional end time filter.

    Returns:
        Summary statistics.
    """
    service = AuditService(session)
    return await service.get_summary(tenant_id, start_time, end_time)


@router.get(
    "/actions",
    response_model=list[str],
    summary="List available actions",
    description="Get list of all available audit action types.",
)
async def list_audit_actions(
    _user: Annotated[dict, Depends(get_current_user)],
) -> list[str]:
    """Get list of all audit action types.

    Returns:
        List of action type strings.
    """
    return [action.value for action in AuditAction]


@router.get(
    "/user/{user_id}",
    response_model=AuditLogListResponse,
    summary="Get user activity",
    description="Get all audit logs for a specific user.",
)
async def get_user_activity(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[dict, Depends(get_current_user)],
    start_time: Annotated[datetime | None, Query(description="Start of time range")] = None,
    end_time: Annotated[datetime | None, Query(description="End of time range")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum results")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of results to skip")] = 0,
) -> AuditLogListResponse:
    """Get all activity for a specific user.

    Shows all actions performed by a user within the specified time range.

    Args:
        user_id: ID of the user.
        start_time: Optional start time filter.
        end_time: Optional end time filter.
        limit: Maximum number of results.
        offset: Number of results to skip.

    Returns:
        Paginated list of user's audit logs.
    """
    query = AuditLogQuery(
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )

    service = AuditService(session)
    return await service.query(query)
