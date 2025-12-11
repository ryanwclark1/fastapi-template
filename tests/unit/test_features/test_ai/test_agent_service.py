"""Unit tests for Agent Service."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from example_service.core.database import NotFoundError
from example_service.features.ai.models import Agent
from example_service.features.ai.repository import AgentRepository
from example_service.features.ai.schemas import (
    AgentCloneRequest,
    AgentCreate,
    AgentUpdate,
    AgentValidationResponse,
    CreateFromTemplateRequest,
    ToolConfigSchema,
)
from example_service.features.ai.service import AgentService


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock()
    session.add = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    return session


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
        model="gpt-4o",
        provider="openai",
        temperature=0.7,
        max_tokens=4096,
        system_prompt="You are a RAG assistant.",
        is_active=True,
        version="1.0.0",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestAgentService:
    """Tests for AgentService."""

    @pytest.mark.asyncio
    async def test_create_agent_success(self, mock_session: AsyncMock) -> None:
        """Test creating a new agent successfully."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        # Mock repository methods
        with patch.object(
            service.repository, "get_by_key", new_callable=AsyncMock,
        ) as mock_get_by_key:
            mock_get_by_key.return_value = None  # No existing agent

            data = AgentCreate(
                name="Test Agent",
                description="Test description",
                agent_type="rag",
                system_prompt="You are a helpful assistant.",
                model="gpt-4o",
                provider="openai",
                temperature=0.7,
                tools=[
                    ToolConfigSchema(
                        name="search",
                        enabled=True,
                        config={},
                        requires_confirmation=False,
                    ),
                ],
            )

            user_id = uuid.uuid4()
            agent = await service.create_agent(
                data=data, user_id=user_id, tenant_id="tenant-123",
            )

            # Verify agent was created
            assert agent.name == "Test Agent"
            assert agent.agent_type == "rag"
            assert agent.tenant_id == "tenant-123"
            assert agent.is_prebuilt is False
            assert agent.created_by_id == user_id

            # Verify session methods called
            mock_session.add.assert_called_once()
            mock_session.commit.assert_awaited_once()
            mock_session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_agent_duplicate_key(self, mock_session: AsyncMock) -> None:
        """Test creating agent with duplicate key raises error."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        existing_agent = Agent(
            id=uuid.uuid4(),
            agent_key="tenant-123:test-agent",
            name="Existing Agent",
            tenant_id="tenant-123",
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Test",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        with patch.object(
            service.repository, "get_by_key", new_callable=AsyncMock,
        ) as mock_get_by_key:
            mock_get_by_key.return_value = existing_agent

            data = AgentCreate(
                name="Test Agent",  # Will generate same key
                agent_type="rag",
                system_prompt="You are a helpful assistant.",
            )

            with pytest.raises(ValueError, match="already exists"):
                await service.create_agent(
                    data=data, user_id=uuid.uuid4(), tenant_id="tenant-123",
                )

    @pytest.mark.asyncio
    async def test_create_agent_missing_tenant(self, mock_session: AsyncMock) -> None:
        """Test creating agent without tenant raises error."""
        service = AgentService(mock_session, tenant_id=None)

        data = AgentCreate(
            name="Test Agent",
            agent_type="rag",
            system_prompt="You are a helpful assistant.",
        )

        with pytest.raises(ValueError, match="Tenant ID required"):
            await service.create_agent(data=data, user_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_update_agent_success(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test updating an agent successfully."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        with patch.object(
            service.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            data = AgentUpdate(
                name="Updated Agent",
                temperature=0.5,
            )

            user_id = uuid.uuid4()
            updated = await service.update_agent(
                agent_id=sample_agent.id,
                data=data,
                user_id=user_id,
            )

            assert updated.name == "Updated Agent"
            assert updated.temperature == 0.5
            assert updated.updated_by_id == user_id
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_prebuilt_agent_fails(
        self, mock_session: AsyncMock, prebuilt_agent: Agent,
    ) -> None:
        """Test updating prebuilt agent raises error."""
        service = AgentService(mock_session, tenant_id=None)

        with patch.object(
            service.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = prebuilt_agent

            data = AgentUpdate(name="Modified")

            with pytest.raises(ValueError, match="Cannot modify prebuilt agents"):
                await service.update_agent(
                    agent_id=prebuilt_agent.id,
                    data=data,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_update_agent_not_found(self, mock_session: AsyncMock) -> None:
        """Test updating non-existent agent raises error."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        with patch.object(
            service.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            data = AgentUpdate(name="Updated")

            with pytest.raises(NotFoundError, match="not found"):
                await service.update_agent(
                    agent_id=uuid.uuid4(),
                    data=data,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_update_agent_cross_tenant_fails(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test updating agent from different tenant fails."""
        service = AgentService(mock_session, tenant_id="tenant-999")
        sample_agent.tenant_id = "tenant-123"

        with patch.object(
            service.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            data = AgentUpdate(name="Updated")

            with pytest.raises(ValueError, match="different tenant"):
                await service.update_agent(
                    agent_id=sample_agent.id,
                    data=data,
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_get_agent_success(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test getting agent by ID."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        with patch.object(
            service.repository, "get_with_relationships", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            agent = await service.get_agent(sample_agent.id)

            assert agent == sample_agent
            mock_get.assert_awaited_once_with(mock_session, sample_agent.id)

    @pytest.mark.asyncio
    async def test_get_agent_tenant_isolation(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test tenant isolation when getting agent."""
        service = AgentService(mock_session, tenant_id="tenant-999")
        sample_agent.tenant_id = "tenant-123"

        with patch.object(
            service.repository, "get_with_relationships", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            # Should return None due to tenant mismatch
            agent = await service.get_agent(sample_agent.id)

            assert agent is None

    @pytest.mark.asyncio
    async def test_clone_agent_success(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test cloning an agent successfully."""
        service = AgentService(mock_session, tenant_id="tenant-456")

        cloned_agent = Agent(
            id=uuid.uuid4(),
            agent_key="tenant-456:cloned-agent",
            name="Cloned Agent",
            tenant_id="tenant-456",
            agent_type=sample_agent.agent_type,
            is_prebuilt=False,
            model=sample_agent.model,
            provider=sample_agent.provider,
            temperature=0.3,  # Customized
            system_prompt=sample_agent.system_prompt,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        with patch.object(
            service, "get_agent", new_callable=AsyncMock,
        ) as mock_get_agent, patch.object(
            service.repository, "clone_agent", new_callable=AsyncMock,
        ) as mock_clone:
            mock_get_agent.return_value = sample_agent
            mock_clone.return_value = cloned_agent

            data = AgentCloneRequest(
                name="Cloned Agent",
                description="Cloned from Test Agent",
                customizations={"temperature": 0.3},
            )

            clone = await service.clone_agent(
                source_id=sample_agent.id,
                data=data,
                user_id=uuid.uuid4(),
                tenant_id="tenant-456",
            )

            assert clone.name == "Cloned Agent"
            assert clone.temperature == 0.3
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clone_agent_source_not_found(
        self, mock_session: AsyncMock,
    ) -> None:
        """Test cloning non-existent agent raises error."""
        service = AgentService(mock_session, tenant_id="tenant-456")

        with patch.object(
            service, "get_agent", new_callable=AsyncMock,
        ) as mock_get_agent:
            mock_get_agent.return_value = None

            data = AgentCloneRequest(
                name="Cloned Agent",
                customizations={},
            )

            with pytest.raises(NotFoundError, match="not found"):
                await service.clone_agent(
                    source_id=uuid.uuid4(),
                    data=data,
                    user_id=uuid.uuid4(),
                    tenant_id="tenant-456",
                )

    @pytest.mark.asyncio
    async def test_delete_agent_success(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test soft deleting an agent."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        with patch.object(
            service.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = sample_agent

            await service.delete_agent(sample_agent.id)

            # Verify agent was deactivated
            assert sample_agent.is_active is False
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_prebuilt_agent_fails(
        self, mock_session: AsyncMock, prebuilt_agent: Agent,
    ) -> None:
        """Test deleting prebuilt agent raises error."""
        service = AgentService(mock_session, tenant_id=None)

        with patch.object(
            service.repository, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = prebuilt_agent

            with pytest.raises(ValueError, match="Cannot delete prebuilt agents"):
                await service.delete_agent(prebuilt_agent.id)

    @pytest.mark.asyncio
    async def test_validate_agent_success(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test validating an agent configuration."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        with patch.object(
            service, "get_agent", new_callable=AsyncMock,
        ) as mock_get_agent:
            mock_get_agent.return_value = sample_agent

            validation = await service.validate_agent(sample_agent.id)

            assert isinstance(validation, AgentValidationResponse)
            assert validation.valid is True
            assert len(validation.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_agent_with_errors(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test validating agent with configuration errors."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        # Set up agent with issues
        sample_agent.model = "claude-3-opus"
        sample_agent.provider = "openai"  # Incompatible!
        sample_agent.temperature = 2.5  # Too high

        with patch.object(
            service, "get_agent", new_callable=AsyncMock,
        ) as mock_get_agent:
            mock_get_agent.return_value = sample_agent

            validation = await service.validate_agent(sample_agent.id)

            assert validation.valid is False
            assert len(validation.errors) > 0
            assert any("compatible" in err["message"].lower() for err in validation.errors)

    @pytest.mark.asyncio
    async def test_validate_agent_not_found(self, mock_session: AsyncMock) -> None:
        """Test validating non-existent agent raises error."""
        service = AgentService(mock_session, tenant_id="tenant-123")

        with patch.object(
            service, "get_agent", new_callable=AsyncMock,
        ) as mock_get_agent:
            mock_get_agent.return_value = None

            with pytest.raises(NotFoundError, match="not found"):
                await service.validate_agent(uuid.uuid4())

    def test_generate_agent_key(self, mock_session: AsyncMock) -> None:
        """Test agent key generation."""
        service = AgentService(mock_session)

        key = service._generate_agent_key("tenant-123", "My Test Agent!")

        assert key == "tenant-123:my-test-agent"
        assert "!" not in key
        assert " " not in key

    def test_generate_agent_key_long_name(self, mock_session: AsyncMock) -> None:
        """Test agent key generation with very long name."""
        service = AgentService(mock_session)

        long_name = "A" * 100
        key = service._generate_agent_key("tenant-123", long_name)

        # Should be truncated to 50 chars after tenant prefix
        slug_part = key.split(":")[1]
        assert len(slug_part) <= 50
