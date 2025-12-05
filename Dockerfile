###############################################
# Base Image
###############################################
FROM python:3.13-slim AS python-base

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  UV_SYSTEM_PYTHON=1 \
  UV_COMPILE_BYTECODE=1 \
  VENV_PATH="/app/.venv"

ENV PATH="$VENV_PATH/bin:$PATH"

###############################################
# Builder Image
###############################################
FROM python-base AS builder-base

# Install build dependencies
RUN apt-get update -qq \
  && apt-get install -y --no-install-recommends \
  curl \
  gcc \
  libc6-dev \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

# Install UV
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Create virtual environment
RUN uv venv .venv

# Copy dependency files
COPY pyproject.toml uv.lock* ./
# Include README so hatch can build the local package during uv sync
COPY README.md README.md

# Install dependencies
RUN uv sync --frozen --no-dev

###############################################
# Production Image
###############################################
FROM python-base AS production

# Install runtime dependencies
RUN apt-get update -qq \
  && apt-get install -y --no-install-recommends \
  libpq5 \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Copy uv from builder (needed for uv run)
COPY --from=builder-base /root/.local/bin/uv /usr/local/bin/uv

# Copy the virtual environment
COPY --from=builder-base /app/.venv /app/.venv

# Copy application code
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
