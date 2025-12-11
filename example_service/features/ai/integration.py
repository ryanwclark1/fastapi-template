"""Integration utilities for bridging features/ai and infra/ai.

This module provides helpers to connect the persistent Agent configuration
(features/ai) with the execution framework (infra/ai).

Key Functions:
- create_agent_config_from_db: Load Agent from database and create AgentConfig
- execute_agent_by_id: Execute an agent by its database ID
- execute_agent_by_key: Execute an agent by its key
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from example_service.features.ai.agent_resolver import AgentResolver
from example_service.infra.ai.agents.base import AgentConfig

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from example_service.features.ai.models import Agent


async def create_agent_config_from_db(
    session: AsyncSession,
    agent_id: UUID | None = None,
    agent_key: str | None = None,
    tenant_id: str | None = None,
    runtime_overrides: dict[str, Any] | None = None,
) -> tuple[Agent | None, AgentConfig | None]:
    """Create AgentConfig from database Agent configuration.

    This helper bridges the persistent Agent model (features/ai) with the
    execution framework's AgentConfig (infra/ai).

    Args:
        session: Database session.
        agent_id: Agent UUID to load.
        agent_key: Agent key to load (alternative to agent_id).
        tenant_id: Tenant ID for multi-tenancy.
        runtime_overrides: Optional configuration overrides for this execution.

    Returns:
        Tuple of (Agent model, AgentConfig) if found, (None, None) otherwise.

    Example:
        # Load agent configuration and execute
        agent, config = await create_agent_config_from_db(
            session=db_session,
            agent_id=UUID("..."),
            runtime_overrides={"temperature": 0.3}
        )

        if config:
            # Use config with BaseAgent
            agent_instance = MyAgent(config=config, db_session=session)
            result = await agent_instance.execute(input_data={"query": "..."})
    """
    resolver = AgentResolver(session, tenant_id=tenant_id)

    # Resolve agent from database
    agent, config_dict = await resolver.resolve_agent(
        agent_id=agent_id,
        agent_key=agent_key,
        runtime_overrides=runtime_overrides,
    )

    if not agent or not config_dict:
        return None, None

    # Convert dict to AgentConfig
    agent_config = AgentConfig(
        agent_id=agent.id,  # Link back to the Agent configuration
        model=config_dict["model"],
        provider=config_dict["provider"],
        temperature=config_dict.get("temperature", 0.7),
        max_tokens=config_dict.get("max_tokens", 4096),
        system_prompt=config_dict.get("system_prompt"),
        max_iterations=config_dict.get("max_iterations", 10),
        timeout_seconds=config_dict.get("timeout_seconds", 300),
        # Add other relevant fields from config_dict
        **_extract_additional_config(config_dict),
    )

    return agent, agent_config


async def get_agent_config(
    session: AsyncSession,
    agent_id: UUID,
    tenant_id: str | None = None,
    **overrides: Any,
) -> AgentConfig | None:
    """Convenience function to get AgentConfig by ID.

    Args:
        session: Database session.
        agent_id: Agent UUID.
        tenant_id: Tenant ID for isolation.
        **overrides: Runtime configuration overrides.

    Returns:
        AgentConfig if found, None otherwise.

    Example:
        config = await get_agent_config(
            session=db_session,
            agent_id=agent_id,
            temperature=0.3  # Override temperature
        )
    """
    _, config = await create_agent_config_from_db(
        session=session,
        agent_id=agent_id,
        tenant_id=tenant_id,
        runtime_overrides=overrides if overrides else None,
    )
    return config


async def get_agent_config_by_key(
    session: AsyncSession,
    agent_key: str,
    tenant_id: str | None = None,
    **overrides: Any,
) -> AgentConfig | None:
    """Convenience function to get AgentConfig by key.

    Args:
        session: Database session.
        agent_key: Agent key (e.g., "tenant-123:my-agent").
        tenant_id: Tenant ID for isolation.
        **overrides: Runtime configuration overrides.

    Returns:
        AgentConfig if found, None otherwise.

    Example:
        config = await get_agent_config_by_key(
            session=db_session,
            agent_key="system:rag_agent",
            max_iterations=5  # Override max iterations
        )
    """
    _, config = await create_agent_config_from_db(
        session=session,
        agent_key=agent_key,
        tenant_id=tenant_id,
        runtime_overrides=overrides if overrides else None,
    )
    return config


def _extract_additional_config(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Extract additional AgentConfig fields from config dictionary.

    Args:
        config_dict: Configuration dictionary from AgentResolver.

    Returns:
        Dictionary of additional AgentConfig-compatible fields.
    """
    additional = {}

    # Extract tool configuration if present
    tools_config = config_dict.get("tools")
    if tools_config:
        # Convert tool dict to list of tool names
        if isinstance(tools_config, dict):
            additional["tools"] = [
                name for name, cfg in tools_config.items()
                if cfg.get("enabled", True)
            ]
        elif isinstance(tools_config, list):
            additional["tools"] = tools_config

    # Extract retry settings if present
    if "max_retries" in config_dict:
        additional["max_retries"] = config_dict["max_retries"]

    # Extract checkpoint settings
    if "enable_checkpoints" in config_dict:
        additional["enable_checkpoints"] = config_dict["enable_checkpoints"]

    # Extract cost limits
    if "max_cost_usd" in config_dict:
        # Note: AgentConfig might need this field added
        pass

    return additional
