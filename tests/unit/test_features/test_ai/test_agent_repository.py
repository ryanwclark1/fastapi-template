"""Unit tests for Agent Repository."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from sqlalchemy import select

from example_service.core.database.search import SearchResult
from example_service.features.ai.models import Agent
from example_service.features.ai.repository import AgentRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.add = AsyncMock()
    session.commit = AsyncMock()
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
        tenant_id=None,  # System agent
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


class TestAgentRepository:
    """Tests for AgentRepository."""

    def test_init(self) -> None:
        """Test repository initialization."""
        repo = AgentRepository()
        assert repo.model == Agent

    @pytest.mark.asyncio
    async def test_get_by_key_found(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test getting agent by key when it exists."""
        repo = AgentRepository()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_agent
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_key(mock_session, "tenant-123:test-agent")

        assert result == sample_agent
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_key_not_found(self, mock_session: AsyncMock) -> None:
        """Test getting agent by key when it doesn't exist."""
        repo = AgentRepository()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_key(mock_session, "nonexistent-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_for_tenant_with_prebuilt(
        self, mock_session: AsyncMock, sample_agent: Agent, prebuilt_agent: Agent,
    ) -> None:
        """Test listing agents for a tenant including prebuilt agents."""
        repo = AgentRepository()

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        # Mock items query
        mock_items_result = MagicMock()
        mock_items_result.scalars.return_value.all.return_value = [
            sample_agent,
            prebuilt_agent,
        ]

        mock_session.execute.side_effect = [mock_count_result, mock_items_result]

        result = await repo.list_for_tenant(
            mock_session,
            tenant_id="tenant-123",
            include_prebuilt=True,
            limit=20,
            offset=0,
        )

        assert isinstance(result, SearchResult)
        assert result.total == 2
        assert len(result.items) == 2
        assert sample_agent in result.items
        assert prebuilt_agent in result.items

    @pytest.mark.asyncio
    async def test_list_for_tenant_without_prebuilt(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test listing agents for a tenant excluding prebuilt agents."""
        repo = AgentRepository()

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        # Mock items query
        mock_items_result = MagicMock()
        mock_items_result.scalars.return_value.all.return_value = [sample_agent]

        mock_session.execute.side_effect = [mock_count_result, mock_items_result]

        result = await repo.list_for_tenant(
            mock_session,
            tenant_id="tenant-123",
            include_prebuilt=False,
            limit=20,
            offset=0,
        )

        assert isinstance(result, SearchResult)
        assert result.total == 1
        assert len(result.items) == 1
        assert sample_agent in result.items

    @pytest.mark.asyncio
    async def test_list_for_tenant_with_filters(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test listing agents with agent_type and is_active filters."""
        repo = AgentRepository()

        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        # Mock items query
        mock_items_result = MagicMock()
        mock_items_result.scalars.return_value.all.return_value = [sample_agent]

        mock_session.execute.side_effect = [mock_count_result, mock_items_result]

        result = await repo.list_for_tenant(
            mock_session,
            tenant_id="tenant-123",
            agent_type="rag",
            is_active=True,
            limit=20,
            offset=0,
        )

        assert result.total == 1
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_get_with_relationships(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test getting agent with relationships loaded."""
        repo = AgentRepository()

        with patch.object(repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = sample_agent

            result = await repo.get_with_relationships(
                mock_session, sample_agent.id,
            )

            assert result == sample_agent
            mock_get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clone_agent(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test cloning an agent with customizations."""
        repo = AgentRepository()

        # Mock get to return source agent
        with patch.object(repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = sample_agent

            cloned = await repo.clone_agent(
                mock_session,
                source_id=sample_agent.id,
                tenant_id="tenant-456",
                name="Cloned Agent",
                agent_key="tenant-456:cloned-agent",
                customizations={"temperature": 0.3},
                created_by_id=uuid.uuid4(),
            )

            assert cloned.name == "Cloned Agent"
            assert cloned.agent_key == "tenant-456:cloned-agent"
            assert cloned.tenant_id == "tenant-456"
            assert cloned.temperature == 0.3
            assert cloned.agent_type == sample_agent.agent_type
            assert cloned.is_prebuilt is False

            mock_session.add.assert_called_once()
            mock_session.flush.assert_awaited_once()
            mock_session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clone_agent_not_found(self, mock_session: AsyncMock) -> None:
        """Test cloning a non-existent agent raises error."""
        repo = AgentRepository()

        with patch.object(repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(ValueError, match=r"Source agent .* not found"):
                await repo.clone_agent(
                    mock_session,
                    source_id=uuid.uuid4(),
                    tenant_id="tenant-456",
                    name="Cloned Agent",
                    agent_key="tenant-456:cloned",
                    customizations={},
                    created_by_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_count_by_tenant(self, mock_session: AsyncMock) -> None:
        """Test counting agents by tenant."""
        repo = AgentRepository()

        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        count = await repo.count_by_tenant(mock_session, "tenant-123")

        assert count == 5
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_prebuilt_agents(
        self, mock_session: AsyncMock, prebuilt_agent: Agent,
    ) -> None:
        """Test getting all prebuilt agents."""
        repo = AgentRepository()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [prebuilt_agent]
        mock_session.execute.return_value = mock_result

        agents = await repo.get_prebuilt_agents(mock_session)

        assert len(agents) == 1
        assert agents[0] == prebuilt_agent
        assert agents[0].is_prebuilt is True
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_last_used_at(
        self, mock_session: AsyncMock, sample_agent: Agent,
    ) -> None:
        """Test updating agent's last_used_at timestamp."""
        repo = AgentRepository()

        with patch.object(repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = sample_agent

            await repo.update_last_used_at(mock_session, sample_agent.id)

            # Verify session methods were called
            mock_session.flush.assert_awaited_once()
            mock_session.refresh.assert_awaited_once()
