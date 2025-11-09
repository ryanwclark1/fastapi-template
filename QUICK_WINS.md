# Quick Wins for Production Readiness

**Time estimate: 1-2 days to implement all critical items**

These are the highest-impact, easiest-to-implement enhancements that will significantly improve production readiness.

---

## 🔒 Critical Security (2-3 hours)

### 1. Add Security Headers Middleware

**File:** `example_service/app/middleware.py`

```python
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # CSP - customize based on your needs
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self';"
        )
        return response

# In configure_middleware()
app.add_middleware(SecurityHeadersMiddleware)
```

### 2. Add Rate Limiting

**Install:** `uv add slowapi`

**File:** `example_service/app/middleware.py`

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# In create_app()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# In routes
from slowapi import Limiter
from fastapi import Request

@router.post("/login")
@limiter.limit("5/minute")  # Custom limit for sensitive endpoints
async def login(request: Request, credentials: LoginRequest):
    ...
```

### 3. Add Request Size Limits

**File:** `example_service/app/middleware.py`

```python
from starlette.datastructures import Headers

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Limit request body size."""

    def __init__(self, app, max_size: int = 10 * 1024 * 1024):  # 10MB default
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Max size: {self.max_size} bytes"}
                )
        return await call_next(request)

# In configure_middleware()
app.add_middleware(RequestSizeLimitMiddleware, max_size=10_485_760)  # 10MB
```

---

## 🚀 CI/CD Pipeline (2-3 hours)

### Create GitHub Actions Workflow

**File:** `.github/workflows/ci.yml`

```yaml
name: CI

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main, develop]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --all-groups

      - name: Run ruff (lint)
        run: uv run ruff check .

      - name: Run ruff (format check)
        run: uv run ruff format --check .

      - name: Run mypy
        run: uv run mypy example_service

  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: test_db
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --all-groups

      - name: Run tests with coverage
        run: uv run pytest --cov=example_service --cov-report=xml --cov-report=term
        env:
          DB_DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/test_db
          REDIS_REDIS_URL: redis://localhost:6379/0

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          fail_ci_if_error: false

  build:
    runs-on: ubuntu-latest
    needs: [lint, test]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: example-service:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

**File:** `.github/workflows/security.yml`

```yaml
name: Security Scan

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  schedule:
    - cron: '0 0 * * 0'  # Weekly

jobs:
  trivy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          format: 'sarif'
          output: 'trivy-results.sarif'

      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: 'trivy-results.sarif'
```

---

## 🎯 Essential K8s Manifests (1 hour)

### ConfigMap

**File:** `k8s/configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: example-service-config
  namespace: default
data:
  APP_SERVICE_NAME: "example-service"
  APP_ENVIRONMENT: "production"
  APP_DEBUG: "false"
  APP_DISABLE_DOCS: "true"  # Disable in production
  LOG_LEVEL: "INFO"
  LOG_JSON: "true"
  OTEL_ENABLED: "true"
  OTEL_SERVICE_NAME: "example-service"
```

### Service

**File:** `k8s/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: example-service
  namespace: default
  labels:
    app: example-service
spec:
  selector:
    app: example-service
  ports:
    - name: http
      port: 80
      targetPort: 8000
      protocol: TCP
  type: ClusterIP
```

### Ingress

**File:** `k8s/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: example-service
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.example.com
      secretName: example-service-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: example-service
                port:
                  number: 80
```

### HPA (Horizontal Pod Autoscaler)

**File:** `k8s/hpa.yaml`

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: example-service-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: example-service
  minReplicas: 2
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
```

---

## 📊 Basic Monitoring (30 minutes)

### Prometheus ServiceMonitor

**File:** `k8s/service-monitor.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: example-service
  namespace: default
  labels:
    app: example-service
spec:
  selector:
    matchLabels:
      app: example-service
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### Simple Alert Rules

**File:** `k8s/prometheus-rules.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: example-service-alerts
  namespace: default
spec:
  groups:
    - name: example-service
      interval: 30s
      rules:
        - alert: HighErrorRate
          expr: |
            rate(http_requests_total{status=~"5.."}[5m]) > 0.05
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate detected"
            description: "Error rate is {{ $value }} (>5%)"

        - alert: HighLatency
          expr: |
            histogram_quantile(0.95, http_request_duration_seconds_bucket) > 1.0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High latency detected"
            description: "P95 latency is {{ $value }}s"

        - alert: ServiceDown
          expr: up{job="example-service"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Service is down"
            description: "example-service has been down for >1 minute"
```

---

## 📝 Makefile for Common Tasks (15 minutes)

**File:** `Makefile`

```makefile
.PHONY: help install test lint format docker-build docker-run k8s-deploy clean

help:
	@echo "Available targets:"
	@echo "  install       - Install dependencies"
	@echo "  test          - Run tests with coverage"
	@echo "  lint          - Run linters"
	@echo "  format        - Format code"
	@echo "  docker-build  - Build Docker image"
	@echo "  docker-run    - Run with docker-compose"
	@echo "  k8s-deploy    - Deploy to Kubernetes"
	@echo "  clean         - Clean build artifacts"

install:
	uv sync --all-groups

test:
	uv run pytest --cov=example_service --cov-report=html --cov-report=term

lint:
	uv run ruff check .
	uv run mypy example_service

format:
	uv run ruff format .
	uv run ruff check --fix .

docker-build:
	docker build -t example-service:latest .

docker-run:
	docker-compose up -d

k8s-deploy:
	kubectl apply -f k8s/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
```

---

## ✅ Implementation Checklist

### Day 1: Security & CI/CD (4-6 hours)
- [ ] Add security headers middleware
- [ ] Add rate limiting with slowapi
- [ ] Add request size limits
- [ ] Create GitHub Actions CI workflow
- [ ] Create GitHub Actions security workflow
- [ ] Test CI pipeline

### Day 2: K8s & Monitoring (3-4 hours)
- [ ] Create ConfigMap
- [ ] Create Service
- [ ] Create Ingress
- [ ] Create HPA
- [ ] Create ServiceMonitor
- [ ] Create basic alert rules
- [ ] Create Makefile
- [ ] Test K8s deployment

### Total Time: 1-2 days

---

## 🎯 Success Metrics

After implementing these quick wins, you should have:

- ✅ **Security:** Headers, rate limiting, request size limits
- ✅ **CI/CD:** Automated testing and security scanning
- ✅ **K8s:** Production-ready manifests with auto-scaling
- ✅ **Monitoring:** Basic metrics and alerts
- ✅ **DX:** Makefile for common tasks

---

## Next Phase (Week 2-4)

After quick wins, tackle:
1. Grafana dashboards
2. Load testing
3. Complete documentation
4. Database backup automation
5. Enhanced secrets management
