# Prometheus Configuration

This directory contains the configuration for Prometheus, including metrics collection (scraping) and alert rule definitions.

## Directory Structure

```
deployment/configs/prometheus/
├── prometheus.yml    # Main Prometheus configuration
├── alerts.yml        # Alert rule definitions
└── README.md         # This file
```

## Configuration Files

### prometheus.yml

Main Prometheus configuration defining:
- **Scrape interval**: How often to collect metrics (15s)
- **Evaluation interval**: How often to evaluate alert rules (15s)
- **Scrape configs**: Which services to collect metrics from
- **Alerting**: Where to send fired alerts (AlertManager)
- **Rule files**: Which alert rule files to load

### alerts.yml

Comprehensive alert rules organized into groups:
- Application Health (error rates, 5xx errors)
- Performance (response times, slow queries)
- Circuit Breakers (state monitoring, failure rates)
- Rate Limiting (hit rates, excessive limiting)
- Authentication & Authorization (auth failures, invalid tokens)
- External Services (service health, latency, timeouts)
- Dependencies (unhealthy dependencies, connection pools)
- Cache Performance (hit rates)
- Resource Utilization (memory, CPU)
- Retries & Failures
- Validation Errors

## Monitored Services

Prometheus is configured to scrape metrics from:

| Service | Port | Metrics Path | Purpose |
|---------|------|--------------|---------|
| prometheus | 9090 | `/metrics` | Prometheus self-monitoring |
| api | 8000 | `/metrics` | FastAPI application metrics |
| tempo | 3200 | `/metrics` | Tempo tracing backend |
| alloy | 12346 | `/` | Grafana Alloy telemetry collector |

## Alert Rule Groups

### 1. Application Health (`application_health`)

**HighErrorRate** (Warning)
- Trigger: Error rate > 5% for 5 minutes
- Labels: `severity: warning`, `component: application`
- Use: Indicates elevated but manageable error rates

**CriticalErrorRate** (Critical)
- Trigger: Error rate > 10% for 2 minutes
- Labels: `severity: critical`, `component: application`
- Use: Immediate attention required

**High5xxErrorRate** (Warning)
- Trigger: 5xx error rate > 1% for 5 minutes
- Use: Backend/server errors detected

### 2. Performance (`performance`)

**HighResponseTime** (Warning)
- Trigger: P95 response time > 1s for 5 minutes
- Labels: `severity: warning`, `component: performance`

**VeryHighResponseTime** (Critical)
- Trigger: P95 response time > 5s for 2 minutes
- Use: Critical performance degradation

**SlowQueriesDetected** (Warning)
- Trigger: > 1 slow query per second for 5 minutes
- Labels: `component: database`

### 3. Circuit Breakers (`circuit_breakers`)

**CircuitBreakerOpen** (Critical)
- Trigger: Circuit breaker state == 2 (open) for 1 minute
- Labels: `severity: critical`, `component: resilience`
- Use: Service calls being blocked by circuit breaker

**HighCircuitBreakerFailureRate** (Warning)
- Trigger: > 5 failures per second for 2 minutes

**FrequentCircuitBreakerStateChanges** (Warning)
- Trigger: Circuit breaker flapping (changing state frequently)

### 4. Rate Limiting (`rate_limiting`)

**HighRateLimitHitRate** (Warning)
- Trigger: > 10 rate limit hits per second for 5 minutes
- Use: Many requests being rate limited

**ExcessiveRateLimiting** (Warning)
- Trigger: > 20% of requests rate limited for 10 minutes
- Use: May indicate limits too restrictive or attack

### 5. Authentication & Authorization (`auth`)

**HighAuthFailureRate** (Warning)
- Trigger: > 20% auth attempts failing for 5 minutes
- Labels: `component: auth`
- Use: Possible brute force or credential issues

**InvalidTokenSpike** (Warning)
- Trigger: > 10 invalid tokens per second for 2 minutes

### 6. External Services (`external_services`)

**ExternalServiceDown** (Critical)
- Trigger: > 50% of calls failing for 3 minutes
- Labels: `severity: critical`, `component: external`

**HighExternalServiceLatency** (Warning)
- Trigger: P95 latency > 5s for 5 minutes

**ExternalServiceTimeouts** (Warning)
- Trigger: > 1 timeout per second for 3 minutes

### 7. Dependencies (`dependencies`)

**DependencyUnhealthy** (Critical)
- Trigger: Dependency health == 0 for 2 minutes
- Labels: `component: dependency`

**DatabaseConnectionPoolExhausted** (Warning)
- Trigger: > 90 active connections for 5 minutes

### 8. Cache Performance (`cache`)

**LowCacheHitRate** (Warning)
- Trigger: Hit rate < 80% for 10 minutes
- Labels: `component: cache`
- Use: Cache not effective, may need tuning

### 9. Resource Utilization (`resources`)

**HighMemoryUsage** (Warning)
- Trigger: Memory > 2GB for 5 minutes

**HighCPUUsage** (Warning)
- Trigger: CPU > 80% for 5 minutes

### 10. Retries & Failures (`retries`)

**HighRetryRate** (Warning)
- Trigger: > 1 operation exhausting retries per second
- Labels: `component: resilience`

### 11. Validation Errors (`validation`)

**HighValidationErrorRate** (Warning)
- Trigger: > 10% requests have validation errors for 10 minutes

## Alert Labels

All alerts use consistent labels for routing and grouping:

- `severity`: `critical` or `warning`
- `component`: Identifies system component (application, database, cache, auth, etc.)
- `alertname`: Unique alert identifier

## Alert Annotations

Each alert includes annotations for context:

- `summary`: Brief description of the alert
- `description`: Detailed information with metric values and thresholds

Example:
```yaml
annotations:
  summary: "High error rate on {{ $labels.endpoint }}"
  description: "Error rate is {{ $value | humanizePercentage }} on endpoint {{ $labels.endpoint }} (threshold: 5%)"
```

## Customizing Alerts

### Adjusting Thresholds

Edit `alerts.yml` and modify the `expr` (expression):

```yaml
# Before: Trigger at 5% error rate
expr: |
  (sum(rate(errors_total[5m])) by (endpoint) / sum(rate(http_requests_total[5m])) by (endpoint)) > 0.05

# After: Trigger at 10% error rate
expr: |
  (sum(rate(errors_total[5m])) by (endpoint) / sum(rate(http_requests_total[5m])) by (endpoint)) > 0.10
```

### Adjusting Duration

Modify the `for` clause:

```yaml
# Before: Fire after 5 minutes
for: 5m

# After: Fire after 10 minutes
for: 10m
```

### Adding New Alert Rules

1. Choose the appropriate group or create a new one
2. Add your rule:

```yaml
groups:
  - name: custom_alerts
    interval: 30s
    rules:
      - alert: MyCustomAlert
        expr: |
          my_metric_total > 100
        for: 5m
        labels:
          severity: warning
          component: custom
        annotations:
          summary: "Custom metric threshold exceeded"
          description: "my_metric_total is {{ $value }} (threshold: 100)"
```

3. Validate the configuration:
```bash
docker exec -it prometheus promtool check rules /etc/prometheus/alerts.yml
```

4. Reload Prometheus:
```bash
docker compose restart prometheus
```

## Testing Alert Rules

### Check Alert Status

Visit Prometheus UI: http://localhost:9091/alerts

Or use the API:
```bash
curl http://localhost:9091/api/v1/alerts | jq .
```

### Simulate Alert Conditions

For testing, you can temporarily lower thresholds to trigger alerts with current metrics:

```yaml
# Temporarily set a very low threshold for testing
- alert: TestHighErrorRate
  expr: |
    (sum(rate(errors_total[5m])) by (endpoint) / sum(rate(http_requests_total[5m])) by (endpoint)) > 0.001
  for: 1m  # Short duration for testing
```

### Validate Expressions

Test PromQL expressions in Prometheus UI (Graph tab):

```promql
# Test error rate calculation
(
  sum(rate(errors_total[5m])) by (endpoint)
  /
  sum(rate(http_requests_total[5m])) by (endpoint)
)

# Test with threshold
(
  sum(rate(errors_total[5m])) by (endpoint)
  /
  sum(rate(http_requests_total[5m])) by (endpoint)
) > 0.05
```

## Alert Lifecycle

1. **Pending**: Alert condition met, waiting for `for` duration
2. **Firing**: Alert active, sent to AlertManager
3. **Resolved**: Condition no longer met, resolution sent to AlertManager

## Alert Best Practices

### Writing Good Alert Rules

1. **Be Specific**: Alert on symptoms (high latency) not causes (CPU high)
2. **Set Appropriate Thresholds**: Based on historical data and SLOs
3. **Use `for` Clause**: Avoid flapping alerts from brief spikes
4. **Add Context**: Use labels and annotations to provide debugging information
5. **Test Regularly**: Ensure alerts fire when expected

### Alert Fatigue Prevention

1. **Group Related Alerts**: Use AlertManager grouping
2. **Inhibition Rules**: Suppress lower-severity related alerts
3. **Appropriate Severity**: Not everything is critical
4. **Adjust Repeat Intervals**: Critical: 4h, Warning: 12h
5. **Review and Tune**: Regularly assess false positives

### Performance Considerations

1. **Query Efficiency**: Complex PromQL queries impact Prometheus performance
2. **Evaluation Interval**: Balance between responsiveness and load (15s is reasonable)
3. **Label Cardinality**: Avoid high-cardinality labels in alert expressions
4. **Recording Rules**: Pre-compute complex queries for frequently-evaluated alerts

## Monitoring Prometheus

Prometheus exposes its own metrics at http://localhost:9091/metrics:

Key metrics to monitor:
- `prometheus_rule_evaluation_duration_seconds`: Alert rule evaluation time
- `prometheus_rule_evaluation_failures_total`: Failed evaluations
- `prometheus_tsdb_head_samples`: Memory usage indicator
- `prometheus_target_scrape_duration_seconds`: Scrape performance

## Troubleshooting

### Alerts Not Firing

1. **Check alert expression**:
   ```bash
   # Test in Prometheus UI Graph tab
   (sum(rate(errors_total[5m])) by (endpoint) / sum(rate(http_requests_total[5m])) by (endpoint)) > 0.05
   ```

2. **Verify metrics exist**:
   ```bash
   # Check if metrics are being collected
   curl http://localhost:9091/api/v1/query?query=errors_total
   ```

3. **Check evaluation**:
   ```bash
   docker compose logs prometheus | grep -i "error\|fail"
   ```

### Alerts Always Firing

1. **Check thresholds**: May be too sensitive
2. **Verify metric values**: May have units mismatch
3. **Check `for` duration**: May be too short

### Configuration Errors

```bash
# Validate prometheus.yml
docker exec -it prometheus promtool check config /etc/prometheus/prometheus.yml

# Validate alerts.yml
docker exec -it prometheus promtool check rules /etc/prometheus/alerts.yml

# Check logs
docker compose logs prometheus
```

## Reloading Configuration

After modifying configuration files:

```bash
# Method 1: Restart container
docker compose restart prometheus

# Method 2: Hot reload (if enabled)
curl -X POST http://localhost:9091/-/reload

# Verify config loaded
docker compose logs prometheus | tail -20
```

## Resources

- [Prometheus Documentation](https://prometheus.io/docs/prometheus/latest/getting_started/)
- [PromQL Guide](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Recording Rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/)
- [Best Practices](https://prometheus.io/docs/practices/alerting/)
- [PromQL Cheat Sheet](https://promlabs.com/promql-cheat-sheet/)
