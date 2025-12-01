"""Unit tests for tag schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

pytest.importorskip("dateutil.rrule", reason="Reminder schemas require python-dateutil")

from example_service.features.tags.schemas import (
    AddTagsRequest,
    ReminderTagsUpdate,
    RemoveTagsRequest,
    TagCreate,
    TagResponse,
    TagUpdate,
    TagWithCountResponse,
)


class TestTagCreate:
    """Tests for TagCreate schema."""

    def test_valid_tag(self):
        """Valid tag data should pass validation."""
        tag = TagCreate(name="work", color="#FF5733", description="Work tasks")

        assert tag.name == "work"
        assert tag.color == "#FF5733"
        assert tag.description == "Work tasks"

    def test_name_normalization(self):
        """Tag names should be lowercased and trimmed."""
        tag = TagCreate(name="  WORK  ")

        assert tag.name == "work"

    def test_minimal_tag(self):
        """Tag with only name should be valid."""
        tag = TagCreate(name="urgent")

        assert tag.name == "urgent"
        assert tag.color is None
        assert tag.description is None

    def test_invalid_color_format(self):
        """Invalid color format should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            TagCreate(name="test", color="red")

        assert "color" in str(exc_info.value).lower()

    def test_valid_hex_colors(self):
        """Various valid hex colors should pass."""
        colors = ["#000000", "#FFFFFF", "#ff5733", "#ABC123"]

        for color in colors:
            tag = TagCreate(name="test", color=color)
            assert tag.color == color

    def test_name_too_long(self):
        """Name exceeding max length should raise error."""
        with pytest.raises(ValidationError):
            TagCreate(name="x" * 51)

    def test_empty_name(self):
        """Empty name should raise validation error."""
        with pytest.raises(ValidationError):
            TagCreate(name="")


class TestTagUpdate:
    """Tests for TagUpdate schema."""

    def test_partial_update(self):
        """Update with only some fields should work."""
        update = TagUpdate(color="#123ABC")

        assert update.name is None
        assert update.color == "#123ABC"
        assert update.description is None

    def test_name_normalization(self):
        """Updated names should be normalized."""
        update = TagUpdate(name="  NEW NAME  ")

        assert update.name == "new name"

    def test_empty_update(self):
        """Empty update (all None) should be valid."""
        update = TagUpdate()

        assert update.name is None
        assert update.color is None
        assert update.description is None


class TestTagResponse:
    """Tests for TagResponse schema."""

    def test_from_attributes(self):
        """Should convert from ORM model."""
        from datetime import datetime
        from uuid import uuid4

        class MockTag:
            id = uuid4()
            name = "test-tag"
            color = "#FF0000"
            description = "Test"
            created_at = datetime.now()
            updated_at = datetime.now()

        response = TagResponse.model_validate(MockTag())

        assert response.name == "test-tag"
        assert response.color == "#FF0000"


class TestTagWithCountResponse:
    """Tests for TagWithCountResponse schema."""

    def test_includes_count(self):
        """Should include reminder count."""
        from datetime import datetime
        from uuid import uuid4

        response = TagWithCountResponse(
            id=uuid4(),
            name="test",
            color=None,
            description=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            reminder_count=42,
        )

        assert response.reminder_count == 42

    def test_default_count(self):
        """Default count should be zero."""
        from datetime import datetime
        from uuid import uuid4

        response = TagWithCountResponse(
            id=uuid4(),
            name="test",
            color=None,
            description=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        assert response.reminder_count == 0


class TestReminderTagsUpdate:
    """Tests for ReminderTagsUpdate schema."""

    def test_valid_tag_ids(self):
        """Valid UUID list should pass."""
        from uuid import uuid4

        ids = [uuid4(), uuid4(), uuid4()]
        update = ReminderTagsUpdate(tag_ids=ids)

        assert len(update.tag_ids) == 3

    def test_empty_list_allowed(self):
        """Empty list should be valid (removes all tags)."""
        update = ReminderTagsUpdate(tag_ids=[])

        assert update.tag_ids == []


class TestAddTagsRequest:
    """Tests for AddTagsRequest schema."""

    def test_valid_request(self):
        """Valid request should pass."""
        from uuid import uuid4

        request = AddTagsRequest(tag_ids=[uuid4()])

        assert len(request.tag_ids) == 1

    def test_empty_list_rejected(self):
        """Empty list should be rejected (must add at least one)."""
        with pytest.raises(ValidationError):
            AddTagsRequest(tag_ids=[])


class TestRemoveTagsRequest:
    """Tests for RemoveTagsRequest schema."""

    def test_valid_request(self):
        """Valid request should pass."""
        from uuid import uuid4

        request = RemoveTagsRequest(tag_ids=[uuid4(), uuid4()])

        assert len(request.tag_ids) == 2

    def test_empty_list_rejected(self):
        """Empty list should be rejected."""
        with pytest.raises(ValidationError):
            RemoveTagsRequest(tag_ids=[])
