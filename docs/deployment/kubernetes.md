# Kubernetes Deployment Guide

This guide covers deploying the service to Kubernetes with proper health checks, resource management, and configuration.

## Prerequisites

- Kubernetes cluster (>= 1.19)
- kubectl configured
- Docker image built and pushed to registry
- Secrets and ConfigMaps configured

## Health Check Endpoints

The service provides Kubernetes-ready health check endpoints:

### Startup Probe
```
GET /api/v1/health/startup
```
- **Purpose**: Indicates if application has finished starting
- **Returns**: 200 OK when started
- **Use**: Prevents premature liveness/readiness checks during slow startup

### Liveness Probe
```
GET /api/v1/health/live
```
- **Purpose**: Checks if application is alive and responsive
- **Returns**: Always 200 OK if service responds
- **Use**: Kubernetes restarts pod if this fails
- **Recommendation**: Keep lightweight, only checks if process is responsive

### Readiness Probe
```
GET /api/v1/health/ready
```
- **Purpose**: Checks if application is ready to accept traffic
- **Returns**:
  - 200 OK if all critical dependencies are healthy
  - 503 Service Unavailable if not ready
- **Use**: Kubernetes removes pod from service if this fails
- **Checks**: Database, cache, critical external services

### Comprehensive Health
```
GET /api/v1/health/
```
- **Purpose**: Detailed health check with all dependency statuses
- **Returns**: Health status (healthy, degraded, unhealthy) with individual checks
- **Use**: Monitoring, alerting, debugging

## Deployment

### Quick Deploy

```bash
# Create namespace
kubectl create namespace example-service

# Apply deployment
kubectl apply -f k8s/deployment.yaml -n example-service

# Verify deployment
kubectl get pods -n example-service
kubectl logs -f deployment/example-service -n example-service
```

### Deployment Configuration

#### Resource Requests and Limits

```yaml
resources:
  requests:
    memory: "256Mi"    # Minimum memory required
    cpu: "250m"        # Minimum CPU (0.25 cores)
  limits:
    memory: "512Mi"    # Maximum memory allowed
    cpu: "500m"        # Maximum CPU (0.5 cores)
```

**Recommendations:**
- **Requests**: Set based on typical usage
- **Limits**: Set with headroom for traffic spikes
- **Memory**: Monitor actual usage and adjust
- **CPU**: Start conservative, increase if throttling occurs

#### Probe Configuration

```yaml
# Startup probe - allows 150s for startup (30 failures × 5s)
startupProbe:
  httpGet:
    path: /api/v1/health/startup
    port: http
  initialDelaySeconds: 0
  periodSeconds: 5
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 30

# Liveness probe - restart after 30s unresponsive (3 failures × 10s)
livenessProbe:
  httpGet:
    path: /api/v1/health/live
    port: http
  initialDelaySeconds: 0
  periodSeconds: 10
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 3

# Readiness probe - remove from service after 15s not ready (3 failures × 5s)
readinessProbe:
  httpGet:
    path: /api/v1/health/ready
    port: http
  initialDelaySeconds: 0
  periodSeconds: 5
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 3
```

**Best Practices:**
- **Startup probe**: Use for slow-starting apps (database migrations, etc.)
- **Liveness probe**: Keep simple, avoid dependency checks
- **Readiness probe**: Check critical dependencies only
- **Timeouts**: Set lower than period to avoid overlapping checks
- **Failure thresholds**: Balance between quick failover and false positives

#### Graceful Shutdown

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 15"]
terminationGracePeriodSeconds: 30
```

**Process:**
1. Pod receives SIGTERM
2. PreStop hook sleeps 15s (allows load balancer to deregister)
3. Application handles SIGTERM (FastAPI shutdown)
4. After 30s total, SIGKILL is sent

**Recommendations:**
- **PreStop sleep**: Match load balancer deregistration time
- **Grace period**: Should be preStop + app shutdown time + buffer
- **App shutdown**: Close connections, finish requests, cleanup

## Configuration Management

### ConfigMaps

For non-sensitive configuration:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: example-service-config
data:
  redis-url: "redis://redis-service:6379/0"
  log-level: "INFO"
  enable-metrics: "true"
```

Apply:
```bash
kubectl apply -f k8s/configmap.yaml
```

### Secrets

For sensitive data:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: example-service-secrets
type: Opaque
stringData:
  database-url: "postgresql+asyncpg://user:password@postgres:5432/db"
  jwt-secret: "your-secret-key"
```

Apply:
```bash
kubectl apply -f k8s/secrets.yaml
```

**Best Practices:**
- Never commit secrets to git
- Use external secret managers (Vault, AWS Secrets Manager, etc.)
- Rotate secrets regularly
- Limit secret access via RBAC

## Scaling

### Horizontal Pod Autoscaling

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
```

Apply:
```bash
kubectl apply -f k8s/hpa.yaml
```

### Manual Scaling

```bash
# Scale to 5 replicas
kubectl scale deployment example-service --replicas=5

# Check scaling status
kubectl get hpa example-service
```

## Monitoring

### Check Pod Status

```bash
# List pods
kubectl get pods -l app=example-service

# Describe pod
kubectl describe pod <pod-name>

# View logs
kubectl logs -f <pod-name>

# Previous logs (after crash)
kubectl logs <pod-name> --previous
```

### Check Health

```bash
# Port forward to local
kubectl port-forward deployment/example-service 8000:8000

# Check health endpoints
curl http://localhost:8000/api/v1/health/
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/startup
```

### Events

```bash
# Watch events
kubectl get events --sort-by='.lastTimestamp' -w

# Filter by pod
kubectl get events --field-selector involvedObject.name=<pod-name>
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name>

# Common issues:
# - Image pull errors
# - Insufficient resources
# - ConfigMap/Secret not found
# - Startup probe failing
```

### Pod Constantly Restarting

```bash
# Check logs before crash
kubectl logs <pod-name> --previous

# Check liveness probe
kubectl describe pod <pod-name> | grep -A 10 "Liveness"

# Common causes:
# - Application crashes
# - Liveness probe too aggressive
# - Memory OOM kills
# - Deadlocks
```

### Pod Not Receiving Traffic

```bash
# Check readiness probe
kubectl describe pod <pod-name> | grep -A 10 "Readiness"

# Check service endpoints
kubectl get endpoints example-service

# Common causes:
# - Readiness probe failing
# - Dependencies unavailable
# - Database connection issues
```

### High Resource Usage

```bash
# Check resource usage
kubectl top pods -l app=example-service

# Check for memory leaks
kubectl logs <pod-name> | grep -i "memory"

# Solutions:
# - Increase resource limits
# - Investigate memory leaks
# - Enable horizontal autoscaling
```

## Best Practices

### Security

- **Run as non-root user**
- **Use read-only root filesystem where possible**
- **Set security context**
- **Scan images for vulnerabilities**
- **Use network policies**

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
```

### Reliability

- **Set resource requests and limits**
- **Use multiple replicas (3+ recommended)**
- **Configure pod disruption budgets**
- **Use anti-affinity to spread pods across nodes**
- **Implement graceful shutdown**

### Performance

- **Enable horizontal autoscaling**
- **Configure connection pooling**
- **Use persistent connections**
- **Monitor and optimize**

### Observability

- **Expose metrics endpoint**
- **Structured JSON logging**
- **Use correlation IDs**
- **Integrate with APM tools**

## Production Checklist

- [ ] Resource requests and limits configured
- [ ] Health check endpoints implemented and tested
- [ ] Startup, liveness, and readiness probes configured
- [ ] Graceful shutdown implemented
- [ ] Secrets managed securely (not in git)
- [ ] ConfigMaps for non-sensitive config
- [ ] Horizontal pod autoscaling configured
- [ ] Multiple replicas for high availability
- [ ] Pod disruption budget set
- [ ] Anti-affinity rules configured
- [ ] Security context configured
- [ ] Network policies defined
- [ ] Monitoring and alerting set up
- [ ] Log aggregation configured
- [ ] Backup and disaster recovery plan
