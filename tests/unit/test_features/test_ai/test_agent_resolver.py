"""Unit tests for Agent Resolver."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from example_service.core.database import NotFoundError
from example_service.features.ai.agent_resolver import AgentResolver
from example_service.features.ai.models import Agent
from example_service.features.ai.repository import AgentRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock database session."""
    return AsyncMock()


@pytest.fixture
def sample_agent() -> Agent:
    """Create a sample agent for testing."""
    return Agent(
        id=uuid.uuid4(),
        agent_key="tenant-123:test-agent",
        name="Test Agent",
        description="A test agent",
        tenant_id="tenant-123",
        agent_type="rag",
        is_prebuilt=False,
        model="gpt-4o",
        provider="openai",
        temperature=0.7,
        max_tokens=4096,
        system_prompt="You are a helpful assistant.",
        tools={"search": {"enabled": True, "config": {}}},
        config={"key": "value"},
        is_active=True,
        version="1.0.0",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def prebuilt_agent() -> Agent:
    """Create a prebuilt agent for testing."""
    return Agent(
        id=uuid.uuid4(),
        agent_key="system:rag_agent",
        name="RAG Agent",
        description="Prebuilt RAG agent",
        tenant_id=None,
        agent_type="rag",
        is_prebuilt=True,
        prebuilt_template="rag_agent",
        model="gpt-4o",
        provider="openai",
        temperature=0.7,
        max_tokens=4096,
        system_prompt="You are a RAG assistant with access to knowledge bases.",
        tools={"search_knowledge_base": {"enabled": True, "config": {}}},
        is_active=True,
        version="1.0.0",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestAgentResolver:
    """Tests for AgentResolver."""

    @pytest.mark.asyncio
    async def test_resolve_by_id_found(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test resolving agent by ID when it exists."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        with patch.object(
            resolver.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            agent, config = await resolver.resolve_agent(agent_id=sample_agent.id)

            assert agent == sample_agent
            assert isinstance(config, dict)
            assert config["model"] == "gpt-4o"
            assert config["temperature"] == 0.7
            assert config["system_prompt"] == sample_agent.system_prompt

    @pytest.mark.asyncio
    async def test_resolve_by_id_not_found(self, mock_session: AsyncMock) -> None:
        """Test resolving non-existent agent by ID returns None."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        with patch.object(
            resolver.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            with pytest.raises(NotFoundError):
                await resolver.resolve_agent(agent_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_resolve_by_key_from_database(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test resolving agent by key from database."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        with patch.object(
            resolver.repository, "get_by_key", new_callable=AsyncMock,
        ) as mock_get_by_key:
            mock_get_by_key.return_value = sample_agent

            agent, config = await resolver.resolve_agent(
                agent_key="tenant-123:test-agent",
            )

            assert agent == sample_agent
            assert config["agent_type"] == "rag"

    @pytest.mark.asyncio
    async def test_resolve_by_key_not_found(self, mock_session: AsyncMock) -> None:
        """Test resolving non-existent agent by key returns None."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        with patch.object(
            resolver.repository, "get_by_key", new_callable=AsyncMock,
        ) as mock_get_by_key:
            mock_get_by_key.return_value = None

            with pytest.raises(NotFoundError):
                await resolver.resolve_agent(agent_key="tenant-123:nonexistent")

    @pytest.mark.asyncio
    async def test_resolve_with_runtime_overrides(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test resolving agent with runtime overrides."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        with patch.object(
            resolver.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            runtime_overrides = {
                "temperature": 0.3,
                "max_tokens": 8000,
                "custom_field": "custom_value",
            }

            _agent, config = await resolver.resolve_agent(
                agent_id=sample_agent.id,
                runtime_overrides=runtime_overrides,
            )

            # Verify allowed overrides were applied
            assert config["temperature"] == 0.3
            assert config["max_tokens"] == 8000
            assert "custom_field" not in config
            # Original fields should still exist
            assert config["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_agent_to_config_dict(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test converting agent to config dictionary."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        config = resolver._agent_to_config_dict(sample_agent)

        assert config["model"] == "gpt-4o"
        assert config["provider"] == "openai"
        assert config["temperature"] == 0.7
        assert config["max_tokens"] == 4096
        assert config["system_prompt"] == "You are a helpful assistant."
        assert config["agent_type"] == "rag"
        assert config["tools"][0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_agent_to_config_dict_handles_none_values(
        self, mock_session: AsyncMock,
    ) -> None:
        """Test config dict handles None values correctly."""
        resolver = AgentResolver(mock_session)

        minimal_agent = Agent(
            id=uuid.uuid4(),
            agent_key="test:minimal",
            name="Minimal",
            tenant_id="tenant-123",
            agent_type="simple",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Test",
            temperature=None,  # Explicitly None
            max_tokens=None,
            tools=None,
            config=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        config = resolver._agent_to_config_dict(minimal_agent)

        # None values should not cause errors
        assert config["model"] == "gpt-4o"
        assert config.get("temperature") is None
        assert config.get("tools") == []

    def test_merge_overrides(self, mock_session: AsyncMock) -> None:
        """Test merging runtime overrides with base config."""
        resolver = AgentResolver(mock_session)

        base_config = {
            "model": "gpt-4o",
            "temperature": 0.7,
            "max_tokens": 4096,
            "system_prompt": "Base prompt",
        }

        overrides = {
            "temperature": 0.3,  # Override existing
            "custom_field": "new",  # Add new field
        }

        merged = resolver._merge_overrides(base_config, overrides)

        assert merged["model"] == "gpt-4o"  # Unchanged
        assert merged["temperature"] == 0.3  # Overridden
        assert merged["max_tokens"] == 4096  # Unchanged
        assert "custom_field" not in merged  # Not allowed

    def test_merge_overrides_preserves_base(self, mock_session: AsyncMock) -> None:
        """Test merge doesn't mutate base config."""
        resolver = AgentResolver(mock_session)

        base_config = {"temperature": 0.7}
        overrides = {"temperature": 0.3}

        merged = resolver._merge_overrides(base_config, overrides)

        # Original should be unchanged
        assert base_config["temperature"] == 0.7
        # Merged should have new value
        assert merged["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_get_prebuilt_templates(
        self,
        mock_session: AsyncMock,
        prebuilt_agent: Agent,
    ) -> None:
        """Test getting list of prebuilt templates."""
        resolver = AgentResolver(mock_session)

        with patch.object(
            resolver.repository, "get_prebuilt_agents", new_callable=AsyncMock,
        ) as mock_get_prebuilt:
            code_agent = Agent(
                id=uuid.uuid4(),
                agent_key="system:code_agent",
                name="Code Agent",
                description="Code agent",
                tenant_id=None,
                agent_type="code",
                is_prebuilt=True,
                model="gpt-4o",
                provider="openai",
                temperature=0.2,
                max_tokens=2048,
                system_prompt="Write code",
                tools={"code_runner": {"enabled": True, "config": {}}},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            analysis_agent = Agent(
                id=uuid.uuid4(),
                agent_key="system:data_analysis_agent",
                name="Data Analysis Agent",
                description="Analyzes data",
                tenant_id=None,
                agent_type="analysis",
                is_prebuilt=True,
                model="gpt-4o",
                provider="openai",
                temperature=0.1,
                max_tokens=4096,
                system_prompt="Analyze data",
                tools={"analytics": {"enabled": True, "config": {}}},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            mock_get_prebuilt.return_value = [prebuilt_agent, code_agent, analysis_agent]
            templates = await resolver.get_prebuilt_templates()

        # Should return list of template metadata
        assert isinstance(templates, list)

        # Check that common templates exist
        template_names = [t["name"] for t in templates]
        assert "rag_agent" in template_names
        assert "code_agent" in template_names
        assert "data_analysis_agent" in template_names

        # Verify template structure
        for template in templates:
            assert "name" in template
            assert "display_name" in template
            assert "description" in template
            assert "agent_type" in template
            assert "default_model" in template
            assert "system_prompt" in template

    @pytest.mark.asyncio
    async def test_get_prebuilt_templates_has_required_fields(
        self,
        mock_session: AsyncMock,
        prebuilt_agent: Agent,
    ) -> None:
        """Test prebuilt templates have all required fields."""
        resolver = AgentResolver(mock_session)

        with patch.object(
            resolver.repository, "get_prebuilt_agents", new_callable=AsyncMock,
        ) as mock_get_prebuilt:
            mock_get_prebuilt.return_value = [prebuilt_agent]
            templates = await resolver.get_prebuilt_templates()

        for template in templates:
            # Required fields
            assert template["name"]
            assert template["display_name"]
            assert template["agent_type"]
            assert template["default_model"]
            assert template["default_provider"]
            assert template["system_prompt"]

            # Optional but expected fields
            assert "description" in template
            assert "available_tools" in template
            assert "default_temperature" in template

    @pytest.mark.asyncio
    async def test_resolve_respects_tenant_isolation(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test resolver enforces tenant isolation."""
        # Service tenant is different from agent tenant
        resolver = AgentResolver(mock_session, tenant_id="tenant-999")
        sample_agent.tenant_id = "tenant-123"

        with patch.object(
            resolver.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent
            with pytest.raises(PermissionError):
                await resolver.resolve_agent(agent_id=sample_agent.id)

    @pytest.mark.asyncio
    async def test_resolve_allows_system_agents(
        self, mock_session: AsyncMock, prebuilt_agent: Agent,
    ) -> None:
        """Test resolver allows access to system prebuilt agents."""
        resolver = AgentResolver(mock_session, tenant_id="tenant-123")

        with patch.object(
            resolver.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = prebuilt_agent

            # System agents (tenant_id=None) should be accessible to all tenants
            agent, config = await resolver.resolve_agent(agent_id=prebuilt_agent.id)

            assert agent == prebuilt_agent
            assert config is not None
            assert config["agent_type"] == "rag"

    @pytest.mark.asyncio
    async def test_resolve_requires_agent_id_or_key(
        self, mock_session: AsyncMock,
    ) -> None:
        """Test resolving without ID or key returns None."""
        resolver = AgentResolver(mock_session)

        # Call without agent_id or agent_key
        with pytest.raises(ValueError):
            await resolver.resolve_agent()
