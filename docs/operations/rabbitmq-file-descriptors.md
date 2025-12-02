# RabbitMQ File Descriptor Exhaustion

## Problem

The error `Ranch acceptor reducing accept rate: out of file descriptors` indicates that RabbitMQ has exhausted available file descriptors. This is a system resource limitation issue.

### Symptoms

- Repeated warnings in RabbitMQ logs: `Ranch acceptor reducing accept rate: out of file descriptors`
- RabbitMQ unable to accept new connections
- Application connection timeouts
- Degraded performance or service unavailability

## Root Causes

1. **Connection Leaks**: Connections not properly closed, accumulating over time
2. **Too Many Concurrent Connections**: Multiple services/instances creating excessive connections
3. **Low System Limits**: File descriptor limits too low for the workload
4. **Connection Pool Misconfiguration**: Not reusing connections effectively

## Solutions

### 1. Check Current File Descriptor Usage

```bash
# Check RabbitMQ process file descriptor usage
ps aux | grep rabbitmq
# Get PID from above, then:
ls -l /proc/<PID>/fd | wc -l

# Check system-wide file descriptor limits
ulimit -n
cat /proc/sys/fs/file-max

# Check current usage
cat /proc/sys/fs/file-nr
```

### 2. Increase System File Descriptor Limits

#### For Docker (Recommended Solution)

Since you're using Docker, add `ulimits` to your `docker-compose.yml`:

```yaml
services:
  rabbitmq:
    image: rabbitmq:4-management-alpine
    # ... other configuration ...
    ulimits:
      nofile:
        soft: 65536
        hard: 65536

  api:
    # ... other configuration ...
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
```

**Note**: The `docker-compose.yml` in this project has already been updated with these limits.

After updating, restart the services:
```bash
docker-compose down
docker-compose up -d
```

#### Verify Docker Limits

Check if limits are applied:
```bash
# Check RabbitMQ container limits
docker exec rabbitmq sh -c "ulimit -n"

# Check API container limits
docker exec <api-container-name> sh -c "ulimit -n"
```

**Important**: If Docker daemon itself has low limits, container limits may not work properly. Check Docker daemon limits:

```bash
# Check Docker daemon file descriptor limit
cat /proc/$(pgrep dockerd)/limits | grep "open files"

# If Docker daemon limit is too low, increase it in systemd:
# Edit /etc/systemd/system/docker.service.d/override.conf:
[Service]
LimitNOFILE=65536

# Then restart Docker:
sudo systemctl daemon-reload
sudo systemctl restart docker
```

#### For systemd (Non-Docker Installations)

Edit `/etc/systemd/system/rabbitmq-server.service` or create override:

```ini
[Service]
LimitNOFILE=65536
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart rabbitmq-server
```

#### For Shell/Manual Execution

```bash
# Temporary (current session)
ulimit -n 65536

# Permanent (add to ~/.bashrc or /etc/security/limits.conf)
# /etc/security/limits.conf:
* soft nofile 65536
* hard nofile 65536
```

### 3. Configure RabbitMQ Connection Limits

Edit RabbitMQ configuration (`/etc/rabbitmq/rabbitmq.conf` or via environment):

```conf
# Limit connections per user
connection_max = 1000

# Limit channels per connection
channel_max = 2047

# Connection timeout
handshake_timeout = 10000
```

### 4. Fix Connection Leaks in Application

#### Issue: `broker_context()` Creates New Connections

The current `broker_context()` implementation in `example_service/infra/messaging/broker.py` calls `broker.start()` and `broker.close()` each time, which may create new connections instead of reusing them.

**Solution**: Ensure FastStream's RabbitRouter manages connections automatically. The `broker_context()` should only be used when the broker is not already connected (e.g., in Taskiq workers).

#### Best Practices

1. **Use `Depends(get_broker)` in FastAPI endpoints** - This reuses the existing broker connection
2. **Minimize `broker_context()` usage** - Only use in isolated contexts (Taskiq workers)
3. **Monitor connection count** - Track active connections in RabbitMQ management UI

### 5. Connection Pooling Configuration

The `pool_size` setting in `conf/rabbit.yaml` may not be used by FastStream. FastStream's RabbitRouter manages connections internally.

To verify connection reuse:
- Check RabbitMQ Management UI: `http://localhost:15672` → Connections
- Monitor connection count over time
- Look for connections that don't close

### 6. RabbitMQ Resource Limits

Configure in RabbitMQ (`/etc/rabbitmq/rabbitmq.conf`):

```conf
# Memory limit (adjust based on available RAM)
vm_memory_high_watermark.relative = 0.4

# Disk space limit
disk_free_limit.absolute = 2GB

# Connection backpressure
backpressure_threshold = 50
```

### 7. Monitoring and Alerting

Set up monitoring for:
- Active connections count
- File descriptor usage
- Connection rate
- Failed connection attempts

Example Prometheus query:
```promql
rabbitmq_connections{state="running"}
```

## Immediate Actions (Docker)

1. **Check current limits in Docker container**:
   ```bash
   docker exec rabbitmq sh -c "ulimit -n"
   ```

2. **Update docker-compose.yml** (already done in this project):
   - Add `ulimits` section to `rabbitmq` service
   - Add `ulimits` section to `api` service

3. **Restart services**:
   ```bash
   cd deployment/docker
   docker-compose down
   docker-compose up -d
   ```

4. **Verify limits are applied**:
   ```bash
   docker exec rabbitmq sh -c "ulimit -n"
   # Should show 65536
   ```

5. **Monitor connections**:
   - Access RabbitMQ Management UI: `http://localhost:15672`
   - Login: `admin` / `admin123`
   - Check Connections tab
   - Look for stale/unclosed connections

6. **Review application code**:
   - Ensure all `broker_context()` calls are in `finally` blocks
   - Prefer `Depends(get_broker)` in FastAPI endpoints
   - Avoid creating multiple broker instances

## Immediate Actions (Non-Docker)

1. **Check current limits**:
   ```bash
   ulimit -n
   cat /proc/sys/fs/file-max
   ```

2. **Increase limits** (see Solution #2 above)

3. **Restart RabbitMQ**:
   ```bash
   sudo systemctl restart rabbitmq-server
   ```

## Prevention

1. **Set appropriate file descriptor limits** at system and process level
2. **Use connection pooling** effectively (FastStream handles this)
3. **Monitor connection metrics** regularly
4. **Implement connection timeouts** to prevent stale connections
5. **Review code** for connection leaks during code reviews

## References

- [RabbitMQ File Descriptors](https://www.rabbitmq.com/production-checklist.html#file-descriptors)
- [System Limits Configuration](https://www.rabbitmq.com/install-debian.html#kernel-resource-limits)
- [FastStream Connection Management](https://faststream.airt.ai/latest/getting-started/connection/)

