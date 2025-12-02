"""Query resolvers for audit logs.

Provides read operations for audit logs:
- auditLog(id): Get a single audit log by ID
- auditLogs(first, after, filters): List audit logs with pagination and filters
- auditLogsByEntity(entityType, entityId): Get audit history for an entity
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry
from sqlalchemy import select

from example_service.features.audit.models import AuditLog
from example_service.features.audit.schemas import AuditLogResponse
from example_service.features.graphql.types.auditlogs import (
    AuditLogConnection,
    AuditLogEdge,
    AuditLogType,
)
from example_service.features.graphql.types.base import PageInfoType

if TYPE_CHECKING:
    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type aliases
FirstArg = Annotated[int, strawberry.argument(description="Number of items to return")]
AfterArg = Annotated[str | None, strawberry.argument(description="Cursor to start after")]


async def audit_log_query(
    info: Info[GraphQLContext, None],
    id: strawberry.ID,
) -> AuditLogType | None:
    """Get a single audit log by ID.

    Uses DataLoader for efficient batching if called multiple times.

    Args:
        info: Strawberry info with context
        id: Audit log UUID

    Returns:
        AuditLogType if found, None otherwise
    """
    ctx = info.context
    try:
        audit_uuid = UUID(str(id))
    except ValueError:
        return None

    audit = await ctx.loaders.audit_logs.load(audit_uuid)
    if audit is None:
        return None

    # Convert: SQLAlchemy → Pydantic → GraphQL
    audit_pydantic = AuditLogResponse.from_orm(audit)
    return AuditLogType.from_pydantic(audit_pydantic)


async def audit_logs_query(
    info: Info[GraphQLContext, None],
    first: FirstArg = 50,
    after: AfterArg = None,
    entity_type: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
) -> AuditLogConnection:
    """List audit logs with cursor pagination and filters.

    Args:
        info: Strawberry info with context
        first: Items for forward pagination
        after: Cursor for forward pagination
        entity_type: Filter by entity type
        user_id: Filter by user ID
        action: Filter by action type

    Returns:
        AuditLogConnection with edges and page_info
    """
    ctx = info.context
    from example_service.features.audit.repository import get_audit_repository

    repo = get_audit_repository()

    # Build base statement with filters
    stmt = select(AuditLog)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)

    # Use cursor pagination
    connection = await repo.paginate_cursor(
        ctx.session,
        stmt,
        first=first,
        after=after,
        order_by=[
            (AuditLog.timestamp, "desc"),
            (AuditLog.id, "asc"),
        ],
        include_total=True,
    )

    # Convert to GraphQL types via Pydantic
    edges = [
        AuditLogEdge(
            node=AuditLogType.from_pydantic(AuditLogResponse.from_orm(edge.node)),
            cursor=edge.cursor,
        )
        for edge in connection.edges
    ]

    page_info = PageInfoType(
        has_previous_page=connection.page_info.has_previous_page,
        has_next_page=connection.page_info.has_next_page,
        start_cursor=connection.page_info.start_cursor,
        end_cursor=connection.page_info.end_cursor,
        total_count=connection.page_info.total_count,
    )

    return AuditLogConnection(edges=edges, page_info=page_info)


async def audit_logs_by_entity_query(
    info: Info[GraphQLContext, None],
    entity_type: str,
    entity_id: str,
    first: FirstArg = 50,
) -> list[AuditLogType]:
    """Get audit log history for a specific entity.

    Uses DataLoader for efficient batching.

    Args:
        info: Strawberry info with context
        entity_type: Entity type (e.g., "reminder")
        entity_id: Entity ID
        first: Maximum number of logs to return

    Returns:
        List of audit logs for the entity
    """
    ctx = info.context

    # Use DataLoader to get audit logs by entity
    entity_key = f"{entity_type}:{entity_id}"
    audit_logs = await ctx.loaders.audit_logs_by_entity.load(entity_key)

    # Limit results and convert to GraphQL types
    limited_logs = list(audit_logs)[:first]

    return [AuditLogType.from_pydantic(AuditLogResponse.from_orm(log)) for log in limited_logs]


__all__ = [
    "audit_log_query",
    "audit_logs_by_entity_query",
    "audit_logs_query",
]
