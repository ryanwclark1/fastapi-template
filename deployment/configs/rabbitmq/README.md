# RabbitMQ Configuration

This directory contains RabbitMQ configuration files for the Docker deployment.

## Files

- `rabbitmq.conf` - Main RabbitMQ configuration file

## Configuration Details

### Deprecated Features

The configuration explicitly permits deprecated features to avoid warnings:

1. **management_metrics_collection**: Used by the management plugin for metrics collection
2. **transient_nonexcl_queues**: Allows creating transient non-exclusive queues

These features are deprecated and will be removed in future RabbitMQ versions. The application should be migrated away from these features before they are removed.

### HTTP GET Request on AMQP Port

If you see errors like:
```
HTTP GET request detected on AMQP port. Ensure the client is connecting to the correct port.
```

This indicates something is trying to connect to port 5672 (AMQP) with HTTP instead of the AMQP protocol. Common causes:

1. **Misconfigured health check**: A health check tool trying to use HTTP on the AMQP port
2. **Monitoring tool**: Prometheus or another tool trying to scrape metrics from the wrong port
3. **Browser/curl**: Accidental connection to the wrong port

**Solutions**:
- Use port **15672** for HTTP/Management API access
- Use port **5672** only for AMQP protocol connections
- Check health check configurations to ensure they use the correct protocol
- For Prometheus metrics, use the management API endpoint: `http://rabbitmq:15672/api/metrics` or the Prometheus plugin endpoint: `http://rabbitmq:15692/metrics`

## Mounting Configuration

The configuration file is automatically mounted in `docker-compose.yml`:

```yaml
volumes:
  - ../configs/rabbitmq/rabbitmq.conf:/etc/rabbitmq/rabbitmq.conf:ro
```

## Modifying Configuration

After modifying `rabbitmq.conf`, restart the RabbitMQ container:

```bash
docker-compose restart rabbitmq
```

## References

- [RabbitMQ Configuration Guide](https://www.rabbitmq.com/configure.html)
- [RabbitMQ Deprecated Features](https://www.rabbitmq.com/deprecated-features.html)
- [RabbitMQ Management Plugin](https://www.rabbitmq.com/management.html)

