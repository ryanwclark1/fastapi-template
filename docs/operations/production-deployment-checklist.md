# Production Deployment Checklist

Comprehensive pre-flight checklist for deploying the FastAPI template to production environments. This document covers configuration validation, infrastructure verification, monitoring setup, and post-deployment verification.

---

## Table of Contents

- [Pre-Deployment Checklist](#pre-deployment-checklist)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Environment-Specific Configuration](#environment-specific-configuration)
- [Post-Deployment Verification](#post-deployment-verification)
- [Monitoring Dashboard Checklist](#monitoring-dashboard-checklist)
- [Rollback Plan](#rollback-plan)
- [Troubleshooting Guide](#troubleshooting-guide)
- [Configuration Templates](#configuration-templates)
- [Success Criteria](#success-criteria)
- [Contacts & Resources](#contacts--resources)

---

## Pre-Deployment Checklist

### 1. Configuration

#### Environment Variables
- [ ] All required environment variables configured
- [ ] Secrets loaded from secure vault (not in source control)
- [ ] Environment set to `production` (`APP_ENVIRONMENT=production`)
- [ ] Debug mode disabled (`APP_DEBUG=false`)
- [ ] Debug middleware disabled (`APP_ENABLE_DEBUG_MIDDLEWARE=false`)
- [ ] N+1 query detection disabled (`APP_ENABLE_N_PLUS_ONE_DETECTION=false`)
- [ ] API documentation disabled or protected (`APP_DISABLE_DOCS=true`)

#### Database Configuration
- [ ] Database DSN verified and tested
- [ ] Connection pool size appropriate (`DB_POOL_SIZE=20` recommended)
- [ ] Max overflow configured (`DB_MAX_OVERFLOW=10`)
- [ ] Pool timeout set (`DB_POOL_TIMEOUT=30.0`)
- [ ] Connection recycling enabled (`DB_POOL_RECYCLE=1800`)
- [ ] Connect timeout configured (`DB_CONNECT_TIMEOUT=5.0`)
- [ ] Database startup checks enabled (`DB_STARTUP_REQUIRE_DB=true`)
- [ ] Database migrations applied and verified

#### Cache Configuration (Redis)
- [ ] Redis URL verified and accessible
- [ ] Key prefix configured (`REDIS_KEY_PREFIX=your-service:`)
- [ ] Default TTL set appropriately (`REDIS_DEFAULT_TTL=3600`)
- [ ] Max connections configured (`REDIS_MAX_CONNECTIONS=50`)
- [ ] Connection timeouts set (`REDIS_SOCKET_TIMEOUT=5.0`)
- [ ] Retry logic configured (`REDIS_MAX_RETRIES=3`)
- [ ] Cache invalidation tags implemented for critical data

#### Health Check Configuration
- [ ] Global health check cache enabled (`HEALTH_CACHE_TTL_SECONDS=10.0`)
- [ ] Database health check configured (`HEALTH_DATABASE__ENABLED=true`)
- [ ] Database timeout appropriate (`HEALTH_DATABASE__TIMEOUT=2.0`)
- [ ] Database marked as critical (`HEALTH_DATABASE__CRITICAL_FOR_READINESS=true`)
- [ ] Cache health check configured (`HEALTH_CACHE__ENABLED=true`)
- [ ] Per-provider timeouts set appropriately
- [ ] Degraded thresholds configured for latency monitoring
- [ ] Database pool monitoring enabled (built-in `database_pool` provider)
- [ ] Critical dependencies identified and configured

#### Messaging Configuration (RabbitMQ)
- [ ] RabbitMQ URI verified (`RABBIT_AMQP_URI`)
- [ ] Connection name set (`RABBIT_CONNECTION_NAME=your-service-prod`)
- [ ] Queue prefix configured (`RABBIT_QUEUE_PREFIX=your-service`)
- [ ] Prefetch count set (`RABBIT_PREFETCH_COUNT=100`)
- [ ] Publisher confirms enabled (`RABBIT_PUBLISHER_CONFIRMS=true`)
- [ ] Health checks configured (`HEALTH_RABBITMQ__ENABLED=true`)

#### Service Discovery (Consul - Optional)
- [ ] Consul host and port configured
- [ ] Service name registered
- [ ] Health check interval set (`CONSUL_HEALTH_CHECK_INTERVAL=10s`)
- [ ] Health check timeout configured (`CONSUL_HEALTH_CHECK_TIMEOUT=5s`)
- [ ] Deregistration timeout set (`CONSUL_HEALTH_CHECK_DEREGISTER_CRITICAL_AFTER=30m`)
- [ ] Consul health provider enabled (`HEALTH_CONSUL__ENABLED=true`)

#### Security Configuration
- [ ] HSTS enabled (`SECURITY_ENABLE_HSTS=true`)
- [ ] HSTS max age set (`SECURITY_HSTS_MAX_AGE=31536000`)
- [ ] HSTS include subdomains (`SECURITY_HSTS_INCLUDE_SUBDOMAINS=true`)
- [ ] CSP configured (`SECURITY_ENABLE_CSP=true`)
- [ ] CSP directives set appropriately
- [ ] Frame options enabled (`SECURITY_ENABLE_FRAME_OPTIONS=true`)
- [ ] XSS protection enabled (`SECURITY_ENABLE_XSS_PROTECTION=true`)
- [ ] Content type options enabled (`SECURITY_ENABLE_CONTENT_TYPE_OPTIONS=true`)
- [ ] Referrer policy configured (`SECURITY_REFERRER_POLICY=strict-origin-when-cross-origin`)
- [ ] Server header removed or customized (`SECURITY_SERVER_HEADER=false`)

#### Authentication (Accent-Auth)
- [ ] Auth service URL configured (`AUTH_SERVICE_URL`)
- [ ] Token validation endpoint set
- [ ] Token cache TTL configured (`AUTH_TOKEN_CACHE_TTL=300`)
- [ ] Permission caching enabled (`AUTH_ENABLE_PERMISSION_CACHING=true`)
- [ ] Request timeout set (`AUTH_REQUEST_TIMEOUT=5.0`)
- [ ] Max retries configured (`AUTH_MAX_RETRIES=3`)
- [ ] Health checks configured (`HEALTH_ACCENT_AUTH__ENABLED=true`)

#### Rate Limiting
- [ ] Rate limiting enabled (`APP_ENABLE_RATE_LIMITING=true`)
- [ ] Rate limit per minute set (`APP_RATE_LIMIT_PER_MINUTE=120`)
- [ ] Rate limit window configured (`APP_RATE_LIMIT_WINDOW_SECONDS=60`)

#### CORS Configuration
- [ ] CORS origins restricted to allowed domains
- [ ] CORS allow credentials reviewed (`APP_CORS_ALLOW_CREDENTIALS=true`)
- [ ] CORS methods restricted as needed
- [ ] CORS headers restricted as needed

#### Circuit Breaker Configuration
- [ ] Circuit breaker enabled (`CIRCUIT_BREAKER_ENABLED=true`)
- [ ] Failure threshold set (`CIRCUIT_BREAKER_FAILURE_THRESHOLD=5`)
- [ ] Recovery timeout configured (`CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60`)
- [ ] Success threshold set (`CIRCUIT_BREAKER_SUCCESS_THRESHOLD=2`)
- [ ] Metrics enabled (`CIRCUIT_BREAKER_ENABLE_METRICS=true`)
- [ ] Notifications enabled (`CIRCUIT_BREAKER_ENABLE_NOTIFICATIONS=true`)

---

### 2. Infrastructure

#### Database (PostgreSQL)
- [ ] PostgreSQL 15+ provisioned
- [ ] Database created with correct encoding (UTF8)
- [ ] Database user created with appropriate permissions
- [ ] Connection pooling configured (PgBouncer recommended for high load)
- [ ] Backups configured and tested
- [ ] Replication configured for high availability
- [ ] Monitoring enabled (query performance, connection pool)
- [ ] Indexes created for frequently queried columns
- [ ] `deleted_by` column added to audit tables (enhanced audit mixins)

#### Cache (Redis)
- [ ] Redis 7+ provisioned
- [ ] Redis persistence configured (RDB + AOF recommended)
- [ ] Redis maxmemory policy set (`allkeys-lru` or `volatile-lru`)
- [ ] Redis monitoring enabled
- [ ] Redis Sentinel/Cluster for high availability (production)
- [ ] Redis backups configured

#### Message Broker (RabbitMQ - Optional)
- [ ] RabbitMQ 3.12+ provisioned
- [ ] Management plugin enabled
- [ ] Queues and exchanges created
- [ ] Dead letter queues configured
- [ ] Message persistence enabled
- [ ] Clustering configured for high availability
- [ ] Monitoring enabled

#### Service Discovery (Consul - Optional)
- [ ] Consul 1.16+ provisioned
- [ ] Consul agent running in client mode
- [ ] Consul datacenter configured
- [ ] Service registration tested
- [ ] Health checks working
- [ ] DNS integration configured (optional)

#### Storage (S3/MinIO - Optional)
- [ ] S3 bucket created or MinIO provisioned
- [ ] Bucket versioning enabled
- [ ] Lifecycle policies configured
- [ ] Access credentials secured
- [ ] CORS configured if needed
- [ ] Health checks configured (`HEALTH_S3__ENABLED=true`)

#### Load Balancer
- [ ] Load balancer provisioned (AWS ALB, nginx, etc.)
- [ ] SSL/TLS certificates installed
- [ ] Health check endpoint configured (`/api/v1/health/ready`)
- [ ] Connection draining enabled (30s recommended)
- [ ] Timeouts configured appropriately
- [ ] Rate limiting at LB level (optional)

#### SSL/TLS Certificates
- [ ] Valid SSL certificates installed
- [ ] Certificate expiry monitoring configured
- [ ] Auto-renewal configured (Let's Encrypt, cert-manager)
- [ ] Certificate chain complete
- [ ] Strong cipher suites configured

---

### 3. Monitoring & Observability

#### Prometheus
- [ ] Prometheus server configured
- [ ] Scrape endpoint accessible (`/metrics`)
- [ ] Scrape interval set (15s recommended)
- [ ] Service discovery configured
- [ ] Retention period configured (15 days recommended)
- [ ] Storage provisioned

#### Grafana Dashboards
- [ ] Grafana connected to Prometheus
- [ ] Health check dashboard created (see metrics section)
- [ ] Application metrics dashboard created
- [ ] Database metrics dashboard created
- [ ] Infrastructure metrics dashboard created
- [ ] Alerting configured in Grafana

#### Health Check Endpoints
- [ ] `/api/v1/health/` endpoint accessible
- [ ] `/api/v1/health/detailed` endpoint accessible
- [ ] `/api/v1/health/live` endpoint accessible (liveness probe)
- [ ] `/api/v1/health/ready` endpoint accessible (readiness probe)
- [ ] `/api/v1/health/startup` endpoint accessible (startup probe)
- [ ] `/metrics` endpoint accessible for Prometheus

#### Metrics Collection
- [ ] Health check metrics flowing (`health_check_total`, `health_check_duration_seconds`)
- [ ] Status metrics reporting (`health_check_status`)
- [ ] Transition metrics tracking (`health_check_status_transitions_total`)
- [ ] Error metrics reporting (`health_check_errors_total`)
- [ ] Database pool metrics available (`database_pool` provider)
- [ ] Application metrics configured

#### Alerting Rules
- [ ] Service unhealthy alert configured
- [ ] Service degraded alert configured
- [ ] Health check flapping alert configured
- [ ] Connection pool high utilization alert configured
- [ ] High error rate alert configured
- [ ] High latency alert configured
- [ ] Alert routing configured (PagerDuty, Slack, email)

#### Log Aggregation
- [ ] Logging service configured (ELK, Loki, CloudWatch)
- [ ] Log level set to INFO or WARNING (`LOG_LEVEL=INFO`)
- [ ] JSON logs enabled (`LOG_JSON_LOGS=true`)
- [ ] Log retention configured
- [ ] Log queries and dashboards created
- [ ] Log alerts configured

#### OpenTelemetry (Optional)
- [ ] OpenTelemetry enabled (`OTEL_ENABLED=true`)
- [ ] OTEL endpoint configured (`OTEL_ENDPOINT`)
- [ ] Service name set (`OTEL_SERVICE_NAME`)
- [ ] Sample rate configured (`OTEL_SAMPLE_RATE=0.1` for prod)
- [ ] Instrumentation enabled (FastAPI, HTTPX, SQLAlchemy)
- [ ] Traces flowing to backend (Tempo, Jaeger)

---

### 4. Security

#### Secrets Management
- [ ] All secrets in secure vault (AWS Secrets Manager, Vault, etc.)
- [ ] No secrets in source control (verified with git-secrets or similar)
- [ ] No secrets in environment variables (use secrets injection)
- [ ] Database credentials rotated regularly
- [ ] API keys secured
- [ ] Service-to-service tokens secured

#### API Security
- [ ] Authentication required on protected endpoints
- [ ] Authorization checks implemented
- [ ] Rate limiting enabled and tested
- [ ] Request size limits configured (`APP_REQUEST_SIZE_LIMIT=10485760`)
- [ ] SQL injection protection verified (ORM usage)
- [ ] XSS protection enabled (security headers)
- [ ] CSRF protection enabled (if applicable)

#### Network Security
- [ ] Services in private subnet
- [ ] Security groups/firewall rules configured
- [ ] Only necessary ports exposed
- [ ] Intrusion detection configured
- [ ] DDoS protection enabled

#### Compliance
- [ ] Data encryption at rest enabled
- [ ] Data encryption in transit enabled (TLS 1.3)
- [ ] Audit logging enabled (enhanced audit mixins with `deleted_by`)
- [ ] GDPR compliance verified (if applicable)
- [ ] PCI DSS compliance verified (if applicable)
- [ ] Compliance scans passed

---

### 5. Performance

#### Connection Pooling
- [ ] Database pool size optimized (`DB_POOL_SIZE=20-50`)
- [ ] Database max overflow configured (`DB_MAX_OVERFLOW=10`)
- [ ] Pool timeout appropriate (`DB_POOL_TIMEOUT=30.0`)
- [ ] Pool recycling enabled (`DB_POOL_RECYCLE=1800`)
- [ ] Redis connection pool configured (`REDIS_MAX_CONNECTIONS=50`)

#### Caching Strategy
- [ ] Redis cache TTL configured per use case
- [ ] Cache invalidation patterns implemented (tags, patterns)
- [ ] Cache warming strategy for critical data
- [ ] Cache hit rate monitoring configured
- [ ] Health check caching enabled (`HEALTH_CACHE_TTL_SECONDS=10.0`)

#### Database Optimization
- [ ] Indexes created on frequently queried columns
- [ ] Query performance analyzed and optimized
- [ ] N+1 queries identified and fixed (use detection in dev)
- [ ] Database query timeout configured
- [ ] Connection pooler tested (PgBouncer if needed)

#### Load Testing
- [ ] Load testing completed with realistic traffic patterns
- [ ] Performance benchmarks established
- [ ] Latency percentiles measured (p50, p95, p99)
- [ ] Throughput targets verified
- [ ] Resource utilization under load verified
- [ ] Connection pool behavior under load tested

---

### 6. Testing

#### Unit Tests
- [ ] All unit tests passing (`pytest tests/unit/`)
- [ ] Code coverage > 80%
- [ ] Critical paths covered
- [ ] Edge cases tested

#### Integration Tests
- [ ] All integration tests passing (`pytest tests/integration/`)
- [ ] Database interactions tested
- [ ] Cache interactions tested
- [ ] External service mocks tested
- [ ] Health check providers tested

#### End-to-End Tests
- [ ] E2E tests passing in staging
- [ ] Critical user flows tested
- [ ] Authentication flows tested
- [ ] Error handling tested

#### Health Check Testing
- [ ] Health checks pass in staging
- [ ] Database health check verified
- [ ] Cache health check verified
- [ ] Database pool health check verified
- [ ] External service health checks verified
- [ ] Readiness probe tested
- [ ] Liveness probe tested
- [ ] Failover scenarios tested

#### Staging Deployment
- [ ] Application deployed to staging
- [ ] Staging environment mirrors production
- [ ] Full test suite executed in staging
- [ ] Performance testing completed
- [ ] Security scanning completed

---

## Kubernetes Deployment

### Configuration Checklist

```yaml
# Deployment requirements checklist
```

- [ ] **Resource Limits**: CPU and memory limits set
- [ ] **Resource Requests**: CPU and memory requests set
- [ ] **Liveness Probe**: Configured with appropriate thresholds
- [ ] **Readiness Probe**: Configured to check critical dependencies
- [ ] **Startup Probe**: Configured for slow initialization (if needed)
- [ ] **HPA (Horizontal Pod Autoscaler)**: Configured for auto-scaling
- [ ] **PDB (Pod Disruption Budget)**: Configured for high availability
- [ ] **Service Account**: Created with minimal permissions
- [ ] **ConfigMaps**: Created for non-sensitive configuration
- [ ] **Secrets**: Created for sensitive data (from vault)
- [ ] **Affinity Rules**: Configured for pod distribution
- [ ] **Tolerations**: Configured for node taints (if applicable)
- [ ] **Init Containers**: Configured for pre-startup tasks (if needed)

### Health Probes Configuration

#### Startup Probe (for slow initialization)
```yaml
startupProbe:
  httpGet:
    path: /api/v1/health/startup
    port: 8000
  initialDelaySeconds: 0
  periodSeconds: 5
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 30  # 30 * 5s = 150s max startup time
```

**When to use:**
- Application has slow startup (database migrations, cache warming)
- Prevents premature liveness probe failures
- Recommended failure threshold: 20-30 (depending on startup time)

#### Liveness Probe (for deadlock detection)
```yaml
livenessProbe:
  httpGet:
    path: /api/v1/health/live
    port: 8000
  initialDelaySeconds: 0  # Use startup probe instead
  periodSeconds: 10
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 3  # Restart after 30s of failures
```

**Best practices:**
- Conservative failure threshold (3-5)
- Longer period (10-15s) to avoid false positives
- Simple check (app running, not deadlocked)
- Does not check dependencies

#### Readiness Probe (for traffic routing)
```yaml
readinessProbe:
  httpGet:
    path: /api/v1/health/ready
    port: 8000
  initialDelaySeconds: 0  # Use startup probe instead
  periodSeconds: 5
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 3  # Remove from service after 15s
```

**Best practices:**
- Shorter period (5s) for quick traffic routing
- Checks critical dependencies (database)
- Lower failure threshold (3) for fast response
- Used by load balancer for routing decisions

### Resource Recommendations

#### Development
```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "256Mi"
    cpu: "250m"
```

#### Staging
```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "250m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

#### Production (Minimum)
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

#### Production (Recommended)
```yaml
resources:
  requests:
    memory: "1Gi"
    cpu: "1000m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

### Horizontal Pod Autoscaler (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: example-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: example-service
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
```

**Configuration:**
- [ ] Min replicas set (3 recommended for HA)
- [ ] Max replicas set (10-20 typical)
- [ ] CPU target utilization (70% recommended)
- [ ] Memory target utilization (80% recommended)
- [ ] Scale down stabilization configured (5min recommended)
- [ ] Scale up stabilization configured (1min recommended)

### Pod Disruption Budget (PDB)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: example-service-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: example-service
```

**Configuration:**
- [ ] Min available pods set (2 for HA)
- [ ] Or max unavailable set (1)
- [ ] Ensures availability during rolling updates

---

## Environment-Specific Configuration

### Development

```bash
# Application
APP_ENVIRONMENT=development
APP_DEBUG=true
APP_DISABLE_DOCS=false
APP_ENABLE_DEBUG_MIDDLEWARE=true
APP_ENABLE_N_PLUS_ONE_DETECTION=true

# Database
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_ECHO=true

# Health Checks
HEALTH_CACHE_TTL_SECONDS=5.0
HEALTH_DATABASE__TIMEOUT=5.0
HEALTH_CONSUL__ENABLED=false

# Logging
LOG_LEVEL=DEBUG
LOG_JSON_LOGS=false

# Security (relaxed for dev)
SECURITY_ENABLE_HSTS=false
SECURITY_CSP_DEFAULT_SRC="'self' 'unsafe-inline' 'unsafe-eval'"

# OpenTelemetry
OTEL_ENABLED=false
```

### Staging

```bash
# Application
APP_ENVIRONMENT=staging
APP_DEBUG=false
APP_DISABLE_DOCS=false
APP_ENABLE_DEBUG_MIDDLEWARE=false
APP_ENABLE_N_PLUS_ONE_DETECTION=false

# Database
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10
DB_ECHO=false

# Health Checks
HEALTH_CACHE_TTL_SECONDS=10.0
HEALTH_DATABASE__TIMEOUT=2.0
HEALTH_DATABASE__CRITICAL_FOR_READINESS=true
HEALTH_CONSUL__ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_JSON_LOGS=true

# Security
SECURITY_ENABLE_HSTS=true
SECURITY_HSTS_MAX_AGE=31536000
SECURITY_ENABLE_CSP=true

# OpenTelemetry
OTEL_ENABLED=true
OTEL_SAMPLE_RATE=1.0
```

### Production

```bash
# Application
APP_ENVIRONMENT=production
APP_DEBUG=false
APP_DISABLE_DOCS=true
APP_ENABLE_DEBUG_MIDDLEWARE=false
APP_ENABLE_N_PLUS_ONE_DETECTION=false

# Database
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_ECHO=false
DB_POOL_TIMEOUT=30.0
DB_POOL_RECYCLE=1800

# Cache
REDIS_MAX_CONNECTIONS=50
REDIS_DEFAULT_TTL=3600

# Health Checks
HEALTH_CACHE_TTL_SECONDS=10.0
HEALTH_GLOBAL_TIMEOUT=30.0
HEALTH_DATABASE__ENABLED=true
HEALTH_DATABASE__TIMEOUT=2.0
HEALTH_DATABASE__DEGRADED_THRESHOLD_MS=500.0
HEALTH_DATABASE__CRITICAL_FOR_READINESS=true
HEALTH_CACHE__ENABLED=true
HEALTH_CACHE__TIMEOUT=1.0
HEALTH_CACHE__CRITICAL_FOR_READINESS=false
HEALTH_RABBITMQ__ENABLED=true
HEALTH_RABBITMQ__TIMEOUT=5.0
HEALTH_CONSUL__ENABLED=true
HEALTH_CONSUL__TIMEOUT=3.0

# Logging
LOG_LEVEL=INFO
LOG_JSON_LOGS=true
LOG_SLOW_REQUEST_THRESHOLD=1.0

# Security
SECURITY_ENABLE_HSTS=true
SECURITY_HSTS_MAX_AGE=31536000
SECURITY_HSTS_INCLUDE_SUBDOMAINS=true
SECURITY_ENABLE_CSP=true
SECURITY_CSP_DEFAULT_SRC="'self'"
SECURITY_ENABLE_FRAME_OPTIONS=true
SECURITY_FRAME_OPTIONS=DENY
SECURITY_SERVER_HEADER=false

# Rate Limiting
APP_ENABLE_RATE_LIMITING=true
APP_RATE_LIMIT_PER_MINUTE=120

# Circuit Breaker
CIRCUIT_BREAKER_ENABLED=true
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60
CIRCUIT_BREAKER_ENABLE_METRICS=true

# OpenTelemetry
OTEL_ENABLED=true
OTEL_SAMPLE_RATE=0.1  # 10% sampling in prod
OTEL_INSTRUMENT_FASTAPI=true
OTEL_INSTRUMENT_SQLALCHEMY=true
```

---

## Post-Deployment Verification

### Immediate Checks (First 5 minutes)

- [ ] **Application Started**: Pods running and not restarting
  ```bash
  kubectl get pods -l app=example-service
  kubectl logs -l app=example-service --tail=50
  ```

- [ ] **Health Checks Passing**: All health endpoints returning 200
  ```bash
  # Via kubectl port-forward
  kubectl port-forward svc/example-service 8000:80
  curl http://localhost:8000/api/v1/health/
  curl http://localhost:8000/api/v1/health/ready
  curl http://localhost:8000/api/v1/health/live
  ```

- [ ] **Metrics Being Collected**: Prometheus scraping successfully
  ```bash
  curl http://localhost:8000/metrics | grep health_check
  ```

- [ ] **No Error Logs**: Application logs clean
  ```bash
  kubectl logs -l app=example-service | grep -i error
  ```

- [ ] **Database Connectivity**: Database health check passing
  ```bash
  curl http://localhost:8000/api/v1/health/detailed | jq '.checks.database'
  ```

- [ ] **Cache Connectivity**: Redis health check passing
  ```bash
  curl http://localhost:8000/api/v1/health/detailed | jq '.checks.cache'
  ```

- [ ] **Readiness Probe**: Pods marked ready
  ```bash
  kubectl get pods -l app=example-service -o wide
  # Check READY column shows X/X
  ```

### Short Term Checks (First hour)

- [ ] **Traffic Routing Correctly**: Load balancer directing to healthy pods
  ```bash
  # Test via load balancer URL
  curl https://api.example.com/api/v1/health/
  ```

- [ ] **Response Times Acceptable**: p95 latency < SLA
  ```promql
  histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
  ```

- [ ] **No Memory Leaks**: Memory usage stable
  ```bash
  kubectl top pods -l app=example-service
  ```

- [ ] **No Connection Pool Exhaustion**: Pool utilization normal
  ```bash
  curl http://localhost:8000/api/v1/health/detailed | jq '.checks.database_pool'
  ```

- [ ] **Health Check Metrics Normal**: No flapping or errors
  ```promql
  # Check status transitions
  rate(health_check_status_transitions_total[5m])

  # Check error rate
  rate(health_check_errors_total[5m])
  ```

- [ ] **Error Rates Within Threshold**: < 1% error rate
  ```promql
  sum(rate(http_requests_total{status=~"5.."}[5m])) /
  sum(rate(http_requests_total[5m]))
  ```

- [ ] **Resource Utilization**: CPU and memory within limits
  ```bash
  kubectl top pods -l app=example-service
  ```

### Medium Term Checks (First day)

- [ ] **Performance Metrics Stable**: No degradation over time
  ```promql
  # Compare current vs 1 hour ago
  rate(http_request_duration_seconds_sum[5m])
  ```

- [ ] **Resource Utilization Normal**: No unexpected growth
  - Monitor CPU usage trend
  - Monitor memory usage trend
  - Monitor connection pool utilization

- [ ] **No Unexpected Alerts**: All alerts green
  - Check Prometheus alerts
  - Check Grafana dashboards
  - Review PagerDuty/Slack notifications

- [ ] **Logs Clean**: No error patterns emerging
  ```bash
  # Check error count
  kubectl logs -l app=example-service --since=1h | grep -i error | wc -l
  ```

- [ ] **User Feedback Positive**: No customer complaints
  - Check support tickets
  - Check user feedback channels

- [ ] **Database Performance**: Query performance normal
  - Check slow query logs
  - Monitor database connection pool
  - Review query execution times

- [ ] **Cache Performance**: Cache hit rate acceptable
  ```promql
  rate(cache_hits_total[5m]) /
  (rate(cache_hits_total[5m]) + rate(cache_misses_total[5m]))
  ```

---

## Monitoring Dashboard Checklist

### Key Metrics to Monitor

#### 1. Health Check Status

**Overall Health Gauge**
```promql
# Current health status (1.0=healthy, 0.5=degraded, 0.0=unhealthy)
health_check_status
```

**Per-Provider Status**
```promql
# Filter by provider
health_check_status{provider="database"}
health_check_status{provider="cache"}
health_check_status{provider="database_pool"}
```

**Status Transitions (Flapping Detection)**
```promql
# Rate of status changes (high rate indicates flapping)
rate(health_check_status_transitions_total[5m])
```

#### 2. Performance Metrics

**Request Latency**
```promql
# p50 latency
histogram_quantile(0.50, rate(http_request_duration_seconds_bucket[5m]))

# p95 latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# p99 latency
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
```

**Throughput**
```promql
# Requests per second
sum(rate(http_requests_total[5m]))
```

**Error Rate**
```promql
# Percentage of 5xx errors
sum(rate(http_requests_total{status=~"5.."}[5m])) /
sum(rate(http_requests_total[5m])) * 100
```

**Health Check Duration**
```promql
# Average health check duration by provider
avg(rate(health_check_duration_seconds_sum[5m]))
  by (provider)

# p95 health check duration
histogram_quantile(0.95,
  rate(health_check_duration_seconds_bucket[5m])
)
```

#### 3. Resource Utilization

**CPU Usage**
```promql
# Per pod
rate(container_cpu_usage_seconds_total{pod=~"example-service.*"}[5m])

# Total across all pods
sum(rate(container_cpu_usage_seconds_total{pod=~"example-service.*"}[5m]))
```

**Memory Usage**
```promql
# Per pod
container_memory_working_set_bytes{pod=~"example-service.*"}

# Total across all pods
sum(container_memory_working_set_bytes{pod=~"example-service.*"})
```

**Connection Pool Utilization**
```promql
# Database pool utilization from health check metadata
# Note: This requires custom metric export from database_pool provider
# Example custom metric:
database_connection_pool_utilization_percent
```

**Cache Hit Rate**
```promql
# Redis cache hit rate
rate(cache_hits_total[5m]) /
(rate(cache_hits_total[5m]) + rate(cache_misses_total[5m])) * 100
```

#### 4. Dependency Health

**Database Connectivity**
```promql
# Database health status
health_check_status{provider="database"}

# Database response time
avg(rate(health_check_duration_seconds_sum{provider="database"}[5m]))
```

**Cache Connectivity**
```promql
# Cache health status
health_check_status{provider="cache"}
```

**Message Broker Status**
```promql
# RabbitMQ health status
health_check_status{provider="rabbitmq"}
```

**Service Discovery Status**
```promql
# Consul health status
health_check_status{provider="consul"}
```

### Alert Rules

Create `/etc/prometheus/rules/health_checks.yml`:

```yaml
groups:
- name: health_checks
  interval: 30s
  rules:

  # Critical: Service unhealthy
  - alert: ServiceUnhealthy
    expr: health_check_status == 0
    for: 2m
    labels:
      severity: critical
      team: platform
    annotations:
      summary: "Service {{ $labels.provider }} is unhealthy"
      description: "Health check for {{ $labels.provider }} has been unhealthy for 2 minutes. Status value: {{ $value }}"
      runbook: "https://wiki.example.com/runbooks/service-unhealthy"

  # Warning: Service degraded
  - alert: ServiceDegraded
    expr: health_check_status == 0.5
    for: 10m
    labels:
      severity: warning
      team: platform
    annotations:
      summary: "Service {{ $labels.provider }} is degraded"
      description: "Health check for {{ $labels.provider }} has been degraded for 10 minutes. This indicates high latency or partial failures."
      runbook: "https://wiki.example.com/runbooks/service-degraded"

  # Critical: Health check flapping
  - alert: HealthCheckFlapping
    expr: rate(health_check_status_transitions_total[5m]) > 0.1
    for: 5m
    labels:
      severity: warning
      team: platform
    annotations:
      summary: "Health check {{ $labels.provider }} is flapping"
      description: "Service {{ $labels.provider }} status is changing rapidly (> 0.1 transitions/sec). This indicates instability."
      runbook: "https://wiki.example.com/runbooks/health-flapping"

  # Warning: Connection pool high utilization
  - alert: DatabasePoolHighUtilization
    expr: health_check_status{provider="database_pool"} == 0.5
    for: 5m
    labels:
      severity: warning
      team: platform
    annotations:
      summary: "Database connection pool utilization is high"
      description: "Database pool utilization > 70% for 5 minutes. Consider increasing pool size or investigating connection leaks."
      runbook: "https://wiki.example.com/runbooks/pool-exhaustion"

  # Critical: Connection pool near exhaustion
  - alert: DatabasePoolNearExhaustion
    expr: health_check_status{provider="database_pool"} == 0
    for: 2m
    labels:
      severity: critical
      team: platform
    annotations:
      summary: "Database connection pool near exhaustion"
      description: "Database pool utilization > 90% for 2 minutes. Service may fail to acquire connections."
      runbook: "https://wiki.example.com/runbooks/pool-exhaustion"

  # Critical: High error rate
  - alert: HighErrorRate
    expr: |
      sum(rate(http_requests_total{status=~"5.."}[5m])) /
      sum(rate(http_requests_total[5m])) * 100 > 5
    for: 5m
    labels:
      severity: critical
      team: platform
    annotations:
      summary: "High error rate detected"
      description: "Error rate is {{ $value | humanizePercentage }} (threshold: 5%). Service is experiencing failures."
      runbook: "https://wiki.example.com/runbooks/high-error-rate"

  # Warning: Elevated error rate
  - alert: ElevatedErrorRate
    expr: |
      sum(rate(http_requests_total{status=~"5.."}[5m])) /
      sum(rate(http_requests_total[5m])) * 100 > 1
    for: 10m
    labels:
      severity: warning
      team: platform
    annotations:
      summary: "Elevated error rate detected"
      description: "Error rate is {{ $value | humanizePercentage }} (threshold: 1%). Monitor closely."

  # Warning: High latency
  - alert: HighLatency
    expr: |
      histogram_quantile(0.95,
        rate(http_request_duration_seconds_bucket[5m])
      ) > 2.0
    for: 10m
    labels:
      severity: warning
      team: platform
    annotations:
      summary: "High request latency detected"
      description: "p95 latency is {{ $value }}s (threshold: 2s). Service performance degraded."
      runbook: "https://wiki.example.com/runbooks/high-latency"

  # Critical: Very high latency
  - alert: VeryHighLatency
    expr: |
      histogram_quantile(0.95,
        rate(http_request_duration_seconds_bucket[5m])
      ) > 5.0
    for: 5m
    labels:
      severity: critical
      team: platform
    annotations:
      summary: "Very high request latency detected"
      description: "p95 latency is {{ $value }}s (threshold: 5s). Service severely degraded."
      runbook: "https://wiki.example.com/runbooks/high-latency"

  # Warning: Health check errors
  - alert: HealthCheckErrors
    expr: rate(health_check_errors_total[5m]) > 0.01
    for: 5m
    labels:
      severity: warning
      team: platform
    annotations:
      summary: "Health check errors for {{ $labels.provider }}"
      description: "Health check for {{ $labels.provider }} is experiencing errors. Error rate: {{ $value | humanize }}/sec"

  # Critical: No healthy instances
  - alert: NoHealthyInstances
    expr: |
      sum(up{job="example-service"}) == 0
    for: 1m
    labels:
      severity: critical
      team: platform
    annotations:
      summary: "No healthy service instances"
      description: "All instances of example-service are down. Service is completely unavailable."
      runbook: "https://wiki.example.com/runbooks/service-down"
```

### Grafana Dashboard JSON

Create a comprehensive Grafana dashboard (example panels):

**Panel 1: Overall Health Status**
- Visualization: Stat panel with thresholds
- Query: `health_check_status`
- Thresholds: Red (<0.5), Yellow (0.5), Green (1.0)

**Panel 2: Health Check Latency (p95)**
- Visualization: Time series
- Query: `histogram_quantile(0.95, rate(health_check_duration_seconds_bucket[5m]))`

**Panel 3: Status Transitions (Flapping)**
- Visualization: Time series
- Query: `rate(health_check_status_transitions_total[5m])`

**Panel 4: Request Latency Percentiles**
- Visualization: Time series
- Queries:
  - p50: `histogram_quantile(0.50, rate(http_request_duration_seconds_bucket[5m]))`
  - p95: `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`
  - p99: `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))`

**Panel 5: Error Rate**
- Visualization: Time series
- Query: `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100`

**Panel 6: Database Pool Utilization**
- Visualization: Gauge
- Query: Extract from `health_check_detailed` metadata (requires custom exporter)

---

## Rollback Plan

### Rollback Triggers

Initiate rollback if any of these conditions occur:

- [ ] **Health checks failing**: Readiness probe failing for > 2 minutes
- [ ] **High error rate**: > 5% of requests returning 5xx errors
- [ ] **Performance degradation**: p95 latency > 50% slower than baseline
- [ ] **Connection pool exhaustion**: Database pool utilization > 90%
- [ ] **Critical dependency failure**: Database or critical service unavailable
- [ ] **Memory leak detected**: Memory usage increasing linearly
- [ ] **Pod crash loop**: Pods restarting repeatedly (> 3 times in 5 minutes)
- [ ] **Data corruption detected**: Audit logs show data integrity issues

### Rollback Steps

#### Kubernetes Rollback

```bash
# 1. Stop new traffic immediately
kubectl scale deployment example-service --replicas=0

# 2. Check rollout history
kubectl rollout history deployment/example-service

# 3. Rollback to previous version
kubectl rollout undo deployment/example-service

# Or rollback to specific revision
kubectl rollout undo deployment/example-service --to-revision=2

# 4. Verify rollback
kubectl rollout status deployment/example-service

# 5. Check health
kubectl get pods -l app=example-service
kubectl logs -l app=example-service --tail=50

# 6. Test health endpoints
kubectl port-forward svc/example-service 8000:80
curl http://localhost:8000/api/v1/health/ready

# 7. Resume traffic gradually
kubectl scale deployment example-service --replicas=3

# 8. Monitor closely
watch kubectl get pods -l app=example-service
```

#### Manual Rollback Steps

1. **Stop Traffic Routing**
   ```bash
   # Mark deployment as unhealthy in load balancer
   kubectl annotate deployment example-service health-check-disabled=true

   # Or scale down to 0
   kubectl scale deployment example-service --replicas=0
   ```

2. **Revert to Previous Version**
   ```bash
   # Rollback deployment
   kubectl rollout undo deployment/example-service

   # Wait for rollout to complete
   kubectl rollout status deployment/example-service
   ```

3. **Verify Health**
   ```bash
   # Check pod status
   kubectl get pods -l app=example-service

   # Check logs for errors
   kubectl logs -l app=example-service --tail=100 | grep -i error

   # Test health endpoints
   curl http://localhost:8000/api/v1/health/detailed
   ```

4. **Resume Traffic**
   ```bash
   # Scale back to desired replicas
   kubectl scale deployment example-service --replicas=3

   # Remove health check disable annotation
   kubectl annotate deployment example-service health-check-disabled-
   ```

5. **Monitor Recovery**
   - Watch health check metrics in Grafana
   - Monitor error rates
   - Check response times
   - Verify connection pool utilization

6. **Post-Rollback Actions**
   - Document the incident
   - Investigate root cause
   - Create postmortem
   - Fix issues before re-deploying

### Communication During Rollback

- [ ] Notify team in Slack/Teams
- [ ] Update status page if customer-facing
- [ ] Alert on-call engineer
- [ ] Document actions taken
- [ ] Communicate ETA for resolution

---

## Troubleshooting Guide

### Common Issues and Resolutions

#### Issue 1: Health checks failing

**Symptoms:**
- `/api/v1/health/ready` returning 503
- Pods marked as not ready
- Traffic not routing to pods

**Possible Causes:**
1. Database connection failure
2. Health check timeout too aggressive
3. Dependency unavailable (Redis, RabbitMQ)
4. Network connectivity issues

**Debug Steps:**
```bash
# 1. Check detailed health status
kubectl port-forward svc/example-service 8000:80
curl http://localhost:8000/api/v1/health/detailed | jq '.'

# 2. Check which provider is failing
curl http://localhost:8000/api/v1/health/detailed | jq '.checks'

# 3. Check pod logs
kubectl logs -l app=example-service --tail=100 | grep health

# 4. Check configuration
kubectl exec -it <pod-name> -- env | grep HEALTH_

# 5. Test database connectivity directly
kubectl exec -it <pod-name> -- psql $DB_DSN -c "SELECT 1"

# 6. Check Redis connectivity
kubectl exec -it <pod-name> -- redis-cli -u $REDIS_URL ping
```

**Resolution:**
- If database issue: Check database status, connection pool settings
- If timeout issue: Increase `HEALTH_DATABASE__TIMEOUT`
- If dependency issue: Check dependency health, update configuration
- If network issue: Check security groups, network policies

---

#### Issue 2: Connection pool exhaustion

**Symptoms:**
- `database_pool` health check degraded or unhealthy
- Errors: "QueuePool limit exceeded"
- Slow response times
- Timeout errors

**Possible Causes:**
1. High traffic (legitimate)
2. Connection leaks (not closing connections)
3. Pool size too small
4. Long-running queries holding connections
5. Deadlocks in transactions

**Debug Steps:**
```bash
# 1. Check pool utilization
curl http://localhost:8000/api/v1/health/detailed | jq '.checks.database_pool'

# 2. Check pool configuration
kubectl exec -it <pod-name> -- env | grep DB_POOL

# 3. Check application logs for connection errors
kubectl logs -l app=example-service | grep -i "pool\|connection"

# 4. Check database active connections
# Connect to database and run:
SELECT count(*) FROM pg_stat_activity WHERE application_name = 'example-service';

# 5. Check for long-running queries
SELECT pid, now() - query_start as duration, query
FROM pg_stat_activity
WHERE state = 'active'
  AND application_name = 'example-service'
ORDER BY duration DESC;
```

**Resolution:**
```bash
# Option 1: Increase pool size
kubectl set env deployment/example-service DB_POOL_SIZE=30
kubectl set env deployment/example-service DB_MAX_OVERFLOW=10

# Option 2: Reduce pool recycle time (if connections going stale)
kubectl set env deployment/example-service DB_POOL_RECYCLE=900

# Option 3: Kill long-running queries (emergency)
# SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE ...;

# Option 4: Restart pods to reset connections (last resort)
kubectl rollout restart deployment/example-service
```

**Prevention:**
- Always close database sessions in finally blocks
- Use context managers for database sessions
- Set appropriate statement timeout
- Monitor connection pool metrics continuously
- Enable N+1 query detection in development

---

#### Issue 3: High latency

**Symptoms:**
- p95 latency > SLA (e.g., > 2s)
- Slow response times reported by users
- Health checks showing degraded status
- Timeouts in logs

**Possible Causes:**
1. Database queries slow (missing indexes, N+1 queries)
2. External service calls slow
3. Connection pool contention
4. Cache misses (Redis unavailable)
5. CPU throttling
6. Memory pressure

**Debug Steps:**
```bash
# 1. Check latency metrics
curl http://localhost:8000/metrics | grep http_request_duration

# 2. Check health check latency
curl http://localhost:8000/api/v1/health/detailed | jq '.checks[] | {name: .name, latency: .latency_ms}'

# 3. Check slow query logs
kubectl logs -l app=example-service | grep "slow query\|took"

# 4. Check resource utilization
kubectl top pods -l app=example-service

# 5. Check database query performance
# Run on database:
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
WHERE mean_exec_time > 1000  -- queries > 1s
ORDER BY mean_exec_time DESC
LIMIT 20;

# 6. Check cache hit rate
curl http://localhost:8000/metrics | grep cache_hits

# 7. Enable OpenTelemetry tracing for detailed analysis
kubectl set env deployment/example-service OTEL_ENABLED=true
```

**Resolution:**
- Add database indexes for slow queries
- Optimize N+1 queries (use eager loading)
- Increase connection pool size if contended
- Scale horizontally (increase replica count)
- Increase resource limits (CPU, memory)
- Enable caching for expensive operations
- Add circuit breakers for slow external services

---

#### Issue 4: Service flapping (status changes rapidly)

**Symptoms:**
- `health_check_status_transitions_total` metric high
- Pods marked ready/not ready repeatedly
- Inconsistent health check results
- Alert: "Health check flapping"

**Possible Causes:**
1. Health check threshold too sensitive
2. Network instability
3. Dependency intermittent failures
4. Resource contention (CPU throttling)
5. GC pauses (memory pressure)

**Debug Steps:**
```bash
# 1. Check transition rate
curl http://localhost:8000/metrics | grep health_check_status_transitions_total

# 2. Check health check history
curl http://localhost:8000/api/v1/health/history?limit=50 | jq '.history'

# 3. Check for network issues
kubectl logs -l app=example-service | grep -i "timeout\|connection refused"

# 4. Check resource throttling
kubectl describe pod <pod-name> | grep -A 10 "State:"

# 5. Check dependency health
curl http://localhost:8000/api/v1/health/detailed | jq '.checks'
```

**Resolution:**
```bash
# Option 1: Increase health check cache TTL
kubectl set env deployment/example-service HEALTH_CACHE_TTL_SECONDS=30.0

# Option 2: Increase degraded threshold
kubectl set env deployment/example-service HEALTH_DATABASE__DEGRADED_THRESHOLD_MS=1000.0

# Option 3: Increase resource limits
kubectl set resources deployment example-service --limits=cpu=2,memory=2Gi

# Option 4: Increase readiness probe failure threshold
kubectl patch deployment example-service --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/failureThreshold", "value": 5}]'
```

---

#### Issue 5: Memory leak

**Symptoms:**
- Memory usage increasing linearly over time
- Eventually OOMKilled (pod restarted)
- Performance degrading over time
- Frequent pod restarts

**Possible Causes:**
1. Connection leaks (database, Redis, HTTP connections)
2. Cache growing unbounded
3. Event listeners not removed
4. Large objects not garbage collected
5. Memory profiling revealed leak

**Debug Steps:**
```bash
# 1. Monitor memory trend
kubectl top pods -l app=example-service --containers

# 2. Check for OOMKilled events
kubectl get events --sort-by='.lastTimestamp' | grep OOMKilled

# 3. Check pod restarts
kubectl get pods -l app=example-service -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}'

# 4. Enable memory profiling (if available)
curl http://localhost:8000/debug/pprof/heap > heap.prof

# 5. Check application metrics
curl http://localhost:8000/metrics | grep memory
```

**Resolution:**
```bash
# Emergency: Restart pods
kubectl rollout restart deployment/example-service

# Increase memory limits (temporary)
kubectl set resources deployment example-service --limits=memory=4Gi

# Long-term: Fix code
# - Review database session management
# - Check Redis connection pooling
# - Review cache size limits
# - Add memory limits to in-memory caches
# - Enable memory profiling in staging
```

---

#### Issue 6: Consul health check failing

**Symptoms:**
- `consul` health check unhealthy
- Service not registered in Consul
- Service discovery not working
- Health check shows "agent connection failed"

**Possible Causes:**
1. Consul agent not running
2. Network connectivity issues
3. Wrong Consul address configured
4. Consul ACL token missing/invalid
5. Service registration failed

**Debug Steps:**
```bash
# 1. Check Consul health directly
curl http://consul:8500/v1/agent/self

# 2. Check detailed Consul health
curl http://localhost:8000/api/v1/health/detailed | jq '.checks.consul'

# 3. Check Consul configuration
kubectl exec -it <pod-name> -- env | grep CONSUL_

# 4. Check Consul logs
kubectl logs -l app=consul

# 5. Check service registration
curl http://consul:8500/v1/agent/services | jq '.'
```

**Resolution:**
```bash
# Option 1: Verify Consul is running
kubectl get pods -l app=consul

# Option 2: Check network policies allow connectivity
kubectl describe networkpolicy

# Option 3: Update Consul configuration
kubectl set env deployment/example-service CONSUL_HOST=consul.default.svc.cluster.local
kubectl set env deployment/example-service CONSUL_PORT=8500

# Option 4: Disable Consul health check if not critical
kubectl set env deployment/example-service HEALTH_CONSUL__CRITICAL_FOR_READINESS=false

# Option 5: Restart Consul agent
kubectl rollout restart deployment/consul
```

---

## Configuration Templates

### .env.production

Complete production configuration template:

```bash
# ==============================================================================
# Production Environment Configuration
# ==============================================================================

# ------------------------------------------------------------------------------
# Application Settings
# ------------------------------------------------------------------------------
APP_SERVICE_NAME=example-service
APP_TITLE=Example Service API
APP_DESCRIPTION=Production FastAPI service
APP_VERSION=1.0.0
APP_ENVIRONMENT=production
APP_DEBUG=false
APP_HOST=0.0.0.0
APP_PORT=8000
APP_API_PREFIX=/api/v1

# Documentation (disabled in production)
APP_DOCS_URL=
APP_REDOC_URL=
APP_OPENAPI_URL=
APP_DISABLE_DOCS=true

# CORS (restrict to actual domains)
APP_CORS_ORIGINS=["https://app.example.com", "https://dashboard.example.com"]
APP_CORS_ALLOW_CREDENTIALS=true
APP_CORS_ALLOW_METHODS=["GET", "POST", "PUT", "PATCH", "DELETE"]
APP_CORS_ALLOW_HEADERS=["*"]

# Request limits
APP_ENABLE_REQUEST_SIZE_LIMIT=true
APP_REQUEST_SIZE_LIMIT=10485760  # 10MB

# Rate limiting
APP_ENABLE_RATE_LIMITING=true
APP_RATE_LIMIT_PER_MINUTE=120
APP_RATE_LIMIT_WINDOW_SECONDS=60

# Debug features (disabled in production)
APP_ENABLE_DEBUG_MIDDLEWARE=false
APP_DEBUG_LOG_REQUESTS=false
APP_DEBUG_LOG_RESPONSES=false
APP_ENABLE_N_PLUS_ONE_DETECTION=false

# ------------------------------------------------------------------------------
# Security Headers
# ------------------------------------------------------------------------------
SECURITY_ENABLE_HSTS=true
SECURITY_HSTS_MAX_AGE=31536000  # 1 year
SECURITY_HSTS_INCLUDE_SUBDOMAINS=true
SECURITY_HSTS_PRELOAD=false

SECURITY_ENABLE_CSP=true
SECURITY_CSP_DEFAULT_SRC="'self'"
SECURITY_CSP_SCRIPT_SRC="'self'"
SECURITY_CSP_STYLE_SRC="'self' 'unsafe-inline'"

SECURITY_ENABLE_FRAME_OPTIONS=true
SECURITY_FRAME_OPTIONS=DENY

SECURITY_ENABLE_XSS_PROTECTION=true
SECURITY_ENABLE_CONTENT_TYPE_OPTIONS=true

SECURITY_ENABLE_REFERRER_POLICY=true
SECURITY_REFERRER_POLICY=strict-origin-when-cross-origin

SECURITY_ENABLE_PERMISSIONS_POLICY=true
SECURITY_SERVER_HEADER=false  # Remove server header

SECURITY_ENVIRONMENT=production

# ------------------------------------------------------------------------------
# Database Settings
# ------------------------------------------------------------------------------
DB_ENABLED=true
# Use secret injection for DSN in production
DB_DSN=${DATABASE_URL}  # Injected from secret manager

DB_APPLICATION_NAME=example-service-prod
DB_ECHO=false

# Connection pooling (production sizing)
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30.0
DB_POOL_RECYCLE=1800  # 30 minutes
DB_CONNECT_TIMEOUT=5.0

# PostgreSQL specific
DB_PG_MIN_SIZE=5
DB_PG_MAX_SIZE=20
DB_PG_TIMEOUT=30.0

# Startup behavior
DB_STARTUP_REQUIRE_DB=true
DB_STARTUP_RETRY_ATTEMPTS=3
DB_STARTUP_RETRY_DELAY=2.0
DB_STARTUP_RETRY_TIMEOUT=60.0

# ------------------------------------------------------------------------------
# Redis Cache Settings
# ------------------------------------------------------------------------------
# Use secret injection for URL in production
REDIS_REDIS_URL=${REDIS_URL}  # Injected from secret manager

REDIS_KEY_PREFIX=example-service:prod:
REDIS_DEFAULT_TTL=3600
REDIS_AUTH_TOKEN_TTL=300

# Connection pooling
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_TIMEOUT=5.0
REDIS_SOCKET_CONNECT_TIMEOUT=5.0
REDIS_SOCKET_KEEPALIVE=true

# Retry logic
REDIS_MAX_RETRIES=3
REDIS_RETRY_DELAY=0.5
REDIS_RETRY_TIMEOUT=10.0

REDIS_HEALTH_CHECKS_ENABLED=true
REDIS_STARTUP_REQUIRE_CACHE=false

# ------------------------------------------------------------------------------
# RabbitMQ Messaging Settings
# ------------------------------------------------------------------------------
RABBIT_ENABLED=true
# Use secret injection for URI in production
RABBIT_AMQP_URI=${RABBITMQ_URI}  # Injected from secret manager

RABBIT_CONNECTION_NAME=example-service-prod
RABBIT_QUEUE_PREFIX=example-service-prod
RABBIT_DEFAULT_QUEUE=tasks
RABBIT_EXCHANGE_NAME=example-service-prod
RABBIT_EXCHANGE_TYPE=topic

RABBIT_PREFETCH_COUNT=100
RABBIT_MAX_CONSUMERS=10
RABBIT_POOL_SIZE=10
RABBIT_PUBLISHER_CONFIRMS=true
RABBIT_HEARTBEAT=60
RABBIT_RETRY_ATTEMPTS=5
RABBIT_RETRY_BACKOFF=1.0
RABBIT_GRACEFUL_TIMEOUT=15.0

# ------------------------------------------------------------------------------
# Circuit Breaker Configuration
# ------------------------------------------------------------------------------
CIRCUIT_BREAKER_ENABLED=true
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60
CIRCUIT_BREAKER_SUCCESS_THRESHOLD=2
CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS=1
CIRCUIT_BREAKER_BACKOFF_MULTIPLIER=1.5
CIRCUIT_BREAKER_MAX_RECOVERY_TIMEOUT=300
CIRCUIT_BREAKER_ENABLE_METRICS=true
CIRCUIT_BREAKER_ENABLE_NOTIFICATIONS=true

# ------------------------------------------------------------------------------
# Accent-Auth Authentication
# ------------------------------------------------------------------------------
# Use secret injection for service URL in production
AUTH_SERVICE_URL=${AUTH_SERVICE_URL}  # Injected from config

AUTH_HEALTH_CHECKS_ENABLED=true
AUTH_TOKEN_VALIDATION_ENDPOINT=/api/auth/0.1/token

# Token caching
AUTH_TOKEN_CACHE_TTL=300
AUTH_ENABLE_PERMISSION_CACHING=true
AUTH_ENABLE_ACL_CACHING=true

AUTH_TOKEN_HEADER=X-Auth-Token
AUTH_TOKEN_SCHEME=Bearer

AUTH_REQUEST_TIMEOUT=5.0
AUTH_MAX_RETRIES=3

# ------------------------------------------------------------------------------
# Health Check Configuration
# ------------------------------------------------------------------------------
# Global settings
HEALTH_CACHE_TTL_SECONDS=10.0
HEALTH_HISTORY_SIZE=100
HEALTH_GLOBAL_TIMEOUT=30.0

# Database health check (CRITICAL for readiness)
HEALTH_DATABASE__ENABLED=true
HEALTH_DATABASE__TIMEOUT=2.0
HEALTH_DATABASE__DEGRADED_THRESHOLD_MS=500.0
HEALTH_DATABASE__CRITICAL_FOR_READINESS=true

# Cache health check (non-critical)
HEALTH_CACHE__ENABLED=true
HEALTH_CACHE__TIMEOUT=1.0
HEALTH_CACHE__DEGRADED_THRESHOLD_MS=200.0
HEALTH_CACHE__CRITICAL_FOR_READINESS=false

# RabbitMQ health check (non-critical)
HEALTH_RABBITMQ__ENABLED=true
HEALTH_RABBITMQ__TIMEOUT=5.0
HEALTH_RABBITMQ__DEGRADED_THRESHOLD_MS=1000.0
HEALTH_RABBITMQ__CRITICAL_FOR_READINESS=false

# Accent-Auth health check (non-critical)
HEALTH_ACCENT_AUTH__ENABLED=true
HEALTH_ACCENT_AUTH__TIMEOUT=5.0
HEALTH_ACCENT_AUTH__DEGRADED_THRESHOLD_MS=1000.0
HEALTH_ACCENT_AUTH__CRITICAL_FOR_READINESS=false

# Consul health check (non-critical)
HEALTH_CONSUL__ENABLED=true
HEALTH_CONSUL__TIMEOUT=3.0
HEALTH_CONSUL__DEGRADED_THRESHOLD_MS=500.0
HEALTH_CONSUL__CRITICAL_FOR_READINESS=false

# S3 health check (non-critical)
HEALTH_S3__ENABLED=false
HEALTH_S3__TIMEOUT=5.0
HEALTH_S3__DEGRADED_THRESHOLD_MS=2000.0
HEALTH_S3__CRITICAL_FOR_READINESS=false

# ------------------------------------------------------------------------------
# Consul Service Discovery (Optional)
# ------------------------------------------------------------------------------
CONSUL_ENABLED=true
CONSUL_HOST=consul.service.consul
CONSUL_PORT=8500
CONSUL_SCHEME=http
# Use secret injection for token
CONSUL_TOKEN=${CONSUL_TOKEN}  # Injected from secret manager

CONSUL_SERVICE_NAME=example-service
CONSUL_SERVICE_TAGS=["fastapi", "api", "production"]

CONSUL_HEALTH_CHECK_ENABLED=true
CONSUL_HEALTH_CHECK_INTERVAL=10s
CONSUL_HEALTH_CHECK_TIMEOUT=5s
CONSUL_HEALTH_CHECK_DEREGISTER_CRITICAL_AFTER=30m

CONSUL_CONNECT_ENABLED=false

# ------------------------------------------------------------------------------
# Logging Settings
# ------------------------------------------------------------------------------
LOG_SERVICE_NAME=example-service
LOG_LEVEL=INFO
LOG_JSON_LOGS=true
LOG_CONSOLE_ENABLED=true
LOG_FILE_ENABLED=false  # Use centralized logging in production

LOG_INCLUDE_UVICORN=true
LOG_INCLUDE_REQUEST_ID=true
LOG_LOG_SLOW_REQUESTS=true
LOG_SLOW_REQUEST_THRESHOLD=1.0
LOG_CAPTURE_WARNINGS=true

# ------------------------------------------------------------------------------
# OpenTelemetry Settings
# ------------------------------------------------------------------------------
OTEL_ENABLED=true
OTEL_ENDPOINT=${OTEL_COLLECTOR_ENDPOINT}  # Injected from config
OTEL_SERVICE_NAME=example-service
OTEL_SERVICE_VERSION=1.0.0
OTEL_INSECURE=false
OTEL_SAMPLE_RATE=0.1  # 10% sampling in production

OTEL_INSTRUMENT_FASTAPI=true
OTEL_INSTRUMENT_HTTPX=true
OTEL_INSTRUMENT_SQLALCHEMY=true
OTEL_INSTRUMENT_PSYCOPG=true

# ------------------------------------------------------------------------------
# GraphQL Configuration (Optional)
# ------------------------------------------------------------------------------
GRAPHQL_ENABLED=true
GRAPHQL_PATH=/graphql
GRAPHQL_GRAPHQL_IDE=false  # Disabled in production
GRAPHQL_DISABLE_PLAYGROUND=true

GRAPHQL_MAX_QUERY_DEPTH=10
GRAPHQL_MAX_COMPLEXITY=1000
GRAPHQL_DEFAULT_PAGE_SIZE=50
GRAPHQL_MAX_PAGE_SIZE=100

GRAPHQL_SUBSCRIPTIONS_ENABLED=true
GRAPHQL_SUBSCRIPTION_KEEPALIVE_INTERVAL=30.0
GRAPHQL_INTROSPECTION_ENABLED=false  # Disabled in production

# ------------------------------------------------------------------------------
# WebSocket Configuration (Optional)
# ------------------------------------------------------------------------------
WS_MAX_CONNECTIONS=10000
WS_MAX_CONNECTIONS_PER_USER=10
WS_MAX_MESSAGE_SIZE=65536

WS_HEARTBEAT_INTERVAL=30.0
WS_CONNECTION_TIMEOUT=60.0
WS_CLOSE_TIMEOUT=5.0

WS_CHANNEL_PREFIX=ws:prod:
WS_DEFAULT_CHANNELS=["global"]
WS_MAX_CHANNELS_PER_CONNECTION=50

WS_REQUIRE_AUTH=true
WS_AUTH_TIMEOUT=10.0
WS_AUTH_TOKEN_HEADER=Authorization

WS_RATE_LIMIT_ENABLED=true
WS_RATE_LIMIT_MESSAGES_PER_MINUTE=120
WS_RATE_LIMIT_BURST=20

WS_ENABLE_COMPRESSION=true
WS_COMPRESSION_THRESHOLD=1024

# ==============================================================================
# Notes:
# - Replace ${VARIABLE} placeholders with actual secret injection
# - Use AWS Secrets Manager, HashiCorp Vault, or Kubernetes Secrets
# - Never commit sensitive credentials to source control
# - Rotate credentials regularly
# - Use different credentials per environment
# ==============================================================================
```

---

### Kubernetes Manifests

#### deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: example-service
  namespace: production
  labels:
    app: example-service
    version: v1.0.0
    environment: production
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Zero downtime
  selector:
    matchLabels:
      app: example-service
  template:
    metadata:
      labels:
        app: example-service
        version: v1.0.0
        environment: production
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: example-service
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

      containers:
      - name: example-service
        image: example-service:1.0.0
        imagePullPolicy: IfNotPresent

        ports:
        - name: http
          containerPort: 8000
          protocol: TCP

        env:
        # Application settings
        - name: APP_SERVICE_NAME
          value: "example-service"
        - name: APP_ENVIRONMENT
          value: "production"
        - name: APP_DEBUG
          value: "false"
        - name: APP_DISABLE_DOCS
          value: "true"

        # Database (from secret)
        - name: DB_DSN
          valueFrom:
            secretKeyRef:
              name: example-service-secrets
              key: database-url
        - name: DB_POOL_SIZE
          value: "20"
        - name: DB_MAX_OVERFLOW
          value: "10"

        # Redis (from secret)
        - name: REDIS_REDIS_URL
          valueFrom:
            secretKeyRef:
              name: example-service-secrets
              key: redis-url
        - name: REDIS_MAX_CONNECTIONS
          value: "50"

        # Health checks
        - name: HEALTH_CACHE_TTL_SECONDS
          value: "10.0"
        - name: HEALTH_DATABASE__ENABLED
          value: "true"
        - name: HEALTH_DATABASE__TIMEOUT
          value: "2.0"
        - name: HEALTH_DATABASE__CRITICAL_FOR_READINESS
          value: "true"

        # Logging
        - name: LOG_LEVEL
          value: "INFO"
        - name: LOG_JSON_LOGS
          value: "true"

        # Security
        - name: SECURITY_ENABLE_HSTS
          value: "true"
        - name: SECURITY_ENABLE_CSP
          value: "true"

        resources:
          requests:
            memory: "1Gi"
            cpu: "1000m"
          limits:
            memory: "2Gi"
            cpu: "2000m"

        # Startup probe - for slow initialization
        startupProbe:
          httpGet:
            path: /api/v1/health/startup
            port: http
            httpHeaders:
            - name: X-Health-Check
              value: "startup"
          initialDelaySeconds: 0
          periodSeconds: 5
          timeoutSeconds: 3
          successThreshold: 1
          failureThreshold: 30  # 150s max startup time

        # Liveness probe - restart if deadlocked
        livenessProbe:
          httpGet:
            path: /api/v1/health/live
            port: http
            httpHeaders:
            - name: X-Health-Check
              value: "liveness"
          initialDelaySeconds: 0
          periodSeconds: 10
          timeoutSeconds: 3
          successThreshold: 1
          failureThreshold: 3  # Restart after 30s of failures

        # Readiness probe - remove from service if not ready
        readinessProbe:
          httpGet:
            path: /api/v1/health/ready
            port: http
            httpHeaders:
            - name: X-Health-Check
              value: "readiness"
          initialDelaySeconds: 0
          periodSeconds: 5
          timeoutSeconds: 3
          successThreshold: 1
          failureThreshold: 3  # Remove after 15s of failures

        # Graceful shutdown
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]

      terminationGracePeriodSeconds: 30

      # Pod anti-affinity for high availability
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - example-service
              topologyKey: kubernetes.io/hostname
```

#### service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: example-service
  namespace: production
  labels:
    app: example-service
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-backend-protocol: http
    service.beta.kubernetes.io/aws-load-balancer-connection-draining-enabled: "true"
    service.beta.kubernetes.io/aws-load-balancer-connection-draining-timeout: "30"
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: http
    protocol: TCP
    name: http
  selector:
    app: example-service
  sessionAffinity: None
```

#### configmap.yaml

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: example-service-config
  namespace: production
data:
  # Non-sensitive configuration
  app-environment: "production"
  log-level: "INFO"
  health-cache-ttl: "10.0"

  # External service URLs
  auth-service-url: "http://accent-auth.production.svc.cluster.local:9497"
  consul-host: "consul.production.svc.cluster.local"
  consul-port: "8500"
```

#### secret.yaml

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: example-service-secrets
  namespace: production
type: Opaque
stringData:
  # NOTE: In production, use external secret manager (AWS Secrets Manager, Vault, etc.)
  # These are examples only - DO NOT hardcode secrets
  database-url: "postgresql+psycopg://user:password@postgres.production.svc.cluster.local:5432/example_db"
  redis-url: "redis://:password@redis.production.svc.cluster.local:6379/0"
  rabbitmq-uri: "amqp://admin:password@rabbitmq.production.svc.cluster.local:5672/"
  consul-token: "your-consul-token"
```

#### hpa.yaml

See HPA configuration in Kubernetes section above.

#### pdb.yaml

See PDB configuration in Kubernetes section above.

---

## Success Criteria

### Deployment Successful When:

- [ ] **All health checks passing**
  - `/api/v1/health/` returns 200
  - `/api/v1/health/ready` returns 200
  - All providers showing healthy status

- [ ] **No error logs**
  - Application logs show no errors
  - No exceptions in logs
  - No warnings about critical issues

- [ ] **Metrics flowing to Prometheus**
  - `/metrics` endpoint accessible
  - Health check metrics visible in Prometheus
  - Application metrics being scraped

- [ ] **Response times within SLA**
  - p95 latency < 2 seconds (or your SLA)
  - p99 latency < 5 seconds (or your SLA)
  - Average response time < 500ms

- [ ] **Error rate < 0.1%**
  - 5xx errors < 0.1% of total requests
  - No 503 Service Unavailable errors
  - No timeout errors

- [ ] **No alerts firing**
  - All Prometheus alerts green
  - No critical alerts in PagerDuty
  - No warnings in monitoring dashboards

- [ ] **All pods healthy and ready**
  - All replicas running
  - All pods marked READY
  - No pod restarts

- [ ] **Load balancer routing correctly**
  - Traffic distributed across pods
  - Health check at LB level passing
  - No 502/504 errors from LB

- [ ] **Database connectivity verified**
  - Database health check passing
  - Connection pool utilization normal (< 70%)
  - No connection errors in logs

- [ ] **Cache connectivity verified**
  - Redis health check passing
  - Cache operations working
  - No connection errors

- [ ] **Team confident in deployment**
  - All stakeholders informed
  - Rollback plan ready
  - On-call engineer available

---

## Contacts & Resources

### On-Call Contacts

- **Engineering Lead**: [Name] - [Email] - [Phone]
- **DevOps Team**: [Slack Channel] - [PagerDuty]
- **Database Admin**: [Name] - [Email]
- **Security Team**: [Email] - [Slack Channel]

### Documentation Links

**Internal Documentation:**
- [Health Check Guide](/docs/features/health-checks.md)
- [Testing Guide](/docs/testing/testing-guide.md)
- [Architecture Documentation](/docs/architecture/final-architecture.md)
- [Best Practices](/docs/development/best-practices.md)
- [Runbooks](/docs/runbooks/) (create directory)

**External Resources:**
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

### Monitoring Dashboards

- **Grafana**: https://grafana.example.com/
- **Prometheus**: https://prometheus.example.com/
- **Kibana/Logs**: https://logs.example.com/
- **APM/Traces**: https://apm.example.com/

### Incident Management

- **PagerDuty**: https://example.pagerduty.com/
- **Status Page**: https://status.example.com/
- **Incident Slack Channel**: #incidents
- **Postmortem Template**: [Link to template]

---

## Appendix: Quick Reference Commands

### Health Check Commands

```bash
# Basic health check
curl http://localhost:8000/api/v1/health/

# Detailed health check
curl http://localhost:8000/api/v1/health/detailed | jq '.'

# Readiness probe
curl http://localhost:8000/api/v1/health/ready

# Liveness probe
curl http://localhost:8000/api/v1/health/live

# Force refresh (bypass cache)
curl http://localhost:8000/api/v1/health/detailed?force_refresh=true

# Health check history
curl http://localhost:8000/api/v1/health/history?limit=20

# Health check statistics
curl http://localhost:8000/api/v1/health/stats
```

### Kubernetes Commands

```bash
# Get pod status
kubectl get pods -l app=example-service

# View pod logs
kubectl logs -l app=example-service --tail=100

# Follow logs
kubectl logs -l app=example-service -f

# Describe pod
kubectl describe pod <pod-name>

# Check pod resource usage
kubectl top pods -l app=example-service

# Check deployment status
kubectl rollout status deployment/example-service

# Scale deployment
kubectl scale deployment example-service --replicas=5

# Restart deployment
kubectl rollout restart deployment/example-service

# Rollback deployment
kubectl rollout undo deployment/example-service

# Port forward for local testing
kubectl port-forward svc/example-service 8000:80
```

### Prometheus Queries

```promql
# Current health status
health_check_status

# Health check failure rate
rate(health_check_total{status="unhealthy"}[5m])

# p95 request latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Error rate
sum(rate(http_requests_total{status=~"5.."}[5m])) /
sum(rate(http_requests_total[5m])) * 100

# Flapping detection
rate(health_check_status_transitions_total[5m])
```

---

**Document Version**: 1.0.0
**Last Updated**: 2025-12-01
**Next Review**: 2026-01-01
