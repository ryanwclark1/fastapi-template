"""Agent service for business logic.

Provides high-level operations for agent configuration management,
including creation, updates, validation, and execution orchestration.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING
import uuid

from example_service.core.database import NotFoundError
from example_service.utils.runtime_dependencies import require_runtime_dependency

from .agent_resolver import AgentResolver
from .models import Agent
from .repository import AgentRepository
from .schemas import (
    AgentCloneRequest,
    AgentCreate,
    AgentUpdate,
    AgentValidationResponse,
    CreateFromTemplateRequest,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
require_runtime_dependency(uuid.UUID)


class AgentService:
    """Service for managing AI agent configurations.

    Provides:
    - CRUD operations for agent configurations
    - Template-based agent creation
    - Agent validation and testing
    - Cloning and customization
    - Multi-tenancy enforcement

    Example:
        service = AgentService(session, tenant_id="tenant-123")

        # Create custom agent
        agent = await service.create_agent(
            AgentCreate(
                name="My Custom Agent",
                agent_type="rag",
                system_prompt="You are a helpful assistant...",
            ),
            user_id=user_id,
        )

        # Clone from template
        clone = await service.clone_agent(
            template_agent_id,
            AgentCloneRequest(
                name="Customer Support RAG",
                customizations={"temperature": 0.3}
            ),
            user_id=user_id,
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: str | None = None,
    ) -> None:
        """Initialize agent service.

        Args:
            session: Database session.
            tenant_id: Optional tenant ID for tenant-scoped operations.
        """
        self.session = session
        self.tenant_id = tenant_id
        self.repository = AgentRepository()

    async def create_agent(
        self,
        data: AgentCreate,
        user_id: int | None,
        tenant_id: str | None = None,
    ) -> Agent:
        """Create a new custom agent.

        Args:
            data: Agent creation data.
            user_id: Database user ID for auditing (if available).
            tenant_id: Tenant ID (uses service tenant_id if not provided).

        Returns:
            Created agent.

        Raises:
            ValueError: If validation fails.
        """
        tenant = tenant_id or self.tenant_id
        if not tenant:
            msg = "Tenant ID required for custom agents"
            raise ValueError(msg)

        # Generate unique agent key
        agent_key = self._generate_agent_key(tenant, data.name)

        # Check for duplicate key
        existing = await self.repository.get_by_key(self.session, agent_key)
        if existing:
            msg = f"Agent with key '{agent_key}' already exists"
            raise ValueError(msg)

        # Convert tools list to dict format
        tools_dict = None
        if data.tools:
            tools_dict = {
                tool.name: {
                    "enabled": tool.enabled,
                    "config": tool.config,
                    "requires_confirmation": tool.requires_confirmation,
                    "timeout_seconds": tool.timeout_seconds,
                }
                for tool in data.tools
            }

        # Create agent
        agent = Agent(
            agent_key=agent_key,
            name=data.name,
            description=data.description,
            tenant_id=tenant,
            agent_type=data.agent_type,
            is_prebuilt=False,
            model=data.model,
            provider=data.provider,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            system_prompt=data.system_prompt,
            tools=tools_dict,
            config=data.config,
            max_iterations=data.max_iterations,
            timeout_seconds=data.timeout_seconds,
            max_cost_usd=data.max_cost_usd,
            tags=data.tags,
            metadata_json=data.metadata,
            created_by_id=user_id,
            updated_by_id=user_id,
        )

        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)

        logger.info(f"Created agent {agent.id} ({agent.agent_key}) for user {user_id}")
        return agent

    async def create_from_template(
        self,
        data: CreateFromTemplateRequest,
        user_id: int | None,
        tenant_id: str | None = None,
    ) -> Agent:
        """Create agent from a prebuilt template.

        Args:
            data: Template request with name and customizations.
            user_id: Database user ID for auditing (if available).
            tenant_id: Tenant ID (uses service tenant_id if not provided).

        Returns:
            Created agent.

        Raises:
            ValueError: If template not found or validation fails.
        """
        tenant = tenant_id or self.tenant_id
        if not tenant:
            msg = "Tenant ID required for custom agents"
            raise ValueError(msg)

        # Get template configuration
        resolver = AgentResolver(self.session, tenant_id=tenant)
        templates = await resolver.get_prebuilt_templates()

        # Find matching template
        template = None
        for tmpl in templates:
            if tmpl["name"] == data.template_name:
                template = tmpl
                break

        if not template:
            msg = f"Template '{data.template_name}' not found"
            raise ValueError(msg)

        # Build agent configuration from template + customizations
        agent_data = {
            "name": data.name,
            "description": data.description or template.get("description"),
            "agent_type": template["agent_type"],
            "system_prompt": template["system_prompt"],
            "model": template["default_model"],
            "provider": template["default_provider"],
            "temperature": template.get("default_temperature", 0.7),
            "max_tokens": template.get("max_tokens"),
            "tools": template.get("available_tools"),
            "config": template.get("configuration_schema", {}),
            "max_iterations": template.get("max_iterations"),
            "timeout_seconds": template.get("timeout_seconds"),
        }

        # Apply customizations (override defaults)
        for key, value in data.customizations.items():
            if key in agent_data:
                agent_data[key] = value

        # Mark the template source
        prebuilt_template = data.template_name

        # Generate unique agent key
        agent_key = self._generate_agent_key(tenant, data.name)

        # Check for duplicate key
        existing = await self.repository.get_by_key(self.session, agent_key)
        if existing:
            msg = f"Agent with key '{agent_key}' already exists"
            raise ValueError(msg)

        # Convert tools to dict format if needed
        tools_dict = None
        if agent_data.get("tools"):
            # If tools is already a list of tool names from template
            if isinstance(agent_data["tools"], list):
                tools_dict = {
                    tool_name: {
                        "enabled": True,
                        "config": {},
                        "requires_confirmation": False,
                        "timeout_seconds": None,
                    }
                    for tool_name in agent_data["tools"]
                }
            else:
                tools_dict = agent_data["tools"]

        # Create agent
        agent = Agent(
            agent_key=agent_key,
            name=agent_data["name"],
            description=agent_data.get("description"),
            tenant_id=tenant,
            agent_type=agent_data["agent_type"],
            is_prebuilt=False,
            prebuilt_template=prebuilt_template,
            model=agent_data["model"],
            provider=agent_data["provider"],
            temperature=agent_data.get("temperature"),
            max_tokens=agent_data.get("max_tokens"),
            system_prompt=agent_data["system_prompt"],
            tools=tools_dict,
            config=agent_data.get("config"),
            max_iterations=agent_data.get("max_iterations"),
            timeout_seconds=agent_data.get("timeout_seconds"),
            max_cost_usd=agent_data.get("max_cost_usd"),
            tags=agent_data.get("tags"),
            metadata_json=agent_data.get("metadata"),
            created_by_id=user_id,
            updated_by_id=user_id,
        )

        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)

        logger.info(
            f"Created agent {agent.id} from template '{prebuilt_template}' for user {user_id}",
        )
        return agent

    async def update_agent(
        self,
        agent_id: uuid.UUID,
        data: AgentUpdate,
        user_id: int | None,
    ) -> Agent:
        """Update an existing agent.

        Args:
            agent_id: Agent ID to update.
            data: Update data (partial).
            user_id: Database user ID for auditing (if available).

        Returns:
            Updated agent.

        Raises:
            NotFoundError: If agent not found.
            ValueError: If trying to update prebuilt agent.
        """
        agent = await self.repository.get(self.session, agent_id)
        if not agent:
            model_name = "Agent"
            raise NotFoundError(model_name, {"id": agent_id})

        # Prevent modification of prebuilt agents
        if agent.is_prebuilt:
            msg = "Cannot modify prebuilt agents"
            raise ValueError(msg)

        # Enforce tenant isolation
        if self.tenant_id and agent.tenant_id != self.tenant_id:
            msg = "Cannot modify agent from different tenant"
            raise ValueError(msg)

        # Update fields
        update_data = data.model_dump(exclude_unset=True)

        # Handle tools conversion
        if "tools" in update_data and update_data["tools"] is not None:
            tools_dict = {
                tool.name: {
                    "enabled": tool.enabled,
                    "config": tool.config,
                    "requires_confirmation": tool.requires_confirmation,
                    "timeout_seconds": tool.timeout_seconds,
                }
                for tool in update_data["tools"]
            }
            update_data["tools"] = tools_dict

        # Bump version if requested
        if update_data.pop("bump_version", False):
            current_version = agent.version
            major, minor, _patch = current_version.split(".")
            update_data["version"] = f"{major}.{int(minor) + 1}.0"

        # Update agent
        for key, value in update_data.items():
            if hasattr(agent, key):
                setattr(agent, key, value)

        agent.updated_by_id = user_id
        agent.updated_at = datetime.now(UTC)

        await self.session.commit()
        await self.session.refresh(agent)

        logger.info(f"Updated agent {agent.id} by user {user_id}")
        return agent

    async def get_agent(
        self,
        agent_id: uuid.UUID,
    ) -> Agent | None:
        """Get agent by ID.

        Args:
            agent_id: Agent ID.

        Returns:
            Agent if found and accessible, None otherwise.
        """
        agent = await self.repository.get_with_relationships(self.session, agent_id)

        # Enforce tenant isolation
        if agent and self.tenant_id and agent.tenant_id not in (self.tenant_id, None):
            return None

        return agent

    async def clone_agent(
        self,
        source_id: uuid.UUID,
        data: AgentCloneRequest,
        user_id: int | None,
        tenant_id: str | None = None,
    ) -> Agent:
        """Clone an agent with customizations.

        Args:
            source_id: Source agent ID to clone.
            data: Clone request with name and customizations.
            user_id: Database user ID for auditing (if available).
            tenant_id: Tenant ID for cloned agent (uses service tenant_id if not provided).

        Returns:
            Cloned agent.

        Raises:
            NotFoundError: If source agent not found.
            ValueError: If validation fails.
        """
        tenant = tenant_id or self.tenant_id
        if not tenant:
            msg = "Tenant ID required for cloning"
            raise ValueError(msg)

        # Verify source exists and is accessible
        source = await self.get_agent(source_id)
        if not source:
            model_name = "Agent"
            raise NotFoundError(model_name, {"id": source_id})

        # Generate unique key
        agent_key = self._generate_agent_key(tenant, data.name)

        # Clone agent
        clone = await self.repository.clone_agent(
            self.session,
            source_id=source_id,
            tenant_id=tenant,
            name=data.name,
            agent_key=agent_key,
            customizations={
                **data.customizations,
                "description": data.description or f"Cloned from {source.name}",
            },
            created_by_id=user_id,
        )

        await self.session.commit()
        await self.session.refresh(clone)

        logger.info(f"Cloned agent {source_id} -> {clone.id} by user {user_id}")
        return clone

    async def delete_agent(
        self,
        agent_id: uuid.UUID,
    ) -> None:
        """Soft delete an agent (deactivate).

        Args:
            agent_id: Agent ID to delete.

        Raises:
            NotFoundError: If agent not found.
            ValueError: If trying to delete prebuilt agent.
        """
        agent = await self.repository.get(self.session, agent_id)
        if not agent:
            model_name = "Agent"
            raise NotFoundError(model_name, {"id": agent_id})

        if agent.is_prebuilt:
            msg = "Cannot delete prebuilt agents"
            raise ValueError(msg)

        # Enforce tenant isolation
        if self.tenant_id and agent.tenant_id != self.tenant_id:
            msg = "Cannot delete agent from different tenant"
            raise ValueError(msg)

        # Soft delete (deactivate)
        agent.is_active = False
        await self.session.commit()

        logger.info(f"Deleted (deactivated) agent {agent_id}")

    async def validate_agent(
        self,
        agent_id: uuid.UUID,
    ) -> AgentValidationResponse:
        """Validate agent configuration.

        Args:
            agent_id: Agent ID to validate.

        Returns:
            Validation results with errors, warnings, and suggestions.

        Raises:
            NotFoundError: If agent not found.
        """
        agent = await self.get_agent(agent_id)
        if not agent:
            model_name = "Agent"
            raise NotFoundError(model_name, {"id": agent_id})

        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        suggestions: list[dict[str, str]] = []

        # Validate system prompt
        if len(agent.system_prompt) < 20:
            warnings.append({
                "field": "system_prompt",
                "message": "System prompt is very short. Consider adding more context.",
            })

        # Validate model/provider combination
        if agent.provider == "openai" and "claude" in agent.model.lower():
            errors.append({
                "field": "model",
                "message": f"Model '{agent.model}' is not compatible with provider '{agent.provider}'",
            })

        # Check for deprecated models
        deprecated_models = ["gpt-3.5-turbo-0301", "text-davinci-003"]
        if agent.model in deprecated_models:
            warnings.append({
                "field": "model",
                "message": f"Model '{agent.model}' is deprecated. Consider upgrading.",
            })

        # Validate temperature range
        if agent.temperature is not None:
            if agent.temperature < 0.1:
                suggestions.append({
                    "field": "temperature",
                    "message": "Very low temperature may result in repetitive responses.",
                })
            elif agent.temperature > 1.5:
                warnings.append({
                    "field": "temperature",
                    "message": "High temperature may produce unpredictable results.",
                })

        # Validate execution limits
        if agent.max_iterations and agent.max_iterations > 50:
            warnings.append({
                "field": "max_iterations",
                "message": "High iteration count may lead to long execution times.",
            })

        # Validate tools
        if agent.tools:
            # Tool validation will integrate with ToolRegistry when available.
            for _tool_name in agent.tools:
                pass

        return AgentValidationResponse(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    def _generate_agent_key(self, tenant_id: str, name: str) -> str:
        """Generate unique agent key.

        Args:
            tenant_id: Tenant ID.
            name: Agent name.

        Returns:
            Unique agent key in format 'tenant-{id}:{slug}'.
        """
        # Create slug from name
        slug = name.lower().replace(" ", "-").replace("_", "-")
        # Remove special characters
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        # Limit length
        slug = slug[:50]

        return f"{tenant_id}:{slug}"
