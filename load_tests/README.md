# Load Testing

This directory contains load testing infrastructure for the FastAPI application.

## Tools

### Locust (Python-based)

[Locust](https://locust.io/) is a Python-based load testing framework with a web UI.

#### Installation

```bash
pip install locust
```

#### Usage

```bash
# Start with web UI
locust -f load_tests/locustfile.py --host=http://localhost:8000

# Run headless
locust -f load_tests/locustfile.py --host=http://localhost:8000 \
    --headless --users 100 --spawn-rate 10 --run-time 5m

# Generate HTML report
locust -f load_tests/locustfile.py --host=http://localhost:8000 \
    --headless -u 50 -r 5 -t 2m --html=report.html
```

### k6 (Go-based)

[k6](https://k6.io/) is a modern load testing tool with excellent metrics and scripting.

#### Installation

```bash
# macOS
brew install k6

# Linux
sudo apt-get install k6

# Docker
docker pull grafana/k6
```

#### Usage

```bash
# Run default scenario
k6 run load_tests/k6/scenarios.js

# Run with custom VUs and duration
k6 run --vus 50 --duration 5m load_tests/k6/scenarios.js

# Run specific scenario
k6 run --env SCENARIO=spike_test load_tests/k6/scenarios.js

# Output results to JSON
k6 run --out json=results.json load_tests/k6/scenarios.js

# With Docker
docker run --rm -i grafana/k6 run - < load_tests/k6/scenarios.js
```

## Test Scenarios

### 1. Smoke Test
Quick validation that the system works under minimal load.
- 1-5 users
- 1 minute duration

### 2. Load Test
Standard load to verify performance under expected traffic.
- 20-50 users
- 5-10 minutes duration

### 3. Stress Test
Push the system beyond normal capacity to find breaking points.
- Ramp up to 150+ users
- Monitor error rates and response times

### 4. Spike Test
Sudden traffic surge simulation.
- 0 → 100 users instantly
- Hold for 1 minute
- Quick drop to 0

### 5. Soak Test
Extended duration test to find memory leaks and degradation.
- 30 users
- 30+ minutes duration

## Metrics to Monitor

### Key Performance Indicators

| Metric | Target | Critical |
|--------|--------|----------|
| Response Time (p95) | < 500ms | > 1000ms |
| Error Rate | < 1% | > 5% |
| Throughput | > 100 RPS | < 50 RPS |
| CPU Usage | < 70% | > 90% |
| Memory Usage | < 80% | > 95% |

### Endpoints to Test

1. **Health Checks**: `/api/v1/health`, `/api/v1/health/ready`
2. **Reminders CRUD**: `/api/v1/reminders`
3. **Search**: `/api/v1/search`
4. **Audit Logs**: `/api/v1/audit/logs`
5. **Metrics**: `/metrics`

## Best Practices

1. **Warm up**: Allow the application to warm up before measuring
2. **Isolate**: Run tests in a dedicated environment
3. **Monitor**: Watch application and infrastructure metrics
4. **Baseline**: Establish performance baselines before changes
5. **Automate**: Include load tests in CI/CD pipeline

## Integration with CI/CD

### GitHub Actions Example

```yaml
load-test:
  runs-on: ubuntu-latest
  needs: [deploy-staging]
  steps:
    - uses: actions/checkout@v4

    - name: Run k6 Load Test
      uses: grafana/k6-action@v0.3.1
      with:
        filename: load_tests/k6/scenarios.js
        flags: --vus 10 --duration 1m

    - name: Upload Results
      uses: actions/upload-artifact@v4
      with:
        name: load-test-results
        path: results.json
```

## Grafana Integration

k6 can output metrics to InfluxDB/Grafana for visualization:

```bash
k6 run --out influxdb=http://localhost:8086/k6 load_tests/k6/scenarios.js
```

Import the [k6 dashboard](https://grafana.com/grafana/dashboards/2587) for real-time monitoring.
