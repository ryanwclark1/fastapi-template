"""Performance tests using pytest-benchmark.

This module contains micro-benchmarks for measuring performance
of critical code paths.

Usage:
    # Run all benchmarks
    pytest tests/performance/ --benchmark-only

    # Run with comparison to baseline
    pytest tests/performance/ --benchmark-compare

    # Save benchmark results
    pytest tests/performance/ --benchmark-save=baseline

    # Disable benchmarks during regular test runs
    pytest tests/ --benchmark-disable

Fixtures:
    benchmark: The pytest-benchmark fixture for timing code
    async_benchmark: Async-aware benchmark wrapper

Configuration in pyproject.toml:
    [tool.pytest.ini_options]
    markers = ["benchmark: mark test as benchmark"]
"""
