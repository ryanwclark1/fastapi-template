"""Integration tests for Agent Configuration API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
import uuid

from fastapi import status
import pytest
from sqlalchemy import select

from example_service.features.ai.models import Agent
from example_service.features.ai.schemas import (
    AgentCloneRequest,
    AgentCreate,
    AgentUpdate,
    CreateFromTemplateRequest,
    ToolConfigSchema,
)

if TYPE_CHECKING:
    from httpx import AsyncClient, Response
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    Response = Any


def _assert_status(response: Response, expected_status: int) -> None:
    """Helpful assertion that dumps response content for debugging."""
    if response.status_code != expected_status:
        body: Any
        try:
            body = response.json()
        except ValueError:  # pragma: no cover - fall back to text
            body = response.text
        error_message = (
            f"Expected status {expected_status}, got {response.status_code}: {body}"
        )
        raise AssertionError(error_message)


@pytest.mark.asyncio
class TestAgentCRUDEndpoints:
    """Integration tests for agent CRUD operations."""

    async def test_create_agent_success(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test creating a new agent via API."""
        agent_data = {
            "name": "Test RAG Agent",
            "description": "A test RAG agent for integration testing",
            "agent_type": "rag",
            "system_prompt": "You are a helpful RAG assistant with access to knowledge bases.",
            "model": "gpt-4o",
            "provider": "openai",
            "temperature": 0.7,
            "max_tokens": 4096,
            "tools": [
                {
                    "name": "search_knowledge_base",
                    "enabled": True,
                    "config": {"index": "main"},
                    "requires_confirmation": False,
                },
            ],
            "tags": ["rag", "knowledge-base"],
        }

        response = await async_client.post(
            "/api/v1/agents",
            json=agent_data,
            headers=auth_headers,
        )

        _assert_status(response, status.HTTP_201_CREATED)
        data = response.json()

        assert data["name"] == "Test RAG Agent"
        assert data["agent_type"] == "rag"
        assert data["is_prebuilt"] is False
        assert data["tenant_id"] == test_tenant_id
        assert "id" in data
        assert "agent_key" in data

        # Verify in database
        agent_id = uuid.UUID(data["id"])
        result = await db_session.execute(
            select(Agent).where(Agent.id == agent_id),
        )
        db_agent = result.scalar_one_or_none()

        assert db_agent is not None
        assert db_agent.name == "Test RAG Agent"

    async def test_create_agent_duplicate_name_fails(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test creating agent with duplicate name returns conflict."""
        # Create first agent
        existing_agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:duplicate-agent",
            name="Duplicate Agent",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Test",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(existing_agent)
        await db_session.commit()

        # Try to create duplicate
        agent_data = {
            "name": "Duplicate Agent",  # Same name
            "agent_type": "rag",
            "system_prompt": "Different prompt",
        }

        response = await async_client.post(
            "/api/v1/agents",
            json=agent_data,
            headers=auth_headers,
        )

        assert response.status_code == 409  # Conflict

    async def test_list_agents_with_pagination(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test listing agents with pagination."""
        # Create multiple test agents
        for i in range(5):
            agent = Agent(
                id=uuid.uuid4(),
                agent_key=f"{test_tenant_id}:agent-{i}",
                name=f"Agent {i}",
                tenant_id=test_tenant_id,
                agent_type="rag" if i % 2 == 0 else "code_generation",
                is_prebuilt=False,
                model="gpt-4o",
                provider="openai",
                system_prompt=f"Agent {i} prompt",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db_session.add(agent)
        await db_session.commit()

        # Test pagination
        response = await async_client.get(
            "/api/v1/agents?page=1&limit=3",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 5
        assert len(data["items"]) == 3
        assert data["page"] == 1
        assert data["limit"] == 3
        assert data["has_next"] is True

    async def test_list_agents_with_filters(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test listing agents with agent_type filter."""
        # Create agents of different types
        rag_agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:rag-filter",
            name="RAG Filter Test",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="RAG",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        code_agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:code-filter",
            name="Code Filter Test",
            tenant_id=test_tenant_id,
            agent_type="code_generation",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Code",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add_all([rag_agent, code_agent])
        await db_session.commit()

        # Filter by agent_type
        response = await async_client.get(
            "/api/v1/agents?agent_type=rag",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # All returned agents should be RAG type
        for agent in data["items"]:
            assert agent["agent_type"] == "rag"

    async def test_get_agent_by_id(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test getting agent by ID."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:get-test",
            name="Get Test Agent",
            description="Testing GET endpoint",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            temperature=0.7,
            system_prompt="Test",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        response = await async_client.get(
            f"/api/v1/agents/{agent.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(agent.id)
        assert data["name"] == "Get Test Agent"
        assert data["description"] == "Testing GET endpoint"

    async def test_get_agent_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting non-existent agent returns 404."""
        response = await async_client.get(
            f"/api/v1/agents/{uuid.uuid4()}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_update_agent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test updating an agent."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:update-test",
            name="Original Name",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            temperature=0.7,
            system_prompt="Original prompt",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        update_data = {
            "name": "Updated Name",
            "temperature": 0.5,
            "system_prompt": "Updated prompt",
        }

        response = await async_client.put(
            f"/api/v1/agents/{agent.id}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Updated Name"
        assert data["temperature"] == 0.5
        assert data["system_prompt"] == "Updated prompt"

        # Verify in database
        await db_session.refresh(agent)
        assert agent.name == "Updated Name"

    async def test_update_prebuilt_agent_fails(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
    ) -> None:
        """Test updating prebuilt agent returns error."""
        prebuilt = Agent(
            id=uuid.uuid4(),
            agent_key="system:rag_agent",
            name="RAG Agent",
            tenant_id=None,
            agent_type="rag",
            is_prebuilt=True,
            model="gpt-4o",
            provider="openai",
            system_prompt="Prebuilt",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(prebuilt)
        await db_session.commit()

        update_data = {"name": "Modified"}

        response = await async_client.put(
            f"/api/v1/agents/{prebuilt.id}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "prebuilt" in response.json()["detail"].lower()

    async def test_delete_agent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test soft deleting an agent."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:delete-test",
            name="Delete Test",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Test",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        response = await async_client.delete(
            f"/api/v1/agents/{agent.id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify soft delete (is_active = False)
        await db_session.refresh(agent)
        assert agent.is_active is False


@pytest.mark.asyncio
class TestAgentTemplateEndpoints:
    """Integration tests for template-related endpoints."""

    async def test_list_templates(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        prebuilt_agent: Agent,
    ) -> None:
        """Test listing available prebuilt templates."""
        response = await async_client.get(
            "/api/v1/agents/templates",
            headers=auth_headers,
        )

        _assert_status(response, status.HTTP_200_OK)
        templates = response.json()

        assert isinstance(templates, list)
        assert len(templates) > 0

        # Verify template structure
        for template in templates:
            assert "name" in template
            assert "display_name" in template
            assert "agent_type" in template
            assert "system_prompt" in template

    async def test_create_from_template(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
        prebuilt_agent: Agent,
    ) -> None:
        """Test creating agent from template."""
        template_data = {
            "template_name": "rag_agent",
            "name": "My Custom RAG",
            "description": "Created from template",
            "customizations": {
                "temperature": 0.3,
                "max_tokens": 8000,
            },
        }

        response = await async_client.post(
            "/api/v1/agents/from-template",
            json=template_data,
            headers=auth_headers,
        )

        _assert_status(response, status.HTTP_201_CREATED)
        data = response.json()

        assert data["name"] == "My Custom RAG"
        assert data["agent_type"] == "rag"
        assert data["temperature"] == 0.3
        assert data["max_tokens"] == 8000
        assert data["prebuilt_template"] == "rag_agent"
        assert data["is_prebuilt"] is False

    async def test_create_from_invalid_template_fails(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test creating from non-existent template returns 404."""
        template_data = {
            "template_name": "nonexistent_template",
            "name": "Test Agent",
            "customizations": {},
        }

        response = await async_client.post(
            "/api/v1/agents/from-template",
            json=template_data,
            headers=auth_headers,
        )

        assert response.status_code == 404


@pytest.mark.asyncio
class TestAgentCloningEndpoints:
    """Integration tests for agent cloning."""

    async def test_clone_agent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test cloning an existing agent."""
        source_agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:source",
            name="Source Agent",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            temperature=0.7,
            system_prompt="Source prompt",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(source_agent)
        await db_session.commit()

        clone_data = {
            "name": "Cloned Agent",
            "description": "Cloned from Source Agent",
            "customizations": {"temperature": 0.3},
        }

        response = await async_client.post(
            f"/api/v1/agents/{source_agent.id}/clone",
            json=clone_data,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Cloned Agent"
        assert data["agent_type"] == source_agent.agent_type
        assert data["temperature"] == 0.3  # Customized
        assert data["id"] != str(source_agent.id)  # Different ID


@pytest.mark.asyncio
class TestAgentValidationEndpoints:
    """Integration tests for agent validation."""

    async def test_validate_agent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test validating an agent configuration."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:validate-test",
            name="Validation Test",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            temperature=0.7,
            system_prompt="You are a helpful assistant.",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        response = await async_client.post(
            f"/api/v1/agents/{agent.id}/validate",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "valid" in data
        assert "errors" in data
        assert "warnings" in data
        assert "suggestions" in data

    async def test_validate_agent_with_incompatible_model(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test validating agent with incompatible model/provider."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:invalid-combo",
            name="Invalid Combo",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="claude-3-opus",  # Anthropic model
            provider="openai",  # Wrong provider!
            system_prompt="Test",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        response = await async_client.post(
            f"/api/v1/agents/{agent.id}/validate",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert len(data["errors"]) > 0


@pytest.mark.asyncio
class TestAgentActivationEndpoints:
    """Integration tests for agent activation/deactivation."""

    async def test_deactivate_agent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test deactivating an agent."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:deactivate-test",
            name="Deactivate Test",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Test",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        response = await async_client.patch(
            f"/api/v1/agents/{agent.id}/deactivate",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    async def test_activate_agent(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        test_tenant_id: str,
    ) -> None:
        """Test activating a deactivated agent."""
        agent = Agent(
            id=uuid.uuid4(),
            agent_key=f"{test_tenant_id}:activate-test",
            name="Activate Test",
            tenant_id=test_tenant_id,
            agent_type="rag",
            is_prebuilt=False,
            model="gpt-4o",
            provider="openai",
            system_prompt="Test",
            is_active=False,  # Deactivated
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(agent)
        await db_session.commit()

        response = await async_client.patch(
            f"/api/v1/agents/{agent.id}/activate",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is True
