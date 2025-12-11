# Running Database Migrations in Docker

This guide covers different approaches for running Alembic migrations in containerized environments.

## Overview

Your project uses:
- **Alembic** for database migrations
- **Custom CLI** (`example-service db`) with programmatic Alembic API
- **Docker** for containerization
- **PostgreSQL** as the database

## Approaches

### 1. Automatic Migrations on Startup (Recommended for Development)

**How it works:** The `docker-entrypoint.sh` script runs migrations automatically before starting the application.

**Pros:**
- ✅ Simple - no manual intervention needed
- ✅ Works great for development and staging
- ✅ Ensures migrations are always current

**Cons:**
- ⚠️ Not ideal for production with multiple app instances (race conditions)
- ⚠️ App startup delayed by migration time

**Usage:**
```bash
# Using docker-compose
docker-compose up

# Using docker directly
docker run -p 8000:8000 --env-file .env fastapitemplate:latest
```

The entrypoint script automatically runs:
```bash
example-service db upgrade
```

---

### 2. Separate Migration Service (Recommended for Production)

**How it works:** Use a dedicated one-time container to run migrations, then start the app.

**Pros:**
- ✅ Production-safe - migrations run once before scaling app
- ✅ Clear separation of concerns
- ✅ Works with orchestrators (Kubernetes, Docker Swarm)

**Cons:**
- ⚠️ Slightly more complex setup

**Usage:**
```bash
# Using the alternative docker-compose file
docker-compose -f docker-compose.migrate-service.yml up

# Or manually with docker
docker run --env-file .env fastapitemplate:latest example-service db upgrade
docker run -p 8000:8000 --env-file .env fastapitemplate:latest
```

---

### 3. Manual Execution

**How it works:** Run migrations manually using `docker exec` or `docker run`.

**Pros:**
- ✅ Full control over when migrations run
- ✅ Good for testing migration rollbacks

**Cons:**
- ⚠️ Manual process, easy to forget

**Usage:**

**Option A: Exec into running container**
```bash
# Start app
docker-compose up -d app

# Run migrations
docker-compose exec app example-service db upgrade

# Check status
docker-compose exec app example-service db check
```

**Option B: One-off container**
```bash
docker-compose run --rm app example-service db upgrade
```

**Option C: Interactive shell**
```bash
docker-compose run --rm app /bin/bash
example-service db upgrade
example-service db check
exit
```

---

### 4. Kubernetes Init Container

**How it works:** Use an init container to run migrations before the main app pod starts.

**Pros:**
- ✅ Production-ready
- ✅ Automatic with K8s deployments
- ✅ Handles failures gracefully

**Example:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
spec:
  template:
    spec:
      initContainers:
      - name: migrate
        image: fastapitemplate:latest
        command: ["example-service", "db", "upgrade"]
        env:
          - name: DB_HOST
            value: postgres-service
          - name: DB_NAME
            valueFrom:
              secretKeyRef:
                name: db-credentials
                key: database
      containers:
      - name: app
        image: fastapitemplate:latest
        ports:
        - containerPort: 8000
```

---

## Available Migration Commands

Your CLI provides these migration commands:

```bash
# Apply all pending migrations
example-service db upgrade

# Check migration status
example-service db check

# Show current database revision
example-service db current

# Show pending migrations
example-service db pending

# Create new migration
example-service db migrate -m "description"

# Show migration history
example-service db history

# Rollback migrations
example-service db downgrade --steps 1

# Reset database (destructive!)
example-service db reset --confirm

# Database connection info
example-service db info
```

---

## Environment Variables

Ensure these are set in your container environment:

```bash
# Required
DB_HOST=postgres              # Database host
DB_PORT=5432                  # Database port
DB_NAME=example_db           # Database name
DB_USER=postgres             # Database user
DB_PASSWORD=secretpassword   # Database password

# Optional
APP_ENV=production           # Environment (development/staging/production)
LOG_LEVEL=INFO              # Logging level
```

---

## Production Best Practices

### 1. **Use Separate Migration Jobs**
Don't run migrations in every app instance. Use:
- Init containers (Kubernetes)
- One-time jobs (Docker Swarm, ECS)
- CI/CD pipeline steps
- Separate migration service (docker-compose)

### 2. **Check Before Deploy**
```bash
# Generate SQL without executing (review changes)
docker-compose exec app example-service db sql

# Check for pending migrations
docker-compose exec app example-service db pending
```

### 3. **Handle Failures**
```bash
# Verify migration status
docker-compose exec app example-service db check

# If stuck, check current state
docker-compose exec app example-service db current

# Rollback if needed (be careful!)
docker-compose exec app example-service db downgrade --steps 1
```

### 4. **Zero-Downtime Deployments**
For zero-downtime migrations:
1. Make migrations backward-compatible
2. Deploy migration + new code separately
3. Use expand-contract pattern for schema changes

---

## Troubleshooting

### Migration fails with "database is not up to date"
```bash
# Check current revision
docker-compose exec app example-service db current

# Check what's pending
docker-compose exec app example-service db pending

# Apply migrations
docker-compose exec app example-service db upgrade
```

### Multiple app instances race to run migrations
**Solution:** Use approach #2 (separate migration service) or Kubernetes init containers.

### Container can't connect to database
```bash
# Check database is running
docker-compose ps db

# Test connection
docker-compose exec app example-service db init

# Check environment variables
docker-compose exec app printenv | grep DB_
```

### Want to run migrations manually
```bash
# Disable automatic migrations by overriding entrypoint
docker-compose run --rm --entrypoint /bin/bash app

# Then manually run
example-service db upgrade
```

---

## Files

- `docker-entrypoint.sh` - Startup script that runs migrations automatically
- `docker-compose.yml` - Development setup with automatic migrations
- `docker-compose.migrate-service.yml` - Production-style setup with separate migration service
- `Dockerfile` - Container definition with migration support

---

## Quick Reference

| Scenario | Command |
|----------|---------|
| Start everything (auto-migrate) | `docker-compose up` |
| Manual migration | `docker-compose exec app example-service db upgrade` |
| Check migration status | `docker-compose exec app example-service db check` |
| Create new migration | `docker-compose exec app example-service db migrate -m "message"` |
| Production deployment | Use `docker-compose.migrate-service.yml` or K8s init container |
| Disable auto-migrations | Override `ENTRYPOINT` in compose file |
