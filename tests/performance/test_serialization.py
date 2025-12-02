"""Performance tests for serialization operations.

Tests the performance of Pydantic model serialization/deserialization
which is a critical path in API request/response handling.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field


# Sample models for benchmarking
class SimpleModel(BaseModel):
    id: str
    name: str
    created_at: datetime


class NestedModel(BaseModel):
    id: str
    name: str
    tags: list[str]
    metadata: dict[str, str]
    created_at: datetime


class ComplexModel(BaseModel):
    id: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    nested: list[NestedModel] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None


@pytest.fixture
def simple_data():
    """Simple model data."""
    return {
        "id": str(uuid4()),
        "name": "Test Entity",
        "created_at": datetime.now(UTC),
    }


@pytest.fixture
def nested_data():
    """Nested model data."""
    return {
        "id": str(uuid4()),
        "name": "Test Entity",
        "tags": ["tag1", "tag2", "tag3"],
        "metadata": {f"key_{i}": f"value_{i}" for i in range(10)},
        "created_at": datetime.now(UTC),
    }


@pytest.fixture
def complex_data(nested_data):
    """Complex model data."""
    return {
        "id": str(uuid4()),
        "name": "Complex Entity",
        "description": "A complex entity with nested data",
        "tags": ["complex", "nested", "performance"],
        "metadata": {f"key_{i}": f"value_{i}" for i in range(20)},
        "nested": [nested_data for _ in range(10)],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


class TestModelValidation:
    """Benchmark Pydantic model validation."""

    @pytest.mark.benchmark(group="model-validation")
    def test_simple_model_validation(self, benchmark, simple_data):
        """Benchmark simple model validation."""
        result = benchmark(SimpleModel.model_validate, simple_data)
        assert result.id == simple_data["id"]

    @pytest.mark.benchmark(group="model-validation")
    def test_nested_model_validation(self, benchmark, nested_data):
        """Benchmark nested model validation."""
        result = benchmark(NestedModel.model_validate, nested_data)
        assert result.id == nested_data["id"]

    @pytest.mark.benchmark(group="model-validation")
    def test_complex_model_validation(self, benchmark, complex_data):
        """Benchmark complex model validation."""
        result = benchmark(ComplexModel.model_validate, complex_data)
        assert result.id == complex_data["id"]


class TestModelSerialization:
    """Benchmark Pydantic model serialization."""

    @pytest.mark.benchmark(group="model-serialization")
    def test_simple_model_dump(self, benchmark, simple_data):
        """Benchmark simple model dump."""
        model = SimpleModel.model_validate(simple_data)
        result = benchmark(model.model_dump)
        assert "id" in result

    @pytest.mark.benchmark(group="model-serialization")
    def test_nested_model_dump(self, benchmark, nested_data):
        """Benchmark nested model dump."""
        model = NestedModel.model_validate(nested_data)
        result = benchmark(model.model_dump)
        assert "id" in result

    @pytest.mark.benchmark(group="model-serialization")
    def test_complex_model_dump(self, benchmark, complex_data):
        """Benchmark complex model dump."""
        model = ComplexModel.model_validate(complex_data)
        result = benchmark(model.model_dump)
        assert "id" in result

    @pytest.mark.benchmark(group="model-serialization")
    def test_model_dump_json(self, benchmark, complex_data):
        """Benchmark model dump to JSON string."""
        model = ComplexModel.model_validate(complex_data)
        result = benchmark(model.model_dump_json)
        assert isinstance(result, str)


class TestJSONOperations:
    """Benchmark JSON serialization/deserialization."""

    @pytest.mark.benchmark(group="json")
    def test_json_dumps(self, benchmark, benchmark_data):
        """Benchmark JSON dumps."""
        data = benchmark_data["sample_json"]
        result = benchmark(json.dumps, data)
        assert isinstance(result, str)

    @pytest.mark.benchmark(group="json")
    def test_json_loads(self, benchmark, benchmark_data):
        """Benchmark JSON loads."""
        json_str = json.dumps(benchmark_data["sample_json"])
        result = benchmark(json.loads, json_str)
        assert isinstance(result, dict)
