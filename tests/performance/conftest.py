"""Performance test configuration and fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest


@pytest.fixture
def async_benchmark(benchmark):
    """Async-aware benchmark fixture.

    Wraps pytest-benchmark to handle async functions properly.

    Usage:
        async def test_async_operation(async_benchmark):
            result = await async_benchmark(my_async_function, arg1, arg2)
            assert result is not None
    """

    def _wrapper(func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run async function in benchmark."""

        def sync_wrapper():
            return asyncio.get_event_loop().run_until_complete(func(*args, **kwargs))

        return benchmark(sync_wrapper)

    return _wrapper


@pytest.fixture
def benchmark_data():
    """Provide sample data for benchmarks.

    Returns:
        Dictionary with sample data of various sizes.
    """
    return {
        "small_list": list(range(100)),
        "medium_list": list(range(10_000)),
        "large_list": list(range(100_000)),
        "small_dict": {f"key_{i}": f"value_{i}" for i in range(100)},
        "medium_dict": {f"key_{i}": f"value_{i}" for i in range(10_000)},
        "sample_text": "This is a sample text for full-text search benchmarking. " * 100,
        "sample_json": {
            "id": "test-123",
            "name": "Test Entity",
            "description": "A test entity for benchmarking",
            "tags": ["test", "benchmark", "performance"],
            "metadata": {f"key_{i}": f"value_{i}" for i in range(50)},
        },
    }


@pytest.fixture
def benchmark_group(benchmark):
    """Create grouped benchmarks for comparison.

    Usage:
        def test_comparisons(benchmark_group):
            with benchmark_group("implementation_a"):
                result_a = implementation_a()

            with benchmark_group("implementation_b"):
                result_b = implementation_b()
    """
    from contextlib import contextmanager

    groups = {}

    @contextmanager
    def group(name: str):
        benchmark.group = name
        yield
        groups[name] = benchmark.stats

    return group
