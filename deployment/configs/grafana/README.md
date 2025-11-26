# Grafana Configuration

This directory contains all configuration and provisioned resources for Grafana, following best practices from the [Grafana provisioning documentation](https://grafana.com/docs/grafana/latest/administration/provisioning/).

## Directory Structure

```
deployment/configs/grafana/
├── grafana.ini                    # Main Grafana configuration file
├── provisioning/                  # Provisioning configurations
│   ├── datasources/               # Data source definitions
│   │   └── datasources.yaml       # Prometheus, Loki, Tempo connections
│   └── dashboards/                # Dashboard provisioning settings
│       └── dashboards.yaml        # Dashboard loader configuration
└── dashboards/                    # Provisioned dashboard definitions (read-only)
    ├── infrastructure/            # Infrastructure monitoring dashboards
    │   └── infrastructure.json
    ├── application/               # Application-level dashboards
    │   ├── application-overview.json
    │   └── service-overview.json
    └── observability/             # Logging, tracing, and monitoring
        ├── log-browser.json
        ├── metrics-overview.json
        └── trace-explorer.json
```

## Docker Volume Mappings

The Grafana service uses the following volume mounts:

| Local Path | Container Path | Mode | Purpose |
|------------|----------------|------|---------|
| `grafana.ini` | `/etc/grafana/grafana.ini` | `ro` | Main configuration file |
| `provisioning/` | `/etc/grafana/provisioning` | `ro` | Auto-provisioning configs |
| `dashboards/` | `/var/lib/grafana/dashboards/provisioned` | `ro` | Read-only dashboards |
| `grafana-data` (volume) | `/var/lib/grafana` | `rw` | User data & custom dashboards |

## Dashboard Organization

### Provisioned Dashboards (Read-Only)

Provisioned dashboards are:
- **Version-controlled**: Stored in Git as JSON files
- **Read-only**: `allowUiUpdates: false` prevents UI modifications
- **Auto-organized**: `foldersFromFilesStructure: true` creates Grafana folders matching directory structure
- **Immutable**: `disableDeletion: true` prevents deletion via UI

To update a provisioned dashboard:
1. Export the dashboard JSON from Grafana UI
2. Update the corresponding file in `dashboards/`
3. Commit to version control
4. Grafana automatically reloads within 30 seconds

### User-Created Dashboards (Read-Write)

User-created dashboards are:
- **Stored in Docker volume**: Persisted in the `grafana-data` volume
- **Fully editable**: Can be created, modified, and deleted via UI
- **Separate from provisioned**: No conflicts with version-controlled dashboards
- **Persistent**: Survive container restarts and recreations

## Configuration Management

### grafana.ini

The main configuration file (`grafana.ini`) defines:
- **Paths**: Data, logs, plugins, and provisioning directories
- **Security**: Authentication, session management, security headers
- **Features**: Anonymous access, dashboards, alerting, explore
- **Database**: SQLite configuration for storing Grafana metadata

Environment variables can override any setting using the format `GF_<SECTION>_<KEY>`. For example:
- `GF_AUTH_ANONYMOUS_ENABLED=true` overrides `[auth.anonymous] enabled`
- `GF_SECURITY_ADMIN_PASSWORD=newpass` overrides `[security] admin_password`

Current environment variable overrides in `docker-compose.yml`:
```yaml
- GF_AUTH_ANONYMOUS_ENABLED=true      # Enable anonymous access
- GF_AUTH_ANONYMOUS_ORG_ROLE=Admin    # Grant admin role to anonymous users
- GF_AUTH_DISABLE_LOGIN_FORM=true     # Hide login form (development only)
```

⚠️ **Security Warning**: Anonymous admin access is enabled for development convenience. For production deployments:
1. Set `GF_AUTH_ANONYMOUS_ENABLED=false`
2. Remove `GF_AUTH_DISABLE_LOGIN_FORM=true`
3. Change default admin password in `grafana.ini` or via `GF_SECURITY_ADMIN_PASSWORD`

### Provisioning Datasources

Data sources are auto-configured via `provisioning/datasources/datasources.yaml`:
- **Prometheus**: Metrics (port 9090)
- **Loki**: Logs (port 3100)
- **Tempo**: Traces (port 3200)

### Provisioning Dashboards

Dashboard provisioning is configured in `provisioning/dashboards/dashboards.yaml`:
- **Update interval**: Checks for dashboard changes every 30 seconds
- **Folder structure**: Automatically creates folders from directory hierarchy
- **Read-only enforcement**: Prevents modifications to ensure consistency

## Adding New Dashboards

### Adding a Provisioned Dashboard

1. Create or export the dashboard JSON
2. Place it in the appropriate category folder:
   - `infrastructure/` - System resources, containers, networks
   - `application/` - Application metrics, service health
   - `observability/` - Metrics rollups plus logging & tracing tooling
3. Commit to version control
4. Grafana automatically loads it within 30 seconds

### Creating a Custom Dashboard

1. Access Grafana UI at http://localhost:3003
2. Create a new dashboard via UI
3. Dashboard is automatically saved to `grafana-data` volume
4. Persists across container restarts

## Troubleshooting

### Dashboards not appearing

1. Check Grafana logs: `docker compose logs grafana`
2. Verify file permissions (should be readable by container)
3. Validate JSON syntax: `cat dashboards/category/dashboard.json | jq .`
4. Check provisioning status in Grafana UI: Configuration → Plugins

### "Dashboard cannot be saved" error

This is expected for provisioned dashboards (`allowUiUpdates: false`). To make changes:
1. Export the dashboard JSON from UI
2. Update the source file in the repository
3. Commit and let Grafana reload automatically

### Lost user-created dashboards

User dashboards are stored in the `grafana-data` Docker volume. To back them up:
```bash
# Export all dashboards
docker compose exec grafana grafana-cli admin export-dashboard

# List volumes
docker volume ls | grep grafana

# Backup volume
docker run --rm -v grafana-data:/data -v $(pwd):/backup alpine tar czf /backup/grafana-backup.tar.gz -C /data .
```

## References

- [Grafana Configuration Documentation](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/)
- [Provisioning Documentation](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Dashboard JSON Model](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/view-dashboard-json-model/)
