# Understanding Mypy Type Stub Installation

## Why Mypy Tried to Install Type Stubs for Packages Not in Your Project

When you ran `uv run mypy .`, mypy attempted to install type stubs for packages like:
- `Flask-Cors`, `PyMySQL`, `psycopg2`
- `bleach`, `colorama`, `gevent`, `greenlet`, `grpcio`
- `openpyxl`, `pexpect`, `psutil`, `requests`, `ujson`

### The Root Cause

Your mypy configuration had `install_types = true`, which tells mypy to automatically install type stubs for any package it encounters during type checking. Mypy scans:

1. **Your direct dependencies** (from `pyproject.toml`)
2. **Transitive dependencies** (dependencies of your dependencies)
3. **All installed packages** in your environment

### Where These Packages Come From

#### From `locust` (Load Testing Tool)

You have `locust>=2.29.0` in your `loadtest` dependency group. Locust brings in:

- **Flask** - Locust uses Flask for its web UI
- **flask-cors** - CORS support for the web UI
- **requests** - HTTP client for load testing
- **gevent** - Async networking library
- **greenlet** - Lightweight coroutines (dependency of gevent)
- **psutil** - System and process utilities
- **colorama** - Terminal colors (Windows support)

#### Other Transitive Dependencies

- **grpcio** - May come from OpenTelemetry or other gRPC-using packages
- **bleach** - HTML sanitization (may come from markdown/HTML processing libraries)
- **pexpect** - Terminal automation (may come from test/deployment tools)
- **ujson** - Fast JSON parser (may come from various async libraries)

#### Packages You Actually Use

- **openpyxl** - You use this in `example_service/features/datatransfer/importers.py` (optional dependency)

#### Packages NOT Actually Installed

- **PyMySQL** - Not in your lock file, but mypy may have detected it through:
  - Import statements in transitive dependencies
  - SQLAlchemy dialect detection
  - Type checking heuristics

- **psycopg2** - Not in your lock file (you use `psycopg` v3 instead), but mypy may detect it because:
  - SQLAlchemy supports both psycopg2 and psycopg
  - Some libraries have optional psycopg2 imports

## The Solution

We've disabled automatic type stub installation by setting `install_types = false` in your mypy configuration. This means:

1. ✅ Mypy will no longer try to install stubs for transitive dependencies
2. ✅ You have explicit control over which type stubs are installed
3. ✅ Type stubs are managed in your `[dependency-groups]` dev section

### Current Type Stubs in Your Project

You have these type stubs explicitly listed in `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "types-pyyaml>=6.0.12.20250915",      # For PyYAML
    "types-python-dateutil>=2.9.0.20251115",  # For python-dateutil
    "types-redis>=4.6.0.20241004",       # For redis
    "types-openpyxl>=3.1.0",             # For openpyxl (optional)
]
```

### If You Want to Re-enable Auto-Installation

If you prefer to have mypy automatically install type stubs, you can:

1. Set `install_types = true` in `pyproject.toml`
2. Set `non_interactive = true` to avoid prompts
3. Accept that mypy will install stubs for transitive dependencies

However, this is generally not recommended because:
- It can install unnecessary type stubs
- It makes your environment less predictable
- It can slow down CI/CD pipelines
- It's harder to track what type stubs you're using

### Adding Type Stubs Manually

If you need type stubs for a specific package, add it to your dev dependencies:

```toml
[dependency-groups]
dev = [
    # ... existing stubs ...
    "types-requests>=2.31.0",  # Example: if you start using requests directly
]
```

## Checking Your Dependency Tree

To see where packages come from:

```bash
# See all dependencies
uv tree

# See dependencies for a specific package
uv tree --package locust

# List installed packages
uv pip list
```

## Summary

- **Problem**: `install_types = true` made mypy install stubs for transitive dependencies
- **Solution**: Set `install_types = false` and manage type stubs explicitly
- **Result**: You have full control over which type stubs are installed
- **Benefit**: Cleaner, more predictable development environment

