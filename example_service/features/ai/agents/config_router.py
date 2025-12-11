"""Agent configuration REST API endpoints.

Provides comprehensive API for managing AI agent configurations including:
- CRUD operations for custom agents
- Template-based agent creation
- Agent validation and testing
- Statistics and monitoring
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.database import NotFoundError
from example_service.core.dependencies.auth import AuthUserDep
from example_service.core.dependencies.database import get_db_session
from example_service.core.dependencies.tenant import TenantDep
from example_service.core.exceptions import ConflictException
from example_service.features.ai.agent_resolver import AgentResolver
from example_service.features.ai.schemas import (
    AgentCloneRequest,
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
    AgentValidationResponse,
    CreateFromTemplateRequest,
)
from example_service.features.ai.service import AgentService
from example_service.utils.runtime_dependencies import require_runtime_dependency

if TYPE_CHECKING:
    from example_service.core.schemas.auth import AuthUser
    from example_service.infra.storage.backends.protocol import TenantContext

router = APIRouter(prefix="/agents", tags=["AI Agent Configuration"])

require_runtime_dependency(uuid, AuthUserDep, TenantDep, AsyncSession)


def _require_tenant_uuid(tenant: TenantContext | None) -> str:
    """Ensure a tenant context is present and return its identifier."""
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required for this operation",
        )
    return tenant.tenant_uuid


def _get_audit_user_id(user: AuthUser) -> int | None:
    """Best-effort conversion of AuthUser identity into an integer audit ID."""
    candidate_values = [
        user.metadata.get("user_pk"),
        user.metadata.get("user_id"),
        user.user_id,
        user.service_id,
    ]
    for value in candidate_values:
        if value in (None, ""):
            continue
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return None


# ============================================================================
# Agent CRUD Endpoints
# ============================================================================


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create custom agent",
    description="Create a new custom AI agent configuration from scratch.",
)
async def create_agent(
    data: AgentCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: AuthUserDep,
    tenant: TenantDep,
) -> AgentResponse:
    """Create a new custom agent.

    Args:
        data: Agent configuration.
        session: Database session.
        user: Authenticated user.
        tenant: Current tenant.

    Returns:
        Created agent details.

    Raises:
        ConflictException: If agent with same name already exists.
        ValidationError: If configuration is invalid.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    audit_user_id = _get_audit_user_id(user)
    try:
        agent = await service.create_agent(
            data=data,
            user_id=audit_user_id,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        raise ConflictException(
            detail=str(e),
            type="agent-creation-failed",
        ) from e

    return AgentResponse.model_validate(agent)


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List agents",
    description="List all agents accessible to the current tenant (custom + prebuilt).",
)
async def list_agents(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: TenantDep,
    _user: AuthUserDep,
    include_prebuilt: Annotated[bool, Query()] = True,
    agent_type: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentListResponse:
    """List agents with filtering and pagination.

    Args:
        session: Database session.
        tenant: Current tenant.
        _user: Authenticated user (for access control).
        include_prebuilt: Include system prebuilt agents.
        agent_type: Filter by agent type.
        is_active: Filter by active status (None = all).
        page: Page number (1-indexed).
        limit: Items per page.

    Returns:
        Paginated list of agents.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    # Calculate offset
    offset = (page - 1) * limit

    # Get agents
    result = await service.repository.list_for_tenant(
        session,
        tenant_id=tenant_id,
        include_prebuilt=include_prebuilt,
        agent_type=agent_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    # Convert to response models
    agent_responses = [AgentResponse.model_validate(agent) for agent in result.items]

    return AgentListResponse(
        items=agent_responses,
        total=result.total,
        page=page,
        limit=limit,
        has_next=(page * limit) < result.total,
    )


@router.get(
    "/templates",
    response_model=list[dict],
    summary="List available templates",
    description="Get information about available prebuilt agent templates.",
)
async def list_templates(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: TenantDep,
    _user: AuthUserDep,
) -> list[dict]:
    """List available prebuilt templates.

    Args:
        session: Database session.
        tenant: Current tenant.
        _user: Authenticated user.

    Returns:
        List of template information.
    """
    tenant_id = _require_tenant_uuid(tenant)
    resolver = AgentResolver(session, tenant_id=tenant_id)
    return await resolver.get_prebuilt_templates()


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get agent details",
    description="Get detailed information about a specific agent including statistics.",
)
async def get_agent(
    agent_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: TenantDep,
    _user: AuthUserDep,
) -> AgentResponse:
    """Get agent by ID.

    Args:
        agent_id: Agent UUID.
        session: Database session.
        tenant: Current tenant.
        _user: Authenticated user.

    Returns:
        Agent details.

    Raises:
        HTTPException: If agent not found or not accessible.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    return AgentResponse.model_validate(agent)


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Update agent",
    description="Update an existing agent configuration (full or partial update).",
)
async def update_agent(
    agent_id: uuid.UUID,
    data: AgentUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: AuthUserDep,
    tenant: TenantDep,
) -> AgentResponse:
    """Update an existing agent.

    Args:
        agent_id: Agent UUID.
        data: Update data (partial).
        session: Database session.
        user: Authenticated user.
        tenant: Current tenant.

    Returns:
        Updated agent.

    Raises:
        HTTPException: If agent not found, not accessible, or is prebuilt.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    audit_user_id = _get_audit_user_id(user)
    try:
        agent = await service.update_agent(
            agent_id=agent_id,
            data=data,
            user_id=audit_user_id,
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    return AgentResponse.model_validate(agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete agent",
    description="Soft delete (deactivate) an agent. Prebuilt agents cannot be deleted.",
)
async def delete_agent(
    agent_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: TenantDep,
    _user: AuthUserDep,
) -> None:
    """Delete (deactivate) an agent.

    Args:
        agent_id: Agent UUID.
        session: Database session.
        tenant: Current tenant.
        _user: Authenticated user.

    Raises:
        HTTPException: If agent not found, not accessible, or is prebuilt.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    try:
        await service.delete_agent(agent_id)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# ============================================================================
# Agent Cloning & Templates
# ============================================================================


@router.post(
    "/{agent_id}/clone",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone agent",
    description="Clone an existing agent with optional customizations.",
)
async def clone_agent(
    agent_id: uuid.UUID,
    data: AgentCloneRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: AuthUserDep,
    tenant: TenantDep,
) -> AgentResponse:
    """Clone an agent with customizations.

    Args:
        agent_id: Source agent UUID to clone.
        data: Clone request with name and customizations.
        session: Database session.
        user: Authenticated user.
        tenant: Current tenant.

    Returns:
        Cloned agent.

    Raises:
        HTTPException: If source agent not found or not accessible.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    audit_user_id = _get_audit_user_id(user)
    try:
        clone = await service.clone_agent(
            source_id=agent_id,
            data=data,
            user_id=audit_user_id,
            tenant_id=tenant_id,
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    return AgentResponse.model_validate(clone)


@router.post(
    "/from-template",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create agent from template",
    description="Create a new agent from a prebuilt template with optional customizations.",
)
async def create_from_template(
    data: CreateFromTemplateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: AuthUserDep,
    tenant: TenantDep,
) -> AgentResponse:
    """Create agent from a prebuilt template.

    Args:
        data: Template creation request with name and customizations.
        session: Database session.
        user: Authenticated user.
        tenant: Current tenant.

    Returns:
        Created agent details.

    Raises:
        HTTPException: If template not found.
        ConflictException: If agent with same name already exists.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    audit_user_id = _get_audit_user_id(user)
    try:
        agent = await service.create_from_template(
            data=data,
            user_id=audit_user_id,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        # Template not found or duplicate agent key
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        raise ConflictException(
            detail=str(e),
            type="agent-creation-failed",
        ) from e

    return AgentResponse.model_validate(agent)


# ============================================================================
# Agent Validation & Health
# ============================================================================


@router.post(
    "/{agent_id}/validate",
    response_model=AgentValidationResponse,
    summary="Validate agent configuration",
    description="Validate agent configuration and return errors, warnings, and suggestions.",
)
async def validate_agent(
    agent_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant: TenantDep,
    _user: AuthUserDep,
) -> AgentValidationResponse:
    """Validate agent configuration.

    Args:
        agent_id: Agent UUID.
        session: Database session.
        tenant: Current tenant.
        _user: Authenticated user.

    Returns:
        Validation results.

    Raises:
        HTTPException: If agent not found or not accessible.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    try:
        validation = await service.validate_agent(agent_id)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    return validation


@router.patch(
    "/{agent_id}/activate",
    response_model=AgentResponse,
    summary="Activate agent",
    description="Activate a deactivated agent.",
)
async def activate_agent(
    agent_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: AuthUserDep,
    tenant: TenantDep,
) -> AgentResponse:
    """Activate an agent.

    Args:
        agent_id: Agent UUID.
        session: Database session.
        user: Authenticated user.
        tenant: Current tenant.

    Returns:
        Updated agent.

    Raises:
        HTTPException: If agent not found or not accessible.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    audit_user_id = _get_audit_user_id(user)
    try:
        # Update to set is_active = True
        agent = await service.update_agent(
            agent_id=agent_id,
            data=AgentUpdate(is_active=True),
            user_id=audit_user_id,
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    return AgentResponse.model_validate(agent)


@router.patch(
    "/{agent_id}/deactivate",
    response_model=AgentResponse,
    summary="Deactivate agent",
    description="Deactivate an active agent without deleting it.",
)
async def deactivate_agent(
    agent_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: AuthUserDep,
    tenant: TenantDep,
) -> AgentResponse:
    """Deactivate an agent.

    Args:
        agent_id: Agent UUID.
        session: Database session.
        user: Authenticated user.
        tenant: Current tenant.

    Returns:
        Updated agent.

    Raises:
        HTTPException: If agent not found or not accessible.
    """
    tenant_id = _require_tenant_uuid(tenant)
    service = AgentService(session, tenant_id=tenant_id)

    audit_user_id = _get_audit_user_id(user)
    try:
        agent = await service.update_agent(
            agent_id=agent_id,
            data=AgentUpdate(is_active=False),
            user_id=audit_user_id,
        )
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    return AgentResponse.model_validate(agent)
