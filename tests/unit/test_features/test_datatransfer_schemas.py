"""Tests for data transfer schemas."""

from __future__ import annotations

import pytest

from example_service.features.datatransfer.schemas import (
    ExportFormat,
    ExportRequest,
    FilterCondition,
    FilterOperator,
    ImportFormat,
)


class TestFilterOperator:
    """Tests for FilterOperator enum."""

    def test_all_operators_defined(self):
        """Test all expected operators are defined."""
        operators = [
            "eq", "ne", "gt", "gte", "lt", "lte",
            "contains", "in", "not_in", "is_null", "is_not_null"
        ]
        for op in operators:
            assert op in [o.value for o in FilterOperator]

    def test_operator_values(self):
        """Test operator values match expected strings."""
        assert FilterOperator.EQ == "eq"
        assert FilterOperator.GT == "gt"
        assert FilterOperator.CONTAINS == "contains"
        assert FilterOperator.IN == "in"
        assert FilterOperator.IS_NULL == "is_null"


class TestFilterCondition:
    """Tests for FilterCondition model."""

    def test_default_operator_is_eq(self):
        """Test default operator is equality."""
        condition = FilterCondition(field="name", value="test")
        assert condition.operator == FilterOperator.EQ

    def test_all_fields_serialize(self):
        """Test all fields serialize correctly."""
        condition = FilterCondition(
            field="status",
            operator=FilterOperator.IN,
            value=["active", "pending"]
        )
        data = condition.model_dump()
        assert data["field"] == "status"
        assert data["operator"] == "in"
        assert data["value"] == ["active", "pending"]

    def test_null_value_for_is_null_operator(self):
        """Test is_null operator doesn't require value."""
        condition = FilterCondition(
            field="deleted_at",
            operator=FilterOperator.IS_NULL
        )
        assert condition.value is None


class TestExportRequest:
    """Tests for ExportRequest model."""

    def test_minimal_request(self):
        """Test minimal export request."""
        request = ExportRequest(entity_type="reminders")
        assert request.entity_type == "reminders"
        assert request.format == ExportFormat.CSV
        assert request.filters is None
        assert request.filter_conditions is None

    def test_with_filter_conditions(self):
        """Test request with filter conditions."""
        request = ExportRequest(
            entity_type="reminders",
            format=ExportFormat.JSON,
            filter_conditions=[
                FilterCondition(field="is_completed", operator=FilterOperator.EQ, value=False),
                FilterCondition(field="created_at", operator=FilterOperator.GTE, value="2024-01-01"),
            ]
        )
        assert len(request.filter_conditions) == 2
        assert request.filter_conditions[0].field == "is_completed"
        assert request.filter_conditions[1].operator == FilterOperator.GTE

    def test_backward_compatible_simple_filters(self):
        """Test backward compatibility with simple filters dict."""
        request = ExportRequest(
            entity_type="reminders",
            filters={"is_completed": True}
        )
        assert request.filters == {"is_completed": True}

    def test_field_selection(self):
        """Test field selection."""
        request = ExportRequest(
            entity_type="reminders",
            fields=["id", "title", "created_at"]
        )
        assert request.fields == ["id", "title", "created_at"]


class TestExportFormat:
    """Tests for ExportFormat enum."""

    def test_supported_formats(self):
        """Test all supported export formats."""
        assert ExportFormat.CSV == "csv"
        assert ExportFormat.JSON == "json"
        assert ExportFormat.EXCEL == "xlsx"


class TestImportFormat:
    """Tests for ImportFormat enum."""

    def test_supported_formats(self):
        """Test all supported import formats."""
        assert ImportFormat.CSV == "csv"
        assert ImportFormat.JSON == "json"
        assert ImportFormat.EXCEL == "xlsx"
