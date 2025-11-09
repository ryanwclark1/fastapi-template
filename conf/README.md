# Optional YAML Configuration

This directory contains optional YAML configuration files for local development convenience.

## Important Notes

- **Environment variables always win**: YAML files are loaded BEFORE environment variables
- **Production**: Use environment variables (via Kubernetes ConfigMap/Secret), not YAML files
- **Development**: YAML files can be convenient for local settings that don't change often

## Configuration Precedence

1. `init` kwargs (testing/overrides)
2. YAML/conf.d files (this directory - optional)
3. Environment variables (recommended for production)
4. `.env` file (development)
5. `secrets_dir` (Kubernetes/Docker secrets)

## File Structure

```
conf/
├── app.yaml         # Base app settings
├── app.d/           # App settings overrides (loaded alphabetically)
│   ├── 01-cors.yml
│   └── 02-docs.yml
├── db.yaml          # Database settings
├── db.d/            # Database overrides
├── rabbit.yaml      # RabbitMQ settings
├── redis.yaml       # Redis settings
├── logging.yaml     # Logging settings
└── otel.yaml        # OpenTelemetry settings
```

## Custom Config Directories

Override the config directory location via environment variables:

```bash
export APP_CONFIG_DIR=etc/my-service
export DB_CONFIG_DIR=etc/my-service
export RABBIT_CONFIG_DIR=etc/my-service
```

## Example Usage

### app.yaml
```yaml
service_name: my-service
debug: false
environment: development
cors_origins:
  - http://localhost:3000
  - http://localhost:8080
```

### app.d/01-cors.yml
```yaml
cors_allow_credentials: true
cors_allow_methods:
  - GET
  - POST
  - PUT
  - DELETE
```

### db.yaml
```yaml
pool_size: 20
pool_timeout: 30
echo_sql: false
```

## When to Use YAML Files

✅ **Good for:**
- Local development settings that rarely change
- Team-shared development configurations
- Legacy services migrating from file-based config

❌ **Avoid for:**
- Secrets (use environment variables + Kubernetes Secrets)
- Production configuration (use environment variables)
- Settings that change frequently (use .env file instead)

## Best Practice

Most projects should use environment variables only and skip YAML files entirely.
The YAML support is optional and intended for specific use cases like:
- Large mono-repos with many services
- Legacy migration from file-based config
- Complex local development setups
