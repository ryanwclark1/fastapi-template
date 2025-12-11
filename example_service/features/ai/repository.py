"""Agent repository for database operations.

Provides data access layer for AI agent configurations,
separating persistence concerns from business logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from example_service.core.database.repository import BaseRepository, SearchResult
from example_service.infra.logging import get_lazy_logger
from example_service.utils.runtime_dependencies import require_runtime_dependency

from .models import Agent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_lazy = get_lazy_logger(__name__)
require_runtime_dependency(uuid.UUID, Agent)


class AgentRepository(BaseRepository[Agent]):
    """Repository for Agent database operations.

    Provides methods for:
    - CRUD operations on agent configurations
    - Filtered listing with pagination
    - Key-based and ID-based lookups
    - Tenant-scoped queries
    - Statistics and analytics queries

    Example:
        repo = AgentRepository()
        agent = await repo.get_by_key(session, "tenant-123:my-agent")
        agents = await repo.list_for_tenant(
            session,
            tenant_id="tenant-123",
            include_prebuilt=True
        )
    """

    def __init__(self) -> None:
        """Initialize agent repository."""
        super().__init__(Agent)

    async def get_by_key(
        self,
        session: AsyncSession,
        agent_key: str,
    ) -> Agent | None:
        """Get an agent by its unique key.

        Args:
            session: Database session.
            agent_key: Unique agent key (e.g., 'system:rag_agent' or 'tenant-123:my-agent').

        Returns:
            Agent if found, None otherwise.
        """
        stmt = select(Agent).where(Agent.agent_key == agent_key)
        result = await session.execute(stmt)
        agent = result.scalar_one_or_none()

        _lazy.debug(
            lambda: f"get_by_key: {agent_key} -> {'found' if agent else 'not found'}",
        )
        return agent

    async def list_for_tenant(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        include_prebuilt: bool = True,
        agent_type: str | None = None,
        is_active: bool | None = True,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResult[Agent]:
        """List agents for a tenant with optional prebuilt agents.

        Args:
            session: Database session.
            tenant_id: Tenant identifier.
            include_prebuilt: Include system prebuilt agents.
            agent_type: Filter by agent type.
            is_active: Filter by active status (None = all).
            limit: Maximum agents to return.
            offset: Number of agents to skip.

        Returns:
            SearchResult with agents and total count.
        """
        # Build base query
        stmt = select(Agent)

        # Tenant filtering: tenant agents + optionally prebuilt
        if include_prebuilt:
            stmt = stmt.where(
                or_(
                    Agent.tenant_id == tenant_id,
                    Agent.tenant_id.is_(None),  # System agents
                ),
            )
        else:
            stmt = stmt.where(Agent.tenant_id == tenant_id)

        # Type filtering
        if agent_type:
            stmt = stmt.where(Agent.agent_type == agent_type)

        # Active filtering
        if is_active is not None:
            stmt = stmt.where(Agent.is_active == is_active)

        # Get total count
        count_stmt = select(func.count()).select_from(stmt.alias())
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Apply pagination and ordering
        stmt = stmt.order_by(Agent.is_prebuilt.desc(), Agent.name).limit(limit).offset(offset)

        # Execute query
        result = await session.execute(stmt)
        agents = list(result.scalars().all())

        _lazy.debug(
            lambda: (
                f"list_for_tenant: tenant={tenant_id}, type={agent_type}, "
                f"active={is_active}, found={len(agents)}/{total}"
            ),
        )

        return SearchResult(items=agents, total=total, limit=limit, offset=offset)

    async def get_with_relationships(
        self,
        session: AsyncSession,
        agent_id: uuid.UUID,
    ) -> Agent | None:
        """Get agent with all relationships loaded.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            Agent with relationships loaded, or None if not found.
        """
        return await self.get(
            session,
            agent_id,
            options=[
                selectinload(Agent.tenant),
                selectinload(Agent.created_by),
                selectinload(Agent.updated_by),
            ],
        )

    async def clone_agent(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        tenant_id: str,
        name: str,
        agent_key: str,
        customizations: dict,
        created_by_id: uuid.UUID,
    ) -> Agent:
        """Clone an agent with customizations.

        Args:
            session: Database session.
            source_id: Source agent ID to clone from.
            tenant_id: Tenant ID for new agent.
            name: Name for cloned agent.
            agent_key: Unique key for cloned agent.
            customizations: Fields to override.
            created_by_id: User creating the clone.

        Returns:
            Newly created cloned agent.

        Raises:
            ValueError: If source agent not found.
        """
        # Get source agent
        source = await self.get(session, source_id)
        if not source:
            msg = f"Source agent {source_id} not found"
            raise ValueError(msg)

        # Create new agent with source values
        clone_data = {
            "agent_key": agent_key,
            "name": name,
            "tenant_id": tenant_id,
            "agent_type": source.agent_type,
            "is_prebuilt": False,
            "prebuilt_template": source.prebuilt_template or (source.agent_key if source.is_prebuilt else None),
            "model": source.model,
            "provider": source.provider,
            "temperature": source.temperature,
            "max_tokens": source.max_tokens,
            "system_prompt": source.system_prompt,
            "tools": source.tools.copy() if source.tools else None,
            "config": source.config.copy() if source.config else None,
            "max_iterations": source.max_iterations,
            "timeout_seconds": source.timeout_seconds,
            "max_cost_usd": source.max_cost_usd,
            "tags": source.tags.copy() if source.tags else None,
            "created_by_id": created_by_id,
        }

        # Apply customizations
        clone_data.update(customizations)

        # Create agent
        clone = Agent(**clone_data)
        session.add(clone)
        await session.flush()
        await session.refresh(clone)

        _lazy.info(
            lambda: f"Cloned agent {source_id} -> {clone.id} for tenant {tenant_id}",
        )

        return clone

    async def update_last_used_at(
        self,
        session: AsyncSession,
        agent_id: uuid.UUID,
    ) -> Agent | None:
        """Update last_used_at timestamp for an agent."""
        agent = await self.get(session, agent_id)
        if not agent:
            return None

        agent.last_used_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(agent)
        _lazy.debug(lambda: f"Updated last_used_at for agent {agent_id}")
        return agent

    async def count_by_tenant(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> int:
        """Count agents for a tenant (excluding prebuilt).

        Args:
            session: Database session.
            tenant_id: Tenant identifier.

        Returns:
            Number of agents.
        """
        stmt = select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_prebuilt_agents(
        self,
        session: AsyncSession,
    ) -> list[Agent]:
        """Get all system prebuilt agents.

        Args:
            session: Database session.

        Returns:
            List of prebuilt agents.
        """
        stmt = (
            select(Agent)
            .where(Agent.is_prebuilt == True)  # noqa: E712
            .where(Agent.tenant_id.is_(None))
            .order_by(Agent.name)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
