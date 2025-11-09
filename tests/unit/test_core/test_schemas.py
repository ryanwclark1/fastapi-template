"""Unit tests for core schemas."""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from example_service.core.schemas.auth import AuthUser
from example_service.core.schemas.base import PaginatedResponse


@pytest.mark.unit
class TestAuthUser:
    """Test suite for AuthUser schema."""

    def test_auth_user_from_dict(self, sample_user_data):
        """Test creating AuthUser from dictionary."""
        user = AuthUser(**sample_user_data)

        assert user.user_id == "test-user-123"
        assert user.email == "test@example.com"
        assert "user" in user.roles
        assert "read" in user.permissions

    def test_auth_user_has_permission(self, sample_user_data):
        """Test has_permission method."""
        user = AuthUser(**sample_user_data)

        assert user.has_permission("read") is True
        assert user.has_permission("write") is True
        assert user.has_permission("delete") is False

    def test_auth_user_has_role(self, sample_user_data):
        """Test has_role method."""
        user = AuthUser(**sample_user_data)

        assert user.has_role("user") is True
        assert user.has_role("admin") is False

    def test_auth_user_can_access_resource(self, sample_user_data):
        """Test can_access_resource method."""
        user = AuthUser(**sample_user_data)

        # Has read/write access to documents
        assert user.can_access_resource("documents", "read") is True
        assert user.can_access_resource("documents", "write") is True
        assert user.can_access_resource("documents", "delete") is False

        # No access to other resources
        assert user.can_access_resource("admin", "read") is False

    def test_auth_user_service_to_service(self):
        """Test service-to-service authentication."""
        user = AuthUser(
            user_id=None,
            service_id="api-gateway",
            roles=["service"],
            permissions=["all"]
        )

        assert user.user_id is None
        assert user.service_id == "api-gateway"
        assert user.has_role("service") is True


@pytest.mark.unit
class TestPaginatedResponse:
    """Test suite for PaginatedResponse schema."""

    def test_paginated_response_creation(self):
        """Test creating PaginatedResponse."""
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        response = PaginatedResponse.create(
            items=items,
            total=10,
            page=1,
            page_size=3
        )

        assert len(response.items) == 3
        assert response.total == 10
        assert response.page == 1
        assert response.page_size == 3
        assert response.total_pages == 4  # ceil(10/3)

    def test_paginated_response_empty(self):
        """Test PaginatedResponse with no items."""
        response = PaginatedResponse.create(
            items=[],
            total=0,
            page=1,
            page_size=10
        )

        assert len(response.items) == 0
        assert response.total == 0
        assert response.total_pages == 0

    def test_paginated_response_total_pages_calculation(self):
        """Test total_pages calculation."""
        # Exact division
        response1 = PaginatedResponse.create(
            items=[], total=20, page=1, page_size=10
        )
        assert response1.total_pages == 2

        # With remainder
        response2 = PaginatedResponse.create(
            items=[], total=25, page=1, page_size=10
        )
        assert response2.total_pages == 3

        # Single page
        response3 = PaginatedResponse.create(
            items=[], total=5, page=1, page_size=10
        )
        assert response3.total_pages == 1
