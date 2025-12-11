"""Agent resolver for hybrid agent configuration.

Resolves agent configurations from either database (custom agents) or
code templates (prebuilt agents), providing a unified interface for
agent instantiation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
import uuid

from example_service.core.database import NotFoundError
from example_service.utils.runtime_dependencies import require_runtime_dependency

from .models import Agent
from .repository import AgentRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

require_runtime_dependency(uuid.UUID, Agent)


class AgentResolver:
    """Resolves agent configurations from database or prebuilt templates.

    Provides hybrid agent resolution supporting both:
    - Database-stored agents (custom and prebuilt)
    - Code-defined templates (fallback/defaults)

    Resolution priority:
    1. By agent_id (database lookup)
    2. By agent_key starting with "system:" (prebuilt)
    3. By agent_key starting with "tenant:" (custom)

    Example:
        resolver = AgentResolver(session)

        # Resolve by ID
        config = await resolver.resolve_agent(agent_id=uuid)

        # Resolve by key
        config = await resolver.resolve_agent(agent_key="system:rag_agent")

        # With runtime overrides
        config = await resolver.resolve_agent(
            agent_id=uuid,
            runtime_overrides={"temperature": 0.5}
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str | None = None,
    ) -> None:
        """Initialize agent resolver.

        Args:
            session: Database session.
            tenant_id: Optional tenant ID for access control.
        """
        self.session = session
        self.tenant_id = tenant_id
        self.repository = AgentRepository()

    async def resolve_agent(
        self,
        agent_id: uuid.UUID | None = None,
        agent_key: str | None = None,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> tuple[Agent, dict[str, Any]]:
        """Resolve agent configuration.

        Args:
            agent_id: Agent ID (database lookup).
            agent_key: Agent key (database or template lookup).
            runtime_overrides: Runtime configuration overrides.

        Returns:
            Tuple of (Agent model, merged config dict).

        Raises:
            ValueError: If neither agent_id nor agent_key provided.
            NotFoundError: If agent not found.
            PermissionError: If tenant doesn't have access.
        """
        if not agent_id and not agent_key:
            msg = "Either agent_id or agent_key must be provided"
            raise ValueError(msg)

        # Resolve agent
        agent: Agent | None = None

        if agent_id:
            agent = await self._resolve_by_id(agent_id)
        elif agent_key:
            agent = await self._resolve_by_key(agent_key)

        if not agent:
            identifier: dict[str, Any] = {}
            if agent_id:
                identifier["id"] = agent_id
            if agent_key:
                identifier["agent_key"] = agent_key

            model_name = "Agent"
            raise NotFoundError(
                model_name,
                identifier,
            )

        # Build config dict
        config = self._agent_to_config_dict(agent)

        # Apply runtime overrides
        if runtime_overrides:
            config = self._merge_overrides(config, runtime_overrides)

        logger.debug(
            "Resolved agent %s (%s) with overrides=%s",
            agent.id,
            agent.agent_key,
            bool(runtime_overrides),
        )

        return agent, config

    async def _resolve_by_id(self, agent_id: uuid.UUID) -> Agent | None:
        """Resolve agent by ID.

        Args:
            agent_id: Agent ID.

        Returns:
            Agent if found and accessible.

        Raises:
            PermissionError: If tenant doesn't have access.
        """
        agent = await self.repository.get(self.session, agent_id)
        if not agent:
            return None

        # Enforce tenant isolation
        if self.tenant_id and agent.tenant_id not in (self.tenant_id, None):
            msg = (
                f"Tenant {self.tenant_id} cannot access agent {agent_id}"
            )
            raise PermissionError(
                msg,
            )

        return agent

    async def _resolve_by_key(self, agent_key: str) -> Agent | None:
        """Resolve agent by key.

        Args:
            agent_key: Agent key.

        Returns:
            Agent if found and accessible.

        Raises:
            PermissionError: If tenant doesn't have access.
        """
        agent = await self.repository.get_by_key(self.session, agent_key)
        if not agent:
            return None

        # Enforce tenant isolation
        if self.tenant_id and agent.tenant_id not in (self.tenant_id, None):
            msg = (
                f"Tenant {self.tenant_id} cannot access agent {agent_key}"
            )
            raise PermissionError(
                msg,
            )

        return agent

    def _agent_to_config_dict(self, agent: Agent) -> dict[str, Any]:
        """Convert Agent model to configuration dictionary.

        Args:
            agent: Agent model.

        Returns:
            Configuration dictionary suitable for AgentConfig.
        """
        return {
            "agent_id": agent.id,
            "provider": agent.provider,
            "llm_provider": agent.provider,
            "model": agent.model,
            "temperature": agent.temperature,
            "max_tokens": agent.max_tokens,
            "system_prompt": agent.system_prompt,
            "tools": self._convert_tools_format(agent.tools) if agent.tools else [],
            "max_iterations": agent.max_iterations or 10,
            "timeout_seconds": agent.timeout_seconds or 300,
            "max_cost_usd": agent.max_cost_usd,
            "retry_config": agent.config.get("retry_config") if agent.config else None,
            "checkpoint_config": agent.config.get("checkpoint_config") if agent.config else None,
            # Additional metadata
            "agent_type": agent.agent_type,
            "agent_key": agent.agent_key,
            "version": agent.version,
        }

    def _convert_tools_format(self, tools: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert tools from storage format to AgentConfig format.

        Args:
            tools: Tools dict from database (name -> config).

        Returns:
            List of tool configurations.
        """
        tool_list = []
        for tool_name, tool_config in tools.items():
            if tool_config.get("enabled", True):
                tool_list.append({
                    "name": tool_name,
                    "config": tool_config.get("config", {}),
                    "requires_confirmation": tool_config.get("requires_confirmation", False),
                    "timeout_seconds": tool_config.get("timeout_seconds"),
                })
        return tool_list

    def _merge_overrides(
        self,
        base_config: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge runtime overrides into base configuration.

        Args:
            base_config: Base configuration.
            overrides: Runtime overrides.

        Returns:
            Merged configuration.
        """
        merged = base_config.copy()

        # Allow overriding specific fields
        allowed_overrides = {
            "temperature",
            "max_tokens",
            "max_iterations",
            "timeout_seconds",
            "max_cost_usd",
        }

        for key, value in overrides.items():
            if key in allowed_overrides:
                merged[key] = value
            else:
                logger.warning(
                    f"Runtime override '{key}' not allowed, ignoring",
                )

        return merged

    async def get_prebuilt_templates(self) -> list[dict[str, Any]]:
        """Get information about available prebuilt templates.

        Returns:
            List of template information dicts.
        """
        prebuilt_agents = await self.repository.get_prebuilt_agents(self.session)

        return [
            {
                "name": agent.agent_key.split(":", 1)[1],  # Remove "system:" prefix
                "display_name": agent.name,
                "description": agent.description or "",
                "agent_type": agent.agent_type,
                "default_model": agent.model,
                "default_provider": agent.provider,
                "default_temperature": float(agent.temperature) if agent.temperature else 0.7,
                "available_tools": list(agent.tools.keys()) if agent.tools else [],
                "system_prompt": agent.system_prompt,
                "default_max_tokens": agent.max_tokens,
            }
            for agent in prebuilt_agents
        ]
