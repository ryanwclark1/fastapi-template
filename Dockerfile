# Build stage
FROM python:3.13-slim as builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock* ./
# Include README so hatch can build the local package during uv sync
COPY README.md README.md

# Install dependencies
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.13-slim

# Copy uv from builder
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Copy installed packages and application code
COPY --from=builder /app/.venv /app/.venv
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live')" || exit 1

# Use uv to run the application
CMD ["uv", "run", "uvicorn", "example_service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
