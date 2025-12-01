# Health Check System - Complete Guide

This guide covers the comprehensive health check system in the FastAPI template, including configuration, monitoring, and extending with custom providers.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Built-in Providers](#built-in-providers)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Kubernetes Integration](#kubernetes-integration)
- [Prometheus Metrics](#prometheus-metrics)
- [Custom Providers](#custom-providers)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Overview

The health check system provides:

- ✅ **Protocol-based architecture** - Easily extensible with custom providers
- ✅ **10+ built-in providers** - Database, cache, messaging, storage, service discovery
- ✅ **Per-provider configuration** - Fine-grained control over timeouts, thresholds, criticality
- ✅ **Kubernetes-ready** - Liveness, readiness, and startup probes
- ✅ **Rich observability** - Prometheus metrics, history tracking, detailed diagnostics
- ✅ **Fast execution** - Concurrent checks with caching (10s TTL)
- ✅ **Graceful degradation** - Optional dependencies never block startup

### Health Status Levels

| Status | Description | HTTP Code | Use Case |
|--------|-------------|-----------|----------|
| **HEALTHY** | All checks pass | 200 | Service operating normally |
| **DEGRADED** | Some checks slow/warn | 200 | Service functional but performance impacted |
| **UNHEALTHY** | Critical checks fail | 503 | Service cannot handle requests |

---

## Quick Start

### Basic Health Check

```bash
# Simple health check
curl http://localhost:8000/api/v1/health/

# Response
{
  "status": "healthy",
  "timestamp": "2025-12-01T00:00:00Z",
  "service": "example-service",
  "version": "0.1.0",
  "checks": {
    "database": true,
    "cache": true,
    "database_pool": true
  }
}
```

### Detailed Health Check

```bash
# Detailed with metrics
curl http://localhost:8000/api/v1/health/detailed

# Response
{
  "status": "healthy",
  "timestamp": "2025-12-01T00:00:00Z",
  "duration_ms": 45.2,
  "from_cache": false,
  "checks": {
    "database": {
      "healthy": true,
      "status": "healthy",
      "message": "Database connected",
      "latency_ms": 12.5
    },
    "database_pool": {
      "healthy": true,
      "status": "healthy",
      "message": "Pool utilization at 35% (7/20 connections)",
      "latency_ms": 0.8,
      "metadata": {
        "pool_size": 20,
        "checked_out": 7,
        "utilization_percent": 35.0
      }
    }
  }
}
```

### Kubernetes Probes

```bash
# Liveness probe (always 200 if app running)
curl http://localhost:8000/api/v1/health/live

# Readiness probe (200 if ready for traffic)
curl http://localhost:8000/api/v1/health/ready

# Startup probe (200 after initialization)
curl http://localhost:8000/api/v1/health/startup
```

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────┐
│                   Health Router                      │
│              (REST API Endpoints)                    │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│                 HealthService                        │
│         (Auto-configuration, K8s probes)            │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│              HealthAggregator                        │
│  (Concurrent execution, caching, history)           │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼
   ┌─────────┐ ┌────────┐ ┌────────┐ ┌────────┐
   │Database │ │ Cache  │ │RabbitMQ│ │Consul  │
   │Provider │ │Provider│ │Provider│ │Provider│
   └─────────┘ └────────┘ └────────┘ └────────┘
```

### HealthProvider Protocol

All providers implement this simple protocol:

```python
from typing import Protocol
from example_service.features.health.providers import HealthCheckResult

class HealthProvider(Protocol):
    @property
    def name(self) -> str:
        """Unique identifier (e.g., 'database', 'cache')"""
        ...

    async def check_health(self) -> HealthCheckResult:
        """Perform health check"""
        ...
```

---

## Built-in Providers

### 1. DatabaseHealthProvider

Checks PostgreSQL database connectivity.

**What it checks:**
- Database connection (SELECT 1)
- Response latency

**Status levels:**
- HEALTHY: Connected, latency < threshold (default 500ms)
- DEGRADED: Connected, latency > threshold
- UNHEALTHY: Connection failed

**Configuration:**
```bash
HEALTH_DATABASE__ENABLED=true
HEALTH_DATABASE__TIMEOUT=2.0
HEALTH_DATABASE__DEGRADED_THRESHOLD_MS=500.0
HEALTH_DATABASE__CRITICAL_FOR_READINESS=true
```

### 2. DatabasePoolHealthProvider ⭐ **NEW**

Monitors SQLAlchemy connection pool utilization.

**What it checks:**
- Pool utilization percentage
- Available connections
- Overflow connections

**Status levels:**
- HEALTHY: Utilization < 70% (default)
- DEGRADED: Utilization 70-90%
- UNHEALTHY: Utilization > 90%

**Metadata:**
```json
{
  "pool_size": 20,
  "checked_out": 7,
  "checked_in": 13,
  "overflow": 0,
  "utilization_percent": 35.0,
  "available": 13,
  "pool_class": "QueuePool"
}
```

**Why it matters:** Prevents "connection pool exhausted" errors by providing early warnings.

**Configuration:**
```bash
HEALTH_DATABASE_POOL__ENABLED=true
HEALTH_DATABASE_POOL__DEGRADED_THRESHOLD_MS=100.0
```

### 3. RedisHealthProvider

Checks Redis cache connectivity.

**What it checks:**
- Redis health_check() ping
- Response latency

**Status levels:**
- HEALTHY: Connected, responding
- UNHEALTHY: Connection failed

**Configuration:**
```bash
HEALTH_CACHE__ENABLED=true
HEALTH_CACHE__TIMEOUT=1.0
HEALTH_CACHE__CRITICAL_FOR_READINESS=false
```

### 4. RabbitMQHealthProvider

Checks RabbitMQ message broker connectivity.

**What it checks:**
- AMQP connection
- Connection close (cleanup)

**Status levels:**
- HEALTHY: Connection successful
- UNHEALTHY: Connection failed

**Configuration:**
```bash
HEALTH_RABBITMQ__ENABLED=true
HEALTH_RABBITMQ__TIMEOUT=5.0
```

### 5. ConsulHealthProvider ⭐ **NEW**

Monitors Consul service discovery health.

**What it checks (parallel):**
- Agent connectivity
- Leader election status
- Service registration
- Service count

**Status levels:**
- HEALTHY: All checks pass, latency < threshold
- DEGRADED: No leader OR latency > threshold (default 500ms)
- UNHEALTHY: Agent connection failed

**Metadata:**
```json
{
  "agent_address": "127.0.0.1:8500",
  "datacenter": "dc1",
  "leader": "10.0.1.5:8300",
  "services_registered": 3,
  "service_health": "registered"
}
```

**Why it matters:** Critical for microservices architecture - detects service discovery failures.

**Configuration:**
```bash
HEALTH_CONSUL__ENABLED=true
HEALTH_CONSUL__TIMEOUT=3.0
HEALTH_CONSUL__DEGRADED_THRESHOLD_MS=500.0
HEALTH_CONSUL__CRITICAL_FOR_READINESS=false
```

### 6. AccentAuthHealthProvider

Monitors external Accent-Auth service.

**What it checks:**
- Auth service availability (HEAD request)
- Response latency

**Status levels:**
- HEALTHY: Service responds, latency < 100ms
- DEGRADED: Service responds, latency > 100ms
- UNHEALTHY: Service unavailable

**Configuration:**
```bash
HEALTH_ACCENT_AUTH__ENABLED=false
HEALTH_ACCENT_AUTH__TIMEOUT=5.0
```

### 7. S3StorageHealthProvider

Checks S3/MinIO storage connectivity.

**What it checks:**
- Storage service connectivity
- Basic operation (list objects)

**Status levels:**
- HEALTHY: Connected, latency < threshold (default 1000ms)
- DEGRADED: Connected, latency > threshold
- UNHEALTHY: Connection failed

**Configuration:**
```bash
HEALTH_S3__ENABLED=true
HEALTH_S3__TIMEOUT=3.0
```

### 8. RateLimiterHealthProvider

Monitors rate limiter service status.

**What it checks:**
- Rate limiter operational state
- Failure count

**Status levels:**
- HEALTHY: Operating normally
- DEGRADED: In fail-open mode (protection disabled)
- UNHEALTHY: Critical failures

---

## Configuration

### Global Settings

```bash
# Health check system configuration
HEALTH_CACHE_TTL_SECONDS=10.0          # Result cache lifetime
HEALTH_HISTORY_SIZE=100                 # History buffer size
HEALTH_GLOBAL_TIMEOUT=30.0              # Overall check timeout
```

### Per-Provider Configuration

Each provider supports these settings:

```bash
# Pattern: HEALTH_{PROVIDER}__{SETTING}
HEALTH_DATABASE__ENABLED=true
HEALTH_DATABASE__TIMEOUT=2.0
HEALTH_DATABASE__DEGRADED_THRESHOLD_MS=500.0
HEALTH_DATABASE__CRITICAL_FOR_READINESS=true
```

**Settings:**
- `ENABLED`: Enable/disable provider (default: true)
- `TIMEOUT`: Provider-specific timeout in seconds (default: 2.0)
- `DEGRADED_THRESHOLD_MS`: Latency threshold for DEGRADED status (default: 1000.0)
- `CRITICAL_FOR_READINESS`: Include in readiness probe (default: false, except database)

### Configuration in Code

```python
from example_service.core.settings import get_health_settings

# Load settings
settings = get_health_settings()

# Access global settings
print(settings.cache_ttl_seconds)  # 10.0
print(settings.history_size)       # 100

# Access provider config
db_config = settings.database
print(db_config.enabled)                    # True
print(db_config.timeout)                    # 2.0
print(db_config.degraded_threshold_ms)      # 500.0
print(db_config.critical_for_readiness)     # True

# List enabled providers
enabled = settings.list_enabled_providers()
# ['database', 'cache', 'rabbitmq', ...]

# List critical providers
critical = settings.list_critical_providers()
# ['database']
```

### Environment-Specific Configuration

**Development:**
```bash
HEALTH_CACHE_TTL_SECONDS=5.0           # Shorter cache for dev
HEALTH_DATABASE__TIMEOUT=5.0           # More lenient timeout
HEALTH_CONSUL__ENABLED=false           # Disable in dev
```

**Production:**
```bash
HEALTH_CACHE_TTL_SECONDS=10.0          # Longer cache for prod
HEALTH_DATABASE__TIMEOUT=2.0           # Strict timeout
HEALTH_DATABASE__CRITICAL_FOR_READINESS=true
HEALTH_CONSUL__ENABLED=true            # Enable in prod
```

**Testing:**
```bash
HEALTH_CACHE_TTL_SECONDS=0.0           # No caching in tests
HEALTH_DATABASE__TIMEOUT=10.0          # Very lenient
```

---

## API Endpoints

All endpoints are under `/api/v1/health/` (configurable prefix).

### GET /health/

Comprehensive health check with all enabled providers.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-12-01T00:00:00Z",
  "service": "example-service",
  "version": "0.1.0",
  "checks": {
    "database": true,
    "cache": true,
    "database_pool": true,
    "consul": true
  }
}
```

### GET /health/detailed

Detailed health check with latency and metadata.

**Query Parameters:**
- `force_refresh=true`: Bypass cache and run fresh checks

**Response:**
```json
{
  "status": "degraded",
  "timestamp": "2025-12-01T00:00:00Z",
  "duration_ms": 52.3,
  "from_cache": false,
  "checks": {
    "database": {
      "healthy": true,
      "status": "healthy",
      "message": "Database connected",
      "latency_ms": 8.2
    },
    "database_pool": {
      "healthy": false,
      "status": "degraded",
      "message": "Pool utilization at 85% (17/20)",
      "latency_ms": 0.5,
      "metadata": {
        "utilization_percent": 85.0,
        "available": 3
      }
    }
  }
}
```

### GET /health/live

Kubernetes liveness probe - returns 200 if app is running.

**Response:**
```json
{
  "alive": true,
  "timestamp": "2025-12-01T00:00:00Z",
  "service": "example-service"
}
```

### GET /health/ready

Kubernetes readiness probe - checks critical dependencies.

**Response:**
```json
{
  "ready": true,
  "checks": {
    "database": true
  },
  "timestamp": "2025-12-01T00:00:00Z"
}
```

Returns **503** if not ready (critical checks fail).

### GET /health/startup

Kubernetes startup probe - indicates initialization complete.

**Response:**
```json
{
  "started": true,
  "timestamp": "2025-12-01T00:00:00Z"
}
```

### GET /health/history

Historical health check data for trend analysis.

**Query Parameters:**
- `limit`: Number of entries (default: 50, max: 100)
- `provider`: Filter by provider name

**Response:**
```json
{
  "history": [
    {
      "timestamp": "2025-12-01T00:00:00Z",
      "overall_status": "healthy",
      "duration_ms": 45.2,
      "checks": {
        "database": "healthy",
        "cache": "healthy"
      }
    }
  ],
  "count": 1,
  "limit": 50
}
```

### GET /health/stats

Aggregated statistics for health checks.

**Response:**
```json
{
  "overall": {
    "total_checks": 1234,
    "uptime_percent": 99.5,
    "current_status": "healthy",
    "avg_duration_ms": 42.3
  },
  "providers": {
    "database": {
      "total_checks": 1234,
      "healthy": 1225,
      "degraded": 8,
      "unhealthy": 1,
      "uptime_percent": 99.9,
      "last_status": "healthy"
    }
  }
}
```

### GET /health/providers

List registered health providers.

**Response:**
```json
{
  "providers": [
    "database",
    "database_pool",
    "cache",
    "rabbitmq",
    "consul"
  ],
  "count": 5
}
```

### GET /health/cache

Cache status information.

**Response:**
```json
{
  "ttl_seconds": 10.0,
  "is_valid": true,
  "has_cached_result": true,
  "age_seconds": 3.5
}
```

### GET /health/protection

Security protection (rate limiter) status.

**Response:**
```json
{
  "status": "healthy",
  "message": "Rate limiter operational",
  "active_limits": 5,
  "failed_checks": 0
}
```

### DELETE /health/history

Clear health check history (admin operation).

**Response:**
```json
{
  "cleared": 100,
  "message": "Health check history cleared"
}
```

---

## Kubernetes Integration

### Deployment Configuration

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: example-service
spec:
  template:
    spec:
      containers:
      - name: app
        image: example-service:latest
        ports:
        - containerPort: 8000

        # Startup probe - check app initialized
        startupProbe:
          httpGet:
            path: /api/v1/health/startup
            port: 8000
          failureThreshold: 30
          periodSeconds: 10

        # Liveness probe - restart if unhealthy
        livenessProbe:
          httpGet:
            path: /api/v1/health/live
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3

        # Readiness probe - remove from service if not ready
        readinessProbe:
          httpGet:
            path: /api/v1/health/ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          successThreshold: 1
          failureThreshold: 3
```

### Probe Best Practices

**Startup Probe:**
- Use for slow-starting applications
- Higher failure threshold (30) to allow time for initialization
- Longer period (10s)

**Liveness Probe:**
- Simple check (app running?)
- Conservative failure threshold (3)
- Longer period (10s) to avoid false positives

**Readiness Probe:**
- Check critical dependencies (database)
- Shorter period (5s) for quick traffic routing
- Lower failure threshold (3) for fast response

---

## Prometheus Metrics

### Available Metrics

#### health_check_total
Counter for total health checks performed.

**Labels:**
- `provider`: Provider name (database, cache, etc.)
- `status`: Result status (healthy, degraded, unhealthy)

**Example:**
```promql
# Rate of health checks
rate(health_check_total[5m])

# Health check failure rate
rate(health_check_total{status="unhealthy"}[5m])
```

#### health_check_duration_seconds
Histogram of health check execution time.

**Labels:**
- `provider`: Provider name

**Buckets:** 0.001s to 5.0s (11 buckets)

**Example:**
```promql
# 95th percentile latency
histogram_quantile(0.95,
  rate(health_check_duration_seconds_bucket[5m])
)

# Average check duration by provider
avg(rate(health_check_duration_seconds_sum[5m]))
  by (provider)
```

#### health_check_status
Gauge of current health status.

**Labels:**
- `provider`: Provider name

**Values:**
- 1.0 = HEALTHY
- 0.5 = DEGRADED
- 0.0 = UNHEALTHY

**Example:**
```promql
# Alert on unhealthy status
health_check_status < 0.5

# Count degraded services
count(health_check_status == 0.5)
```

#### health_check_status_transitions_total
Counter of status transitions (critical for flapping detection).

**Labels:**
- `provider`: Provider name
- `from_status`: Previous status
- `to_status`: New status

**Example:**
```promql
# Flapping detection (rapid transitions)
rate(health_check_status_transitions_total[5m]) > 0.1

# Count healthy→unhealthy transitions
sum(health_check_status_transitions_total{
  from_status="healthy",
  to_status="unhealthy"
})
```

#### health_check_errors_total
Counter of health check execution errors.

**Labels:**
- `provider`: Provider name
- `error_type`: Error classification

**Example:**
```promql
# Error rate by provider
rate(health_check_errors_total[5m])

# Alert on high error rate
rate(health_check_errors_total[5m]) > 0.01
```

### Grafana Dashboard Example

```json
{
  "title": "Service Health",
  "panels": [
    {
      "title": "Overall Health Status",
      "targets": [{
        "expr": "health_check_status"
      }]
    },
    {
      "title": "Health Check Latency (p95)",
      "targets": [{
        "expr": "histogram_quantile(0.95, rate(health_check_duration_seconds_bucket[5m]))"
      }]
    },
    {
      "title": "Status Transitions",
      "targets": [{
        "expr": "rate(health_check_status_transitions_total[5m])"
      }]
    }
  ]
}
```

### Alerting Rules

```yaml
groups:
- name: health_checks
  rules:
  # Alert on unhealthy status
  - alert: ServiceUnhealthy
    expr: health_check_status{provider="database"} == 0
    for: 2m
    annotations:
      summary: "{{ $labels.provider }} is unhealthy"

  # Alert on degraded status
  - alert: ServiceDegraded
    expr: health_check_status == 0.5
    for: 10m
    annotations:
      summary: "{{ $labels.provider }} is degraded"

  # Alert on flapping (rapid status changes)
  - alert: HealthCheckFlapping
    expr: rate(health_check_status_transitions_total[5m]) > 0.1
    annotations:
      summary: "{{ $labels.provider }} status is flapping"

  # Alert on connection pool exhaustion risk
  - alert: DatabasePoolHighUtilization
    expr: health_check_status{provider="database_pool"} == 0.5
    for: 5m
    annotations:
      summary: "Database pool utilization > 70%"
```

---

## Custom Providers

### Creating a Custom Provider

**Step 1: Implement the HealthProvider Protocol**

```python
# example_service/features/myfeature/health_provider.py
from example_service.features.health.providers import (
    HealthProvider,
    HealthCheckResult,
    ProviderConfig,
)
from example_service.core.schemas.common import HealthStatus

class MyCustomHealthProvider:
    """Health provider for custom service.

    Example:
        provider = MyCustomHealthProvider(
            api_client=my_client,
            config=config
        )
    """

    def __init__(
        self,
        api_client: MyAPIClient,
        config: ProviderConfig | None = None,
    ):
        self._client = api_client
        self._config = config or ProviderConfig()

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "my_service"

    async def check_health(self) -> HealthCheckResult:
        """Perform health check."""
        start = time.perf_counter()

        try:
            # Your health check logic
            response = await self._client.ping()
            latency_ms = (time.perf_counter() - start) * 1000

            # Determine status
            if latency_ms > self._config.degraded_threshold_ms:
                status = HealthStatus.DEGRADED
                message = f"Service slow ({latency_ms:.0f}ms)"
            else:
                status = HealthStatus.HEALTHY
                message = "Service operational"

            return HealthCheckResult(
                status=status,
                message=message,
                latency_ms=latency_ms,
                metadata={"endpoint": str(self._client.base_url)}
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)}
            )
```

**Step 2: Register the Provider**

```python
# example_service/app/lifespan.py or your initialization code
from example_service.features.health.aggregator import get_health_aggregator
from example_service.features.myfeature.health_provider import MyCustomHealthProvider

# Get global aggregator
aggregator = get_health_aggregator()

# Register provider
aggregator.add_provider(
    MyCustomHealthProvider(
        api_client=my_client,
        config=health_settings.my_service,
    )
)
```

**Step 3: Add Configuration**

```python
# example_service/core/settings/health.py
class HealthCheckSettings(BaseSettings):
    # ... existing configs ...

    my_service: ProviderConfig = ProviderConfig(
        enabled=True,
        timeout=3.0,
        degraded_threshold_ms=500.0,
        critical_for_readiness=False,
    )
```

**Step 4: Add Tests**

```python
# tests/unit/test_features/test_myfeature/test_health_provider.py
import pytest
from unittest.mock import AsyncMock
from example_service.features.myfeature.health_provider import MyCustomHealthProvider

@pytest.mark.asyncio
async def test_my_custom_provider_healthy():
    """Test provider returns healthy status."""
    # Mock client
    mock_client = AsyncMock()
    mock_client.ping.return_value = {"status": "ok"}

    # Create provider
    provider = MyCustomHealthProvider(api_client=mock_client)

    # Check health
    result = await provider.check_health()

    # Assert
    assert result.status == HealthStatus.HEALTHY
    assert "operational" in result.message.lower()
    assert result.latency_ms > 0
```

---

## Best Practices

### 1. Configuration

✅ **DO:**
- Use per-provider configuration for production
- Set appropriate timeouts (2-5s typical)
- Mark critical dependencies for readiness
- Enable caching (10s TTL default)

❌ **DON'T:**
- Use same timeout for all providers
- Mark non-critical services as critical
- Disable caching in production
- Set very long timeouts (> 10s)

### 2. Custom Providers

✅ **DO:**
- Implement fast checks (< 100ms ideal)
- Handle errors gracefully (never crash)
- Return rich metadata for debugging
- Use timeouts on external calls

❌ **DON'T:**
- Perform expensive operations
- Block on slow external services
- Raise exceptions from check_health()
- Use blocking I/O

### 3. Kubernetes Probes

✅ **DO:**
- Use startup probe for slow applications
- Set conservative liveness thresholds
- Use readiness for traffic routing
- Test probes in staging

❌ **DON'T:**
- Use aggressive liveness probes
- Skip startup probe on slow apps
- Use readiness for liveness
- Ignore probe failures in logs

### 4. Monitoring

✅ **DO:**
- Monitor health check metrics
- Alert on status transitions (flapping)
- Track latency percentiles (p95, p99)
- Use Grafana dashboards

❌ **DON'T:**
- Only check current status
- Ignore degraded status
- Alert on every transition
- Forget about historical trends

### 5. Troubleshooting

✅ **DO:**
- Check `/health/detailed` for diagnostics
- Review `/health/history` for trends
- Check provider metadata for context
- Use `force_refresh=true` to bypass cache

❌ **DON'T:**
- Only look at overall status
- Ignore latency metrics
- Skip historical analysis
- Forget to check logs

---

## Troubleshooting

### Problem: All health checks return unhealthy

**Possible Causes:**
1. Configuration issue (wrong timeouts)
2. Dependencies actually down
3. Network connectivity problem

**Debug Steps:**
```bash
# Check detailed status
curl http://localhost:8000/api/v1/health/detailed

# Check individual provider
curl http://localhost:8000/api/v1/health/detailed?force_refresh=true

# Check logs
docker logs example-service | grep health

# Check configuration
echo $HEALTH_DATABASE__TIMEOUT
```

### Problem: Readiness probe failing

**Possible Causes:**
1. Critical dependency (database) unavailable
2. Too aggressive timeout
3. Provider returning degraded (not unhealthy)

**Debug Steps:**
```bash
# Check which checks are failing
curl http://localhost:8000/api/v1/health/ready

# Check critical providers config
curl http://localhost:8000/api/v1/health/providers

# Verify database connectivity
psql -h database-host -U user -d dbname -c "SELECT 1"
```

### Problem: High latency on health checks

**Possible Causes:**
1. Cache disabled or expired
2. Slow dependency (database query taking long)
3. Too many providers

**Debug Steps:**
```bash
# Check cache status
curl http://localhost:8000/api/v1/health/cache

# Check individual provider latency
curl http://localhost:8000/api/v1/health/detailed

# Check historical latency
curl http://localhost:8000/api/v1/health/stats
```

### Problem: Connection pool health showing degraded

**Possible Causes:**
1. High traffic (legitimate)
2. Connection leaks (not closing connections)
3. Pool size too small

**Debug Steps:**
```bash
# Check pool status
curl http://localhost:8000/api/v1/health/detailed | jq '.checks.database_pool'

# Review pool configuration
echo $DB_POOL_SIZE
echo $DB_MAX_OVERFLOW

# Check for connection leaks in logs
docker logs example-service | grep "pool"
```

**Solutions:**
- Increase pool size: `DB_POOL_SIZE=30`
- Add overflow: `DB_MAX_OVERFLOW=10`
- Fix connection leaks (ensure sessions closed)

### Problem: Consul health check failing

**Possible Causes:**
1. Consul agent not running
2. Network connectivity issue
3. Wrong Consul address

**Debug Steps:**
```bash
# Check Consul health directly
curl http://consul:8500/v1/agent/self

# Check provider config
echo $HEALTH_CONSUL__TIMEOUT
echo $CONSUL_URL

# Check detailed error
curl http://localhost:8000/api/v1/health/detailed | jq '.checks.consul'
```

---

## Summary

The health check system provides:

✅ **Production-Ready** - Used in enterprise microservices
✅ **Highly Configurable** - Per-provider settings
✅ **Rich Observability** - Prometheus metrics, history, diagnostics
✅ **Kubernetes Native** - Liveness, readiness, startup probes
✅ **Extensible** - Easy to add custom providers
✅ **Fast** - Concurrent execution with caching
✅ **Reliable** - Graceful degradation, never blocks

**Next Steps:**
1. Configure providers for your environment
2. Set up Kubernetes probes
3. Create Grafana dashboards
4. Add custom providers as needed
5. Monitor health metrics in production

**See Also:**
- [Kubernetes Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)
- [Health Check Pattern](https://microservices.io/patterns/observability/health-check-api.html)
