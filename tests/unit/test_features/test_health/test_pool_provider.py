"""Tests for DatabasePoolHealthProvider."""

from unittest.mock import MagicMock

import pytest

from example_service.core.schemas.common import HealthStatus
from example_service.features.health.providers import (
    DatabasePoolHealthProvider,
    ProviderConfig,
)


@pytest.fixture
def mock_engine():
    """Create a mock async engine with a configurable pool."""
    engine = MagicMock()
    return engine


@pytest.fixture
def mock_queue_pool():
    """Create a mock QueuePool with configurable statistics."""
    pool = MagicMock()
    type(pool).__name__ = "QueuePool"

    # Set default values
    pool.size.return_value = 10
    pool.checkedout.return_value = 3
    pool.checkedin.return_value = 7
    pool.overflow.return_value = 0

    return pool


@pytest.fixture
def mock_null_pool():
    """Create a mock NullPool for test environments."""
    pool = MagicMock()
    type(pool).__name__ = "NullPool"
    return pool


class TestDatabasePoolHealthProviderInitialization:
    """Test provider initialization and validation."""

    def test_initialization_with_defaults(self, mock_engine):
        """Test provider initializes with default thresholds."""
        provider = DatabasePoolHealthProvider(engine=mock_engine)

        assert provider.name == "database_pool"
        assert provider._degraded_threshold == 0.7
        assert provider._unhealthy_threshold == 0.9
        assert provider._engine is mock_engine

    def test_initialization_with_custom_thresholds(self, mock_engine):
        """Test provider initializes with custom thresholds."""
        provider = DatabasePoolHealthProvider(
            engine=mock_engine,
            degraded_threshold=0.6,
            unhealthy_threshold=0.8,
        )

        assert provider._degraded_threshold == 0.6
        assert provider._unhealthy_threshold == 0.8

    def test_initialization_with_config(self, mock_engine):
        """Test provider initializes with ProviderConfig."""
        config = ProviderConfig(timeout=10.0, enabled=True)
        provider = DatabasePoolHealthProvider(
            engine=mock_engine,
            config=config,
        )

        assert provider._config is config

    def test_invalid_degraded_threshold_too_low(self, mock_engine):
        """Test initialization fails with degraded threshold below 0.0."""
        with pytest.raises(ValueError, match="degraded_threshold must be between 0.0 and 1.0"):
            DatabasePoolHealthProvider(
                engine=mock_engine,
                degraded_threshold=-0.1,
            )

    def test_invalid_degraded_threshold_too_high(self, mock_engine):
        """Test initialization fails with degraded threshold above 1.0."""
        with pytest.raises(ValueError, match="degraded_threshold must be between 0.0 and 1.0"):
            DatabasePoolHealthProvider(
                engine=mock_engine,
                degraded_threshold=1.5,
            )

    def test_invalid_unhealthy_threshold_too_low(self, mock_engine):
        """Test initialization fails with unhealthy threshold below 0.0."""
        with pytest.raises(ValueError, match="unhealthy_threshold must be between 0.0 and 1.0"):
            DatabasePoolHealthProvider(
                engine=mock_engine,
                unhealthy_threshold=-0.1,
            )

    def test_invalid_unhealthy_threshold_too_high(self, mock_engine):
        """Test initialization fails with unhealthy threshold above 1.0."""
        with pytest.raises(ValueError, match="unhealthy_threshold must be between 0.0 and 1.0"):
            DatabasePoolHealthProvider(
                engine=mock_engine,
                unhealthy_threshold=1.5,
            )

    def test_degraded_threshold_not_less_than_unhealthy(self, mock_engine):
        """Test initialization fails when degraded >= unhealthy threshold."""
        with pytest.raises(
            ValueError, match="degraded_threshold.*must be less than.*unhealthy_threshold"
        ):
            DatabasePoolHealthProvider(
                engine=mock_engine,
                degraded_threshold=0.9,
                unhealthy_threshold=0.7,
            )

    def test_degraded_threshold_equal_to_unhealthy(self, mock_engine):
        """Test initialization fails when thresholds are equal."""
        with pytest.raises(
            ValueError, match="degraded_threshold.*must be less than.*unhealthy_threshold"
        ):
            DatabasePoolHealthProvider(
                engine=mock_engine,
                degraded_threshold=0.8,
                unhealthy_threshold=0.8,
            )


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderHealthy:
    """Test healthy pool scenarios."""

    async def test_healthy_pool_low_utilization(self, mock_engine, mock_queue_pool):
        """Test healthy status with low pool utilization (< 70%)."""
        # Configure pool: 3 out of 10 connections in use (30%)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 3
        mock_queue_pool.checkedin.return_value = 7
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.HEALTHY
        assert "Pool healthy" in result.message
        assert "30.0%" in result.message
        assert result.latency_ms < 100  # Should be very fast

        # Check metadata
        assert result.metadata["pool_size"] == 10
        assert result.metadata["checked_out"] == 3
        assert result.metadata["checked_in"] == 7
        assert result.metadata["overflow"] == 0
        assert result.metadata["utilization_percent"] == 30.0
        assert result.metadata["available"] == 7
        assert result.metadata["pool_class"] == "QueuePool"

    async def test_healthy_pool_zero_utilization(self, mock_engine, mock_queue_pool):
        """Test healthy status with no connections in use."""
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 0
        mock_queue_pool.checkedin.return_value = 10
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.HEALTHY
        assert result.metadata["utilization_percent"] == 0.0

    async def test_healthy_pool_with_overflow(self, mock_engine, mock_queue_pool):
        """Test healthy status accounting for overflow connections."""
        # 5 out of 15 total connections (10 + 5 overflow) = 33.3%
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 5
        mock_queue_pool.checkedin.return_value = 5
        mock_queue_pool.overflow.return_value = 5

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.HEALTHY
        assert result.metadata["overflow"] == 5
        # Utilization should be 5/15 = 33.33%
        assert 33.0 <= result.metadata["utilization_percent"] <= 34.0


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderDegraded:
    """Test degraded pool scenarios."""

    async def test_degraded_pool_70_percent_utilization(self, mock_engine, mock_queue_pool):
        """Test degraded status at exactly 70% utilization."""
        # 7 out of 10 connections in use (70%)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 7
        mock_queue_pool.checkedin.return_value = 3
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.DEGRADED
        assert "Pool utilization elevated" in result.message
        assert "70.0%" in result.message
        assert result.metadata["utilization_percent"] == 70.0

    async def test_degraded_pool_80_percent_utilization(self, mock_engine, mock_queue_pool):
        """Test degraded status between thresholds (80%)."""
        # 8 out of 10 connections in use (80%)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 8
        mock_queue_pool.checkedin.return_value = 2
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.DEGRADED
        assert result.metadata["utilization_percent"] == 80.0

    async def test_degraded_pool_just_below_unhealthy(self, mock_engine, mock_queue_pool):
        """Test degraded status just below unhealthy threshold (89%)."""
        # 89 out of 100 connections in use
        mock_queue_pool.size.return_value = 100
        mock_queue_pool.checkedout.return_value = 89
        mock_queue_pool.checkedin.return_value = 11
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.DEGRADED
        assert result.metadata["utilization_percent"] == 89.0


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderUnhealthy:
    """Test unhealthy pool scenarios."""

    async def test_unhealthy_pool_90_percent_utilization(self, mock_engine, mock_queue_pool):
        """Test unhealthy status at exactly 90% utilization."""
        # 9 out of 10 connections in use (90%)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 9
        mock_queue_pool.checkedin.return_value = 1
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert "Pool critically high" in result.message
        assert "90.0%" in result.message
        assert result.metadata["utilization_percent"] == 90.0

    async def test_unhealthy_pool_95_percent_utilization(self, mock_engine, mock_queue_pool):
        """Test unhealthy status at high utilization (95%)."""
        # 19 out of 20 connections in use (95%)
        mock_queue_pool.size.return_value = 20
        mock_queue_pool.checkedout.return_value = 19
        mock_queue_pool.checkedin.return_value = 1
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert result.metadata["utilization_percent"] == 95.0

    async def test_unhealthy_pool_full_utilization(self, mock_engine, mock_queue_pool):
        """Test unhealthy status with 100% pool utilization."""
        # All 10 connections in use (100%)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 10
        mock_queue_pool.checkedin.return_value = 0
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert result.metadata["utilization_percent"] == 100.0
        assert result.metadata["available"] == 0


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderNullPool:
    """Test NullPool handling (test environments)."""

    async def test_null_pool_returns_healthy(self, mock_engine, mock_null_pool):
        """Test NullPool is always healthy with informative message."""
        mock_engine.pool = mock_null_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.HEALTHY
        assert "NullPool" in result.message
        assert result.metadata["pool_class"] == "NullPool"
        assert "creates connections on-demand" in result.metadata["note"]

    async def test_null_pool_metadata_structure(self, mock_engine, mock_null_pool):
        """Test NullPool returns proper metadata structure."""
        mock_engine.pool = mock_null_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert "pool_class" in result.metadata
        assert "note" in result.metadata
        # Should not have pool statistics
        assert "pool_size" not in result.metadata
        assert "checked_out" not in result.metadata


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderEdgeCases:
    """Test edge cases and error handling."""

    async def test_zero_capacity_pool(self, mock_engine, mock_queue_pool):
        """Test handling of pool with zero capacity."""
        mock_queue_pool.size.return_value = 0
        mock_queue_pool.checkedout.return_value = 0
        mock_queue_pool.checkedin.return_value = 0
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        # Should handle division by zero gracefully
        assert result.status == HealthStatus.HEALTHY
        assert result.metadata["utilization_percent"] == 0.0

    async def test_unsupported_pool_type(self, mock_engine):
        """Test handling of pool without expected methods."""
        # Create a pool that doesn't have the expected methods
        unsupported_pool = MagicMock()
        type(unsupported_pool).__name__ = "CustomPool"

        # Make methods raise AttributeError
        unsupported_pool.size.side_effect = AttributeError(
            "'CustomPool' object has no attribute 'size'"
        )

        mock_engine.pool = unsupported_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        # Should return healthy with note about unsupported type
        assert result.status == HealthStatus.HEALTHY
        assert "Unsupported pool type" in result.message
        assert result.metadata["pool_class"] == "CustomPool"
        assert "not available" in result.metadata["note"]

    async def test_unexpected_exception_during_check(self, mock_engine, mock_queue_pool):
        """Test handling of unexpected exceptions."""
        # Simulate unexpected error
        mock_queue_pool.size.side_effect = RuntimeError("Unexpected error")
        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY
        assert "Pool check error" in result.message
        assert "error" in result.metadata
        assert "error_type" in result.metadata
        assert result.metadata["error_type"] == "RuntimeError"

    async def test_fast_execution_time(self, mock_engine, mock_queue_pool):
        """Test that pool check executes very quickly (< 10ms)."""
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 5
        mock_queue_pool.checkedin.return_value = 5
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        # Should be very fast since it's just reading stats
        assert result.latency_ms < 10.0


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderCustomThresholds:
    """Test provider with custom threshold configurations."""

    async def test_custom_thresholds_healthy(self, mock_engine, mock_queue_pool):
        """Test custom thresholds with healthy pool."""
        # 5 out of 10 = 50% (below custom 60% degraded threshold)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 5
        mock_queue_pool.checkedin.return_value = 5
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(
            engine=mock_engine,
            degraded_threshold=0.6,
            unhealthy_threshold=0.85,
        )
        result = await provider.check_health()

        assert result.status == HealthStatus.HEALTHY

    async def test_custom_thresholds_degraded(self, mock_engine, mock_queue_pool):
        """Test custom thresholds with degraded pool."""
        # 7 out of 10 = 70% (between 60% and 85%)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 7
        mock_queue_pool.checkedin.return_value = 3
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(
            engine=mock_engine,
            degraded_threshold=0.6,
            unhealthy_threshold=0.85,
        )
        result = await provider.check_health()

        assert result.status == HealthStatus.DEGRADED

    async def test_custom_thresholds_unhealthy(self, mock_engine, mock_queue_pool):
        """Test custom thresholds with unhealthy pool."""
        # 9 out of 10 = 90% (above custom 85% unhealthy threshold)
        mock_queue_pool.size.return_value = 10
        mock_queue_pool.checkedout.return_value = 9
        mock_queue_pool.checkedin.return_value = 1
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(
            engine=mock_engine,
            degraded_threshold=0.6,
            unhealthy_threshold=0.85,
        )
        result = await provider.check_health()

        assert result.status == HealthStatus.UNHEALTHY


@pytest.mark.asyncio
class TestDatabasePoolHealthProviderMetadata:
    """Test metadata structure and contents."""

    async def test_metadata_contains_all_required_fields(self, mock_engine, mock_queue_pool):
        """Test metadata includes all documented fields."""
        mock_queue_pool.size.return_value = 20
        mock_queue_pool.checkedout.return_value = 8
        mock_queue_pool.checkedin.return_value = 12
        mock_queue_pool.overflow.return_value = 3

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        # Verify all required metadata fields
        required_fields = [
            "pool_size",
            "checked_out",
            "checked_in",
            "overflow",
            "utilization_percent",
            "available",
            "pool_class",
        ]

        for field in required_fields:
            assert field in result.metadata, f"Missing required field: {field}"

    async def test_metadata_values_accuracy(self, mock_engine, mock_queue_pool):
        """Test metadata values match pool statistics exactly."""
        mock_queue_pool.size.return_value = 15
        mock_queue_pool.checkedout.return_value = 6
        mock_queue_pool.checkedin.return_value = 9
        mock_queue_pool.overflow.return_value = 2

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        assert result.metadata["pool_size"] == 15
        assert result.metadata["checked_out"] == 6
        assert result.metadata["checked_in"] == 9
        assert result.metadata["overflow"] == 2
        assert result.metadata["available"] == 9

        # Verify utilization calculation: 6 / (15 + 2) = 35.29%
        expected_utilization = round((6 / 17) * 100, 2)
        assert result.metadata["utilization_percent"] == expected_utilization

    async def test_metadata_utilization_percentage_precision(self, mock_engine, mock_queue_pool):
        """Test utilization percentage is rounded to 2 decimal places."""
        # Create scenario with precise decimal: 7/30 = 23.333...%
        mock_queue_pool.size.return_value = 30
        mock_queue_pool.checkedout.return_value = 7
        mock_queue_pool.checkedin.return_value = 23
        mock_queue_pool.overflow.return_value = 0

        mock_engine.pool = mock_queue_pool

        provider = DatabasePoolHealthProvider(engine=mock_engine)
        result = await provider.check_health()

        # Should be rounded to 2 decimals: 23.33
        assert result.metadata["utilization_percent"] == 23.33
