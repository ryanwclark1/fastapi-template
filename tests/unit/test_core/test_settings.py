"""Unit tests for modular Pydantic Settings v2."""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from example_service.core.settings.app import AppSettings
from example_service.core.settings.auth import AuthSettings
from example_service.core.settings.loader import (
    clear_all_caches,
    get_app_settings,
    get_auth_settings,
    get_db_settings,
    get_logging_settings,
    get_otel_settings,
    get_rabbit_settings,
    get_redis_settings,
)
from example_service.core.settings.logging_ import LoggingSettings
from example_service.core.settings.otel import OtelSettings
from example_service.core.settings.postgres import PostgresSettings
from example_service.core.settings.rabbit import RabbitSettings
from example_service.core.settings.redis import RedisSettings


@pytest.mark.unit
class TestAppSettings:
    """Test suite for AppSettings."""

    def test_app_settings_defaults(self):
        """Test AppSettings default values."""
        settings = AppSettings()

        assert settings.service_name == "test-service"  # From env var in conftest
        assert settings.environment == "test"  # From env var
        assert settings.debug is True  # From env var
        assert settings.title == "Example Service API"
        assert settings.version == "1.0.0"

    def test_app_settings_frozen(self):
        """Test that AppSettings instances are frozen (immutable)."""
        settings = AppSettings()

        with pytest.raises(ValidationError):
            settings.debug = False  # Should raise error

    def test_app_settings_cors_origins(self):
        """Test CORS origins configuration."""
        settings = AppSettings(cors_origins=["http://localhost:3000"])

        assert len(settings.cors_origins) == 1
        assert "http://localhost:3000" in settings.cors_origins

    def test_app_settings_docs_enabled(self):
        """Test docs_enabled property."""
        settings = AppSettings(disable_docs=False)
        assert settings.docs_enabled is True

        settings2 = AppSettings(disable_docs=True)
        assert settings2.docs_enabled is False

    def test_app_settings_get_docs_url(self):
        """Test get_docs_url method respects disable_docs."""
        settings = AppSettings(disable_docs=False, docs_url="/docs")
        assert settings.get_docs_url() == "/docs"

        settings2 = AppSettings(disable_docs=True, docs_url="/docs")
        assert settings2.get_docs_url() is None


@pytest.mark.unit
class TestPostgresSettings:
    """Test suite for PostgresSettings."""

    def test_postgres_settings_defaults(self):
        """Test PostgresSettings default values."""
        settings = PostgresSettings()

        assert settings.database_url is None
        assert settings.pool_size == 10
        assert settings.pool_min == 1
        assert settings.max_overflow == 10
        assert settings.pool_timeout == 30
        assert settings.pool_recycle == 1800
        assert settings.pool_pre_ping is True
        assert settings.echo_sql is False

    def test_postgres_settings_is_configured(self):
        """Test is_configured property."""
        settings = PostgresSettings()
        assert settings.is_configured is False

        settings2 = PostgresSettings(
            database_url="postgresql+psycopg://localhost/test"
        )
        assert settings2.is_configured is True

    def test_postgres_settings_get_sqlalchemy_url(self):
        """Test get_sqlalchemy_url method."""
        url = "postgresql+psycopg://user:pass@localhost:5432/testdb"
        settings = PostgresSettings(database_url=url)

        assert settings.get_sqlalchemy_url() == url

    def test_postgres_settings_get_psycopg_url(self):
        """Test get_psycopg_url removes driver specifier."""
        url = "postgresql+psycopg://user:pass@localhost:5432/testdb"
        settings = PostgresSettings(database_url=url)

        psycopg_url = settings.get_psycopg_url()
        assert "+psycopg" not in psycopg_url
        assert psycopg_url == "postgresql://user:pass@localhost:5432/testdb"

    def test_postgres_settings_frozen(self):
        """Test that PostgresSettings instances are frozen."""
        settings = PostgresSettings()

        with pytest.raises(ValidationError):
            settings.pool_size = 20


@pytest.mark.unit
class TestRedisSettings:
    """Test suite for RedisSettings."""

    def test_redis_settings_defaults(self):
        """Test RedisSettings default values."""
        settings = RedisSettings()

        assert settings.redis_url is None
        assert settings.default_ttl == 3600
        assert settings.auth_token_ttl == 300
        assert settings.pool_size == 10
        assert settings.max_retries == 3
        assert settings.key_prefix == "example-service:"

    def test_redis_settings_is_configured(self):
        """Test is_configured property."""
        settings = RedisSettings()
        assert settings.is_configured is False

        settings2 = RedisSettings(redis_url="redis://localhost:6379/0")
        assert settings2.is_configured is True

    def test_redis_settings_get_prefixed_key(self):
        """Test get_prefixed_key method."""
        settings = RedisSettings(key_prefix="test:")

        key = settings.get_prefixed_key("user:123")
        assert key == "test:user:123"


@pytest.mark.unit
class TestRabbitSettings:
    """Test suite for RabbitSettings."""

    def test_rabbit_settings_defaults(self):
        """Test RabbitSettings default values."""
        settings = RabbitSettings()

        assert settings.rabbitmq_url is None
        assert settings.queue_prefix == "example-service"
        assert settings.exchange == "example-service"
        assert settings.prefetch_count == 100
        assert settings.max_consumers == 10

    def test_rabbit_settings_is_configured(self):
        """Test is_configured property."""
        settings = RabbitSettings()
        assert settings.is_configured is False

        settings2 = RabbitSettings(rabbitmq_url="amqp://localhost:5672/")
        assert settings2.is_configured is True

    def test_rabbit_settings_get_prefixed_queue(self):
        """Test get_prefixed_queue method."""
        settings = RabbitSettings(queue_prefix="my-service")

        queue = settings.get_prefixed_queue("tasks")
        assert queue == "my-service.tasks"


@pytest.mark.unit
class TestAuthSettings:
    """Test suite for AuthSettings."""

    def test_auth_settings_defaults(self):
        """Test AuthSettings default values."""
        settings = AuthSettings()

        assert settings.service_url is None
        assert settings.token_cache_ttl == 300
        assert settings.token_header == "Authorization"
        assert settings.token_scheme == "Bearer"
        assert settings.request_timeout == 5.0
        assert settings.max_retries == 3

    def test_auth_settings_is_configured(self):
        """Test is_configured property."""
        settings = AuthSettings()
        assert settings.is_configured is False

        settings2 = AuthSettings(service_url="http://auth-service:8000")
        assert settings2.is_configured is True

    def test_auth_settings_get_validation_url(self):
        """Test get_validation_url method."""
        settings = AuthSettings(
            service_url="http://auth-service:8000",
            token_validation_endpoint="/api/v1/validate"
        )

        url = settings.get_validation_url()
        assert url == "http://auth-service:8000/api/v1/validate"


@pytest.mark.unit
class TestLoggingSettings:
    """Test suite for LoggingSettings."""

    def test_logging_settings_defaults(self):
        """Test LoggingSettings default values."""
        settings = LoggingSettings()

        assert settings.level == "DEBUG"  # From env var
        assert settings.json_format is True
        assert settings.include_uvicorn is True
        assert settings.console_enabled is True
        assert settings.log_slow_requests is True


@pytest.mark.unit
class TestOtelSettings:
    """Test suite for OtelSettings."""

    def test_otel_settings_defaults(self):
        """Test OtelSettings default values."""
        settings = OtelSettings()

        assert settings.enabled is False
        assert settings.endpoint is None
        assert settings.service_name == "example-service"
        assert settings.insecure is True
        assert settings.sample_rate == 1.0

    def test_otel_settings_is_configured(self):
        """Test is_configured property."""
        settings = OtelSettings()
        assert settings.is_configured is False

        settings2 = OtelSettings(enabled=True, endpoint="http://tempo:4317")
        assert settings2.is_configured is True

        # enabled=False but has endpoint - still not configured
        settings3 = OtelSettings(enabled=False, endpoint="http://tempo:4317")
        assert settings3.is_configured is False


@pytest.mark.unit
class TestSettingsLoaders:
    """Test suite for settings loader functions."""

    def test_loaders_return_settings(self):
        """Test that all loaders return correct types."""
        assert isinstance(get_app_settings(), AppSettings)
        assert isinstance(get_db_settings(), PostgresSettings)
        assert isinstance(get_redis_settings(), RedisSettings)
        assert isinstance(get_rabbit_settings(), RabbitSettings)
        assert isinstance(get_auth_settings(), AuthSettings)
        assert isinstance(get_logging_settings(), LoggingSettings)
        assert isinstance(get_otel_settings(), OtelSettings)

    def test_loaders_are_cached(self):
        """Test that loaders return same instance (LRU cache)."""
        app1 = get_app_settings()
        app2 = get_app_settings()
        assert app1 is app2  # Same object reference

        db1 = get_db_settings()
        db2 = get_db_settings()
        assert db1 is db2

    def test_clear_all_caches_works(self):
        """Test that clear_all_caches() clears all caches."""
        app1 = get_app_settings()
        clear_all_caches()
        app2 = get_app_settings()

        # Different instances after cache clear
        assert app1 is not app2
        # But same values
        assert app1.service_name == app2.service_name
