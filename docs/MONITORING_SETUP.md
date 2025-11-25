# Middleware Monitoring Setup Guide

This guide provides detailed instructions for setting up comprehensive monitoring for the enhanced middleware stack using Prometheus, Grafana, and OpenTelemetry.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Metrics Collection](#metrics-collection)
3. [Grafana Dashboards](#grafana-dashboards)
4. [Alerting Rules](#alerting-rules)
5. [Trace Correlation](#trace-correlation)
6. [Log Aggregation](#log-aggregation)
7. [Troubleshooting](#troubleshooting)

## Architecture Overview

```
┌─────────────────┐
│   FastAPI App   │
│   + Middleware  │
└────────┬────────┘
         │
         ├─────────────────────────────────┐
         │                                 │
         ▼                                 ▼
┌────────────────┐                ┌────────────────┐
│   Prometheus   │                │ OpenTelemetry  │
│   (Metrics)    │                │   (Traces)     │
└────────┬───────┘                └────────┬───────┘
         │                                 │
         │ Exemplars link to traces        │
         └──────────────┬──────────────────┘
                        │
                        ▼
                ┌───────────────┐
                │    Grafana    │
                │  (Dashboards  │
                │   + Alerts)   │
                └───────────────┘
```

### Key Components

- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and dashboards
- **OpenTelemetry**: Distributed tracing
- **Tempo**: Trace storage (optional)
- **Loki**: Log aggregation (optional)

## Metrics Collection

### Available Metrics

The middleware stack exposes the following Prometheus metrics:

#### HTTP Request Metrics

```python
# Request counts by method, endpoint, and status code
http_requests_total{method="GET", endpoint="/api/v1/status", status="200"}

# Request duration histogram (includes exemplars for trace correlation)
http_request_duration_seconds{method="GET", endpoint="/api/v1/status"}

# Active requests gauge
http_requests_in_progress{method="GET", endpoint="/api/v1/status"}
```

#### Middleware-Specific Metrics

```python
# Individual middleware execution time
middleware_execution_seconds{middleware_name="RequestIDMiddleware"}

# Request size distribution
request_size_bytes{endpoint="/api/v1/upload", method="POST"}

# Size limit rejections
request_size_limit_rejections_total{endpoint="/api/v1/upload", method="POST"}

# Rate limit rejections
rate_limit_rejections_total{endpoint="/api/v1/status", limit_key_type="ip"}

# Middleware errors
middleware_errors_total{middleware_name="RateLimitMiddleware", error_type="RedisConnectionError"}
```

### Metrics Endpoint

The `/metrics` endpoint is automatically configured and available at:

```
http://localhost:8000/metrics
```

Example output:

```prometheus
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",endpoint="/api/v1/status",status="200"} 1523.0 # {trace_id="a1b2c3d4e5f6..."} 1.0 1637250000.123

# HELP http_request_duration_seconds HTTP request latency
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",endpoint="/api/v1/status",le="0.005"} 1245.0
http_request_duration_seconds_bucket{method="GET",endpoint="/api/v1/status",le="0.01"} 1450.0
http_request_duration_seconds_sum{method="GET",endpoint="/api/v1/status"} 12.5
http_request_duration_seconds_count{method="GET",endpoint="/api/v1/status"} 1523.0
```

### Prometheus Configuration

Add the following to your `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  # Enable exemplar storage for trace correlation
  external_labels:
    cluster: 'production'

scrape_configs:
  - job_name: 'example-service'
    scrape_interval: 10s
    metrics_path: /metrics
    static_configs:
      - targets: ['example-service:8000']
        labels:
          service: 'example-service'
          environment: 'production'

# Enable exemplar storage
storage:
  exemplars:
    max_exemplars: 100000
```

### Scraping Validation

Verify Prometheus is scraping metrics:

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="example-service")'

# Query metrics
curl -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=http_requests_total{job="example-service"}' | jq
```

## Grafana Dashboards

### Dashboard 1: HTTP Request Overview

**Purpose**: High-level view of HTTP traffic, latency, and errors

**Panels**:

#### 1.1 Request Rate (QPS)

```promql
# Query
sum(rate(http_requests_total{job="example-service"}[5m]))

# Visualization: Graph
# Y-axis: Requests/sec
```

#### 1.2 Request Latency (p50, p95, p99)

```promql
# p50
histogram_quantile(0.50,
  sum(rate(http_request_duration_seconds_bucket{job="example-service"}[5m])) by (le)
)

# p95
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{job="example-service"}[5m])) by (le)
)

# p99
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{job="example-service"}[5m])) by (le)
)

# Visualization: Graph with multiple series
# Y-axis: Seconds
```

#### 1.3 Status Code Distribution

```promql
# Query
sum by (status) (rate(http_requests_total{job="example-service"}[5m]))

# Visualization: Pie chart or stacked area chart
```

#### 1.4 Error Rate

```promql
# Query
sum(rate(http_requests_total{job="example-service", status=~"5.."}[5m])) /
sum(rate(http_requests_total{job="example-service"}[5m])) * 100

# Visualization: Graph with threshold alert at 1%
# Y-axis: Percentage
```

#### 1.5 Requests in Progress

```promql
# Query
sum(http_requests_in_progress{job="example-service"})

# Visualization: Graph
# Y-axis: Active requests
```

### Dashboard 2: Middleware Performance

**Purpose**: Detailed middleware execution metrics

**Panels**:

#### 2.1 Middleware Execution Time by Component

```promql
# Query
histogram_quantile(0.95,
  sum(rate(middleware_execution_seconds_bucket{job="example-service"}[5m])) by (le, middleware_name)
)

# Visualization: Graph, grouped by middleware_name
# Y-axis: Seconds
```

#### 2.2 Request Size Distribution

```promql
# Query
histogram_quantile(0.95,
  sum(rate(request_size_bytes_bucket{job="example-service"}[5m])) by (le)
)

# Visualization: Heatmap
# X-axis: Time
# Y-axis: Request size (bytes)
```

#### 2.3 Size Limit Rejections

```promql
# Query
sum by (endpoint, method) (rate(request_size_limit_rejections_total{job="example-service"}[5m]))

# Visualization: Table
# Columns: Endpoint, Method, Rejections/sec
```

#### 2.4 Rate Limit Rejections (if enabled)

```promql
# Query
sum by (limit_key_type) (rate(rate_limit_rejections_total{job="example-service"}[5m]))

# Visualization: Graph
# Y-axis: Rejections/sec
```

#### 2.5 Middleware Errors

```promql
# Query
sum by (middleware_name, error_type) (rate(middleware_errors_total{job="example-service"}[5m]))

# Visualization: Table
# Columns: Middleware, Error Type, Rate
```

### Dashboard 3: Endpoint Breakdown

**Purpose**: Per-endpoint performance analysis

**Panels**:

#### 3.1 Top Endpoints by Request Count

```promql
# Query
topk(10,
  sum by (endpoint, method) (rate(http_requests_total{job="example-service"}[5m]))
)

# Visualization: Bar gauge
```

#### 3.2 Slowest Endpoints (p95 latency)

```promql
# Query
topk(10,
  histogram_quantile(0.95,
    sum(rate(http_request_duration_seconds_bucket{job="example-service"}[5m])) by (le, endpoint)
  )
)

# Visualization: Table
# Columns: Endpoint, p95 Latency
```

#### 3.3 Error Rate by Endpoint

```promql
# Query
sum by (endpoint) (rate(http_requests_total{job="example-service", status=~"5.."}[5m])) /
sum by (endpoint) (rate(http_requests_total{job="example-service"}[5m])) * 100

# Visualization: Heatmap
```

### Dashboard 4: Request ID & Trace Correlation

**Purpose**: Trace correlation and request tracking

**Panels**:

#### 4.1 Requests with Trace IDs

```promql
# Query (requires custom metric if tracking trace coverage)
sum(rate(http_requests_total{job="example-service"}[5m]))

# Visualization: Stat panel
# Display: Total requests with trace correlation
```

#### 4.2 Exemplar Click-Through

Configure data source to enable exemplar click-through:

```yaml
# In Grafana data source configuration
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    jsonData:
      exemplarTraceIdDestinations:
        - name: trace_id
          datasourceUid: tempo  # Link to Tempo data source
          urlDisplayLabel: 'View Trace'
```

### Dashboard Import

Save dashboards as JSON and import:

```bash
# Export dashboard JSON
curl -H "Authorization: Bearer $GRAFANA_API_KEY" \
  http://grafana:3000/api/dashboards/db/middleware-overview -o dashboard.json

# Import dashboard
curl -X POST -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -d @dashboard.json \
  http://grafana:3000/api/dashboards/db
```

## Alerting Rules

### Prometheus Alert Rules

Create `/etc/prometheus/rules/middleware_alerts.yml`:

```yaml
groups:
  - name: middleware_performance
    interval: 30s
    rules:
      # High error rate (> 1%)
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{job="example-service", status=~"5.."}[5m])) /
          sum(rate(http_requests_total{job="example-service"}[5m])) > 0.01
        for: 5m
        labels:
          severity: critical
          component: middleware
        annotations:
          summary: "High 5xx error rate in example-service"
          description: "Error rate is {{ $value | humanizePercentage }} (threshold: 1%)"
          dashboard: "https://grafana/d/middleware-overview"

      # High p99 latency (> 1s)
      - alert: HighLatency
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket{job="example-service"}[5m])) by (le, endpoint)
          ) > 1.0
        for: 5m
        labels:
          severity: warning
          component: middleware
        annotations:
          summary: "High p99 latency on {{ $labels.endpoint }}"
          description: "p99 latency is {{ $value | humanizeDuration }}"

      # Middleware errors
      - alert: MiddlewareErrors
        expr: |
          sum by (middleware_name, error_type) (
            rate(middleware_errors_total{job="example-service"}[5m])
          ) > 0.1
        for: 2m
        labels:
          severity: critical
          component: middleware
        annotations:
          summary: "Errors in {{ $labels.middleware_name }}"
          description: "{{ $labels.error_type }}: {{ $value | humanize }} errors/sec"

  - name: middleware_security
    interval: 30s
    rules:
      # Potential DoS attack (size limit rejections)
      - alert: SizeLimitAttack
        expr: |
          sum(rate(request_size_limit_rejections_total{job="example-service"}[5m])) > 5
        for: 5m
        labels:
          severity: warning
          component: security
        annotations:
          summary: "High request size rejection rate"
          description: "Potential DoS attack: {{ $value }} rejections/sec"

      # Rate limit abuse
      - alert: RateLimitAbuse
        expr: |
          sum by (limit_key_type) (
            rate(rate_limit_rejections_total{job="example-service"}[5m])
          ) > 10
        for: 5m
        labels:
          severity: warning
          component: security
        annotations:
          summary: "High rate limit rejection rate"
          description: "{{ $labels.limit_key_type }}: {{ $value }} rejections/sec"

  - name: middleware_availability
    interval: 30s
    rules:
      # Service down
      - alert: ServiceDown
        expr: |
          up{job="example-service"} == 0
        for: 1m
        labels:
          severity: critical
          component: availability
        annotations:
          summary: "Example service is down"
          description: "Service has been unreachable for 1 minute"

      # High request queue (many in-progress requests)
      - alert: HighRequestQueue
        expr: |
          sum(http_requests_in_progress{job="example-service"}) > 100
        for: 5m
        labels:
          severity: warning
          component: performance
        annotations:
          summary: "High number of in-progress requests"
          description: "{{ $value }} requests currently being processed"
```

Update `prometheus.yml` to include rules:

```yaml
rule_files:
  - /etc/prometheus/rules/middleware_alerts.yml
```

### Alertmanager Configuration

Configure Alertmanager to route alerts:

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  receiver: 'default'
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h

  routes:
    # Critical alerts → PagerDuty
    - match:
        severity: critical
      receiver: 'pagerduty'
      continue: true

    # Warnings → Slack
    - match:
        severity: warning
      receiver: 'slack'

receivers:
  - name: 'default'
    webhook_configs:
      - url: 'http://webhook:5000/alerts'

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: '<PAGERDUTY_SERVICE_KEY>'
        description: '{{ .CommonAnnotations.summary }}'

  - name: 'slack'
    slack_configs:
      - api_url: '<SLACK_WEBHOOK_URL>'
        channel: '#alerts'
        title: '{{ .CommonAnnotations.summary }}'
        text: '{{ .CommonAnnotations.description }}'
```

## Trace Correlation

### OpenTelemetry Configuration

The middleware automatically creates trace exemplars linking metrics to traces.

#### Enable OpenTelemetry

Configure in `.env`:

```bash
# OpenTelemetry settings
OTEL_ENABLED=true
OTEL_SERVICE_NAME=example-service
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0  # Sample 100% (reduce in production)
```

#### Tempo Configuration

Set up Tempo for trace storage:

```yaml
# tempo.yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317

storage:
  trace:
    backend: local
    local:
      path: /var/tempo/traces

querier:
  max_concurrent_queries: 20

metrics_generator:
  processor:
    service_graphs:
      dimensions:
        - name
    span_metrics:
      dimensions:
        - name
```

#### Grafana Tempo Data Source

Add Tempo to Grafana:

```yaml
apiVersion: 1
datasources:
  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      tracesToLogs:
        datasourceUid: loki
        tags: ['request_id', 'trace_id']
      serviceMap:
        datasourceUid: prometheus
```

### Trace-to-Metrics Correlation

With exemplars enabled:

1. **In Grafana**: Click on a spike in the latency graph
2. **View Exemplar**: See the trace ID linked to that metric point
3. **Click "View Trace"**: Navigate directly to the trace in Tempo
4. **Analyze**: See full request flow with span details

Example query with exemplar:

```promql
# In Grafana, this query will show exemplars as clickable dots
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{job="example-service"}[5m])) by (le)
)
```

## Log Aggregation

### Loki Integration

Forward logs to Loki for centralized log aggregation.

#### Promtail Configuration

```yaml
# promtail.yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: example-service
    static_configs:
      - targets:
          - localhost
        labels:
          job: example-service
          __path__: /var/log/example-service/*.log

    pipeline_stages:
      # Parse JSON logs
      - json:
          expressions:
            timestamp: timestamp
            level: level
            message: message
            request_id: request_id
            trace_id: trace_id
            method: method
            path: path
            status_code: status_code
            duration: duration

      # Extract labels
      - labels:
          level:
          request_id:
          trace_id:

      # Add timestamp
      - timestamp:
          source: timestamp
          format: RFC3339Nano
```

#### Log Queries in Grafana

Example LogQL queries:

```logql
# All logs for a specific request
{job="example-service"} | json | request_id="a1b2c3d4-e5f6-7890-1234-567890abcdef"

# Error logs only
{job="example-service", level="ERROR"}

# Slow requests (duration > 1s)
{job="example-service"} | json | duration > 1.0

# Logs for a specific trace
{job="example-service"} | json | trace_id="a1b2c3d4e5f6..."
```

### Log-to-Trace Correlation

In Grafana, configure Loki data source for trace correlation:

```yaml
datasources:
  - name: Loki
    type: loki
    url: http://loki:3100
    jsonData:
      derivedFields:
        - datasourceUid: tempo
          matcherRegex: "trace_id=([a-f0-9]+)"
          name: TraceID
          url: "$${__value.raw}"
```

Now clicking on a log entry with a trace_id will link directly to the trace.

## Troubleshooting

### Issue: Metrics Not Appearing

**Diagnosis:**

```bash
# Check /metrics endpoint is accessible
curl http://localhost:8000/metrics

# Verify Prometheus can scrape
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="example-service") | .health'
```

**Solutions:**

- Ensure `/metrics` endpoint is not blocked by middleware or firewall
- Check Prometheus scrape configuration
- Verify network connectivity between Prometheus and application

### Issue: Exemplars Not Showing

**Diagnosis:**

```bash
# Check if traces are being generated
curl http://localhost:8000/api/v1/status -v
# Response should include traceparent header

# Verify Prometheus exemplar storage
curl -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=http_request_duration_seconds{job="example-service"}' | jq '.data.result[].exemplars'
```

**Solutions:**

- Enable OpenTelemetry: `OTEL_ENABLED=true`
- Configure Prometheus with exemplar storage (see Prometheus Configuration above)
- Ensure Grafana Tempo data source is configured

### Issue: High Cardinality Metrics

**Symptom:** Prometheus memory usage increasing, slow queries

**Diagnosis:**

```bash
# Check metric cardinality
curl -G http://localhost:9090/api/v1/status/tsdb | jq '.data.seriesCountByMetricName' | sort -rn -k2 | head -10
```

**Solutions:**

- Use route templates instead of actual paths in `endpoint` label
- Limit number of unique labels (e.g., use `limit_key_type` instead of actual IPs)
- Drop high-cardinality labels using Prometheus relabeling:

```yaml
metric_relabel_configs:
  - source_labels: [endpoint]
    regex: '/api/v1/users/[0-9]+'
    replacement: '/api/v1/users/{id}'
    target_label: endpoint
```

### Issue: Missing Request IDs in Logs

**Diagnosis:**

```bash
# Check logs for request_id field
grep request_id /var/log/example-service/app.log

# Verify RequestIDMiddleware is registered
python -c "from example_service.app.main import app; print([m.cls.__name__ for m in app.user_middleware])"
```

**Solutions:**

- Ensure RequestIDMiddleware is registered first (last in configuration)
- Check logging context is set: `set_log_context(request_id=request_id)`
- Verify logging formatter includes request_id field

## Best Practices

### 1. Metric Naming Conventions

Follow Prometheus naming conventions:

- Use `_total` suffix for counters
- Use `_seconds` suffix for durations
- Use `_bytes` suffix for sizes
- Use descriptive labels: `method`, `endpoint`, `status`

### 2. Dashboard Organization

- Create separate dashboards for different audiences (developers, SRE, management)
- Use template variables for filtering (e.g., `$environment`, `$service`)
- Add documentation panels with markdown explaining metrics

### 3. Alert Tuning

- Start with conservative thresholds and tune based on baseline
- Use `for` clause to avoid alert fatigue from transient issues
- Group related alerts to reduce noise

### 4. Trace Sampling

In production, reduce trace sampling to manage costs:

```bash
# Sample 10% of traces
OTEL_TRACES_SAMPLER_ARG=0.1
```

Always sample errors:

```python
# In middleware, force sampling for errors
if response.status_code >= 500:
    span.set_attribute("force_sample", True)
```

## Related Documentation

- [Deployment Validation](./DEPLOYMENT_VALIDATION.md) - Deployment checklist
- [Middleware Architecture](./MIDDLEWARE_ARCHITECTURE.md) - Implementation details
- [Security Configuration](./SECURITY_CONFIGURATION.md) - Security best practices

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-25 | AI Assistant | Initial monitoring setup guide |
