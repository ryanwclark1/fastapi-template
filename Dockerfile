# Multi-stage Dockerfile for FastAPI Service
# Optimized for production with security and performance in mind
# Using UV package manager following best practices from:
# https://docs.astral.sh/uv/guides/integration/docker/
# https://github.com/astral-sh/uv-docker-example

###############################################
# Stage 1: Builder - Use official UV image
###############################################
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Set environment variables for UV
ENV UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_PYTHON_DOWNLOADS=0

# Install build dependencies
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
  gcc \
  libc6-dev \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock* ./
# Include README so hatch can build the local package during uv sync
COPY README.md README.md

# Install dependencies with build cache
# uv sync will automatically create .venv if it doesn't exist
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-dev

###############################################
# Stage 2: Production - Use matching Python version
###############################################
FROM python:3.14-slim AS production

# Configurable port (change this value or override with --build-arg APP_PORT=XXXX)
ARG APP_PORT=8000

# Set runtime environment variables
ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PATH="/app/.venv/bin:$PATH"

# Install runtime dependencies
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
  libpq5 \
  curl \
  tini \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Create app user for security (uid 1000)
RUN groupadd -g 1000 appuser && \
  useradd -r -u 1000 -g appuser appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appuser . .

# Copy and set up entrypoint script
COPY --chown=appuser:appuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Create directories for logs and temp files
RUN mkdir -p /app/logs /app/tmp && \
  chown -R appuser:appuser /app

# Switch to app user
USER appuser

# Expose port
EXPOSE ${APP_PORT}

# Health check endpoint (adjust path based on your actual health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:${APP_PORT}/api/v1/health/live || exit 1

# Use tini for proper signal handling + migration script
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint.sh"]

# Default command - start FastAPI application
# Using venv's python directly (no UV needed at runtime)
# The entrypoint script will run migrations, then exec this command
CMD ["sh", "-c", "python -m uvicorn example_service.app.main:app --host 0.0.0.0 --port ${APP_PORT}"]

# Alternative commands (uncomment as needed):
#
# Single worker (default):
# CMD python -m uvicorn example_service.app.main:app --host 0.0.0.0 --port ${APP_PORT}
#
# Multiple workers (adjust based on CPU cores):
# CMD python -m uvicorn example_service.app.main:app --host 0.0.0.0 --port ${APP_PORT} --workers 4
#
# With Gunicorn (for production with multiple workers):
# CMD gunicorn example_service.app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${APP_PORT}
#
# Development mode (if needed):
# CMD python -m uvicorn example_service.app.main:app --reload --host 0.0.0.0 --port ${APP_PORT}

