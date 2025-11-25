# Logging System - Future Enhancements

This document outlines potential enhancements to the logging system that could be implemented in the future. These features would build upon the existing loguru-inspired logging infrastructure.

---

## 1. Structured Binding

### Overview

Add a `logger.bind()` method to create logger instances with permanent context fields, providing a more ergonomic alternative to repeatedly calling `set_log_context()`.

### Current State

Context is managed globally via `set_log_context()`:

```python
from example_service.infra.logging import set_log_context
import logging

logger = logging.getLogger(__name__)

# Must set context before each operation
set_log_context(user_id=123, request_id="abc-123")
logger.info("Processing request")  # Includes user_id and request_id

# Context persists across logs (using ContextVar)
logger.info("Request complete")  # Still includes user_id and request_id
```

### Proposed Enhancement

Allow binding context to specific logger instances:

```python
from example_service.infra.logging import get_logger

# Create logger with bound context
logger = get_logger(__name__).bind(user_id=123, request_id="abc-123")

# All logs from this logger automatically include bound fields
logger.info("Processing request")  # Includes user_id and request_id
logger.info("Request complete")    # Still includes user_id and request_id

# Create child logger with additional context
api_logger = logger.bind(endpoint="/api/users")
api_logger.info("API call")  # Includes user_id, request_id, AND endpoint

# Original logger unaffected
logger.info("Back to base context")  # Only user_id and request_id
```

### Implementation Approach

1. **Extend `ContextBoundLogger`** in `example_service/infra/logging/context.py`:
   ```python
   class ContextBoundLogger(logging.LoggerAdapter):
       def __init__(self, logger: logging.Logger, extra: dict[str, Any] | None = None):
           super().__init__(logger, extra or {})
           self._bound_context: dict[str, Any] = {}

       def bind(self, **kwargs: Any) -> ContextBoundLogger:
           """Create new logger with additional bound context."""
           new_logger = ContextBoundLogger(self.logger, self.extra)
           new_logger._bound_context = {**self._bound_context, **kwargs}
           return new_logger

       def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
           # Merge bound context with current context
           extra = kwargs.get("extra", {})
           extra.update(self._bound_context)
           extra.update(get_log_context())
           kwargs["extra"] = extra
           return msg, kwargs
   ```

2. **Update `get_logger()`** to return `ContextBoundLogger` by default:
   ```python
   def get_logger(name: str | None = None, **bind_context: Any) -> ContextBoundLogger:
       """Get logger with optional initial bound context."""
       logger = logging.getLogger(name)
       bound_logger = ContextBoundLogger(logger)
       if bind_context:
           return bound_logger.bind(**bind_context)
       return bound_logger
   ```

3. **Add to public API** in `example_service/infra/logging/__init__.py`:
   ```python
   __all__ = [
       # ... existing exports ...
       "get_logger",  # Already exported, but now returns ContextBoundLogger with bind()
   ]
   ```

### Benefits

- **Ergonomics**: More natural than global context management
- **Clarity**: Context is explicit per logger instance
- **Composability**: Can create hierarchies of bound loggers
- **Thread-safe**: Each logger instance has independent bound context
- **Backwards compatible**: Existing `set_log_context()` still works

### Use Cases

**HTTP Request Handling:**
```python
async def handle_request(request: Request):
    # Create request-scoped logger
    logger = get_logger(__name__).bind(
        request_id=request.state.request_id,
        user_id=request.state.user_id,
        method=request.method,
        path=request.url.path
    )

    logger.info("Request started")
    # ... process request ...
    logger.info("Request completed")
    # All logs automatically include request context
```

**Background Task Processing:**
```python
async def process_task(task: Task):
    # Bind task context
    logger = get_logger(__name__).bind(
        task_id=task.id,
        task_type=task.type,
        queue=task.queue_name
    )

    logger.info("Task started")
    # Pass logger to sub-functions
    await process_step_1(task, logger)
    await process_step_2(task, logger)
    logger.info("Task completed")
```

**Service Integration:**
```python
class ExternalAPIClient:
    def __init__(self, api_key: str):
        # Bind service-level context
        self.logger = get_logger(__name__).bind(
            service="external_api",
            api_version="v2"
        )

    async def fetch_user(self, user_id: int):
        # Bind operation-specific context
        logger = self.logger.bind(operation="fetch_user", user_id=user_id)
        logger.info("Fetching user")
        # ... API call ...
        logger.info("User fetched successfully")
```

---

## 2. Time-Based Log Rotation

### Overview

Add support for time-based log rotation (hourly, daily, weekly) in addition to the existing size-based rotation.

### Current State

Logs rotate based on file size only:

```yaml
# conf/logging.yaml
file_path: logs/example-service.log.jsonl
file_max_bytes: 10485760  # 10 MB
file_backup_count: 5       # Keep 5 rotated files
```

This creates files like:
```
logs/example-service.log.jsonl
logs/example-service.log.jsonl.1
logs/example-service.log.jsonl.2
```

### Proposed Enhancement

Support time-based rotation with configurable intervals:

```yaml
# conf/logging.yaml
file_path: logs/example-service.log.jsonl

# Time-based rotation
rotation_type: time  # Options: size, time, both
rotation_interval: daily  # Options: hourly, daily, weekly, midnight
rotation_time: "00:00"  # For daily: time to rotate (default midnight)
rotation_day: 0  # For weekly: day of week (0=Monday, 6=Sunday)

# Keep existing size-based options for "both" mode
file_max_bytes: 10485760
file_backup_count: 7  # Keep 7 days of logs
```

This would create files like:
```
logs/example-service.log.jsonl
logs/example-service.log.jsonl.2025-01-20
logs/example-service.log.jsonl.2025-01-21
logs/example-service.log.jsonl.2025-01-22
```

### Implementation Approach

1. **Add rotation settings** to `example_service/core/settings/logs.py`:
   ```python
   class LoggingSettings(BaseSettings):
       # ... existing fields ...

       rotation_type: Literal["size", "time", "both"] = Field(
           default="size",
           description="Log rotation strategy: size-based, time-based, or both"
       )

       rotation_interval: Literal["hourly", "daily", "weekly", "midnight"] = Field(
           default="midnight",
           description="Time interval for rotation when rotation_type is 'time' or 'both'"
       )

       rotation_time: str = Field(
           default="00:00",
           description="Time of day for daily rotation (HH:MM format)"
       )

       rotation_day: int = Field(
           default=0,
           ge=0,
           le=6,
           description="Day of week for weekly rotation (0=Monday, 6=Sunday)"
       )
   ```

2. **Update `configure_logging()`** in `example_service/infra/logging/config.py`:
   ```python
   def _configure_with_dictconfig(
       # ... existing params ...
       rotation_type: Literal["size", "time", "both"],
       rotation_interval: str,
       rotation_time: str,
       rotation_day: int,
   ) -> None:
       """Configure logging with time-based rotation support."""

       if file_path:
           if rotation_type == "time":
               # Use TimedRotatingFileHandler
               from logging.handlers import TimedRotatingFileHandler

               # Map interval names to TimedRotatingFileHandler arguments
               when_map = {
                   "hourly": "H",
                   "daily": "D",
                   "weekly": "W",
                   "midnight": "midnight"
               }

               file_handler = TimedRotatingFileHandler(
                   file_path,
                   when=when_map[rotation_interval],
                   interval=1,
                   backupCount=file_backup_count,
                   atTime=_parse_rotation_time(rotation_time) if rotation_interval == "daily" else None
               )

           elif rotation_type == "both":
               # Use custom handler that combines both strategies
               file_handler = SizeAndTimeRotatingFileHandler(
                   file_path,
                   maxBytes=file_max_bytes,
                   backupCount=file_backup_count,
                   when=when_map[rotation_interval],
                   interval=1
               )

           else:  # rotation_type == "size"
               # Use existing RotatingFileHandler
               file_handler = RotatingFileHandler(
                   file_path,
                   maxBytes=file_max_bytes,
                   backupCount=file_backup_count
               )
   ```

3. **Create custom handler** for "both" mode (optional):
   ```python
   class SizeAndTimeRotatingFileHandler(TimedRotatingFileHandler):
       """Handler that rotates on both size and time."""

       def __init__(self, filename, maxBytes=0, backupCount=0, when='midnight', interval=1, **kwargs):
           super().__init__(filename, when=when, interval=interval, backupCount=backupCount, **kwargs)
           self.maxBytes = maxBytes

       def shouldRollover(self, record):
           # Check time-based rollover
           if super().shouldRollover(record):
               return True

           # Check size-based rollover
           if self.maxBytes > 0:
               if self.stream is None:
                   self.stream = self._open()
               msg = self.format(record)
               self.stream.seek(0, 2)
               if self.stream.tell() + len(msg) >= self.maxBytes:
                   return True

           return False
   ```

### Benefits

- **Compliance**: Many regulations require daily log retention
- **Predictability**: Logs rotate at consistent times
- **Easier archival**: One file per day/hour simplifies backup scripts
- **Better organization**: Time-based filenames are more intuitive
- **Flexibility**: Can combine size and time strategies

### Use Cases

**Daily Rotation for Compliance:**
```yaml
rotation_type: time
rotation_interval: midnight
file_backup_count: 30  # Keep 30 days for compliance
```

**Hourly Rotation for High-Volume Services:**
```yaml
rotation_type: time
rotation_interval: hourly
file_backup_count: 168  # Keep 7 days (7 * 24 hours)
```

**Combined Strategy (Size + Time):**
```yaml
rotation_type: both
rotation_interval: daily      # Rotate at midnight
file_max_bytes: 100000000    # Also rotate if exceeds 100MB
file_backup_count: 14        # Keep 2 weeks
```

---

## 3. Log Compression

### Overview

Automatically compress rotated log files using gzip to save disk space, especially valuable for production systems with high log volume.

### Current State

Rotated logs remain uncompressed:

```
logs/example-service.log.jsonl       # Current (10 MB)
logs/example-service.log.jsonl.1     # Rotated (10 MB)
logs/example-service.log.jsonl.2     # Rotated (10 MB)
logs/example-service.log.jsonl.3     # Rotated (10 MB)
Total: 40 MB
```

### Proposed Enhancement

Automatically compress rotated logs:

```yaml
# conf/logging.yaml
file_path: logs/example-service.log.jsonl
file_max_bytes: 10485760
file_backup_count: 5

# Compression settings
compress_rotated_logs: true     # Enable compression (default: false)
compression_algorithm: gzip     # Options: gzip, bzip2, xz (default: gzip)
compression_level: 6            # 1-9 for gzip (default: 6, balanced)
```

This would create:

```
logs/example-service.log.jsonl       # Current (10 MB)
logs/example-service.log.jsonl.1.gz  # Compressed (~1 MB)
logs/example-service.log.jsonl.2.gz  # Compressed (~1 MB)
logs/example-service.log.jsonl.3.gz  # Compressed (~1 MB)
Total: 13 MB (67% reduction)
```

**Typical compression ratios for JSON logs:**
- gzip: 85-90% reduction (10 MB → 1-1.5 MB)
- bzip2: 88-92% reduction (better compression, slower)
- xz: 90-94% reduction (best compression, slowest)

### Implementation Approach

1. **Add compression settings** to `example_service/core/settings/logs.py`:
   ```python
   class LoggingSettings(BaseSettings):
       # ... existing fields ...

       compress_rotated_logs: bool = Field(
           default=False,
           description="Enable automatic compression of rotated log files"
       )

       compression_algorithm: Literal["gzip", "bzip2", "xz"] = Field(
           default="gzip",
           description="Compression algorithm for rotated logs"
       )

       compression_level: int = Field(
           default=6,
           ge=1,
           le=9,
           description="Compression level (1=fastest, 9=best compression)"
       )
   ```

2. **Create custom rotating handler** in `example_service/infra/logging/handlers.py`:
   ```python
   import gzip
   import bz2
   import lzma
   import os
   from logging.handlers import RotatingFileHandler
   from pathlib import Path


   class CompressedRotatingFileHandler(RotatingFileHandler):
       """RotatingFileHandler that compresses rotated files."""

       def __init__(
           self,
           filename,
           mode='a',
           maxBytes=0,
           backupCount=0,
           encoding=None,
           delay=False,
           compress=True,
           compression_algorithm='gzip',
           compression_level=6
       ):
           super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
           self.compress = compress
           self.compression_algorithm = compression_algorithm
           self.compression_level = compression_level

       def doRollover(self):
           """Override doRollover to compress rotated files."""
           # Close current file
           if self.stream:
               self.stream.close()
               self.stream = None

           # Rotate files
           if self.backupCount > 0:
               for i in range(self.backupCount - 1, 0, -1):
                   sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                   dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")

                   # Handle compressed extensions
                   if self.compress:
                       sfn = self._add_compression_ext(sfn)
                       dfn = self._add_compression_ext(dfn)

                   if os.path.exists(sfn):
                       if os.path.exists(dfn):
                           os.remove(dfn)
                       os.rename(sfn, dfn)

               # Compress the file being rotated
               dfn = self.rotation_filename(f"{self.baseFilename}.1")
               if os.path.exists(self.baseFilename):
                   if self.compress:
                       self._compress_file(self.baseFilename, dfn)
                       os.remove(self.baseFilename)
                   else:
                       if os.path.exists(dfn):
                           os.remove(dfn)
                       os.rename(self.baseFilename, dfn)

           # Open new file
           if not self.delay:
               self.stream = self._open()

       def _compress_file(self, source: str, dest: str) -> None:
           """Compress source file to destination."""
           dest_compressed = self._add_compression_ext(dest)

           if self.compression_algorithm == "gzip":
               with open(source, 'rb') as f_in:
                   with gzip.open(dest_compressed, 'wb', compresslevel=self.compression_level) as f_out:
                       f_out.writelines(f_in)

           elif self.compression_algorithm == "bzip2":
               with open(source, 'rb') as f_in:
                   with bz2.open(dest_compressed, 'wb', compresslevel=self.compression_level) as f_out:
                       f_out.writelines(f_in)

           elif self.compression_algorithm == "xz":
               with open(source, 'rb') as f_in:
                   with lzma.open(dest_compressed, 'wb', preset=self.compression_level) as f_out:
                       f_out.writelines(f_in)

       def _add_compression_ext(self, filename: str) -> str:
           """Add compression extension to filename."""
           ext_map = {
               "gzip": ".gz",
               "bzip2": ".bz2",
               "xz": ".xz"
           }
           return filename + ext_map.get(self.compression_algorithm, ".gz")
   ```

3. **Update `configure_logging()`** to use compressed handler:
   ```python
   def _configure_with_dictconfig(
       # ... existing params ...
       compress_rotated_logs: bool,
       compression_algorithm: str,
       compression_level: int,
   ) -> None:
       """Configure logging with compression support."""

       if file_path:
           if compress_rotated_logs:
               from example_service.infra.logging.handlers import CompressedRotatingFileHandler

               file_handler = CompressedRotatingFileHandler(
                   file_path,
                   maxBytes=file_max_bytes,
                   backupCount=file_backup_count,
                   compress=True,
                   compression_algorithm=compression_algorithm,
                   compression_level=compression_level
               )
           else:
               # Use standard RotatingFileHandler
               file_handler = RotatingFileHandler(
                   file_path,
                   maxBytes=file_max_bytes,
                   backupCount=file_backup_count
               )
   ```

4. **Add CLI helper** for reading compressed logs:
   ```python
   # example_service/cli/commands/logs.py

   import click
   import gzip
   import bz2
   import lzma
   from pathlib import Path

   @click.command()
   @click.argument('log_file', type=click.Path(exists=True))
   @click.option('--lines', '-n', type=int, help='Number of lines to show')
   @click.option('--follow', '-f', is_flag=True, help='Follow log output (like tail -f)')
   def view(log_file: str, lines: int | None, follow: bool):
       """View compressed or uncompressed log files."""
       path = Path(log_file)

       # Detect compression from extension
       if path.suffix == '.gz':
           opener = gzip.open
       elif path.suffix == '.bz2':
           opener = bz2.open
       elif path.suffix == '.xz':
           opener = lzma.open
       else:
           opener = open

       with opener(path, 'rt') as f:
           if lines:
               # Show last N lines
               content = f.readlines()
               for line in content[-lines:]:
                   click.echo(line, nl=False)
           elif follow:
               # Follow mode (not supported for compressed)
               if path.suffix in ['.gz', '.bz2', '.xz']:
                   click.echo("Error: Follow mode not supported for compressed files", err=True)
                   return
               # Implement tail -f logic
               pass
           else:
               # Show entire file
               click.echo(f.read())
   ```

### Benefits

- **Disk space savings**: 85-90% reduction in log storage (typical for JSON)
- **Cost reduction**: Lower cloud storage costs for production logs
- **Longer retention**: Can keep more historical logs within same disk budget
- **Transparent**: Log readers (Alloy/Promtail) can handle compressed files
- **Standard format**: gzip is universally supported (`zcat`, `zgrep`, `zless`)

### Use Cases

**High-Volume Production System:**
```yaml
compress_rotated_logs: true
compression_algorithm: gzip
compression_level: 6           # Balanced speed/compression
file_backup_count: 30          # Keep 30 days instead of 5
```

**Archive-Heavy System (Compliance):**
```yaml
compress_rotated_logs: true
compression_algorithm: xz      # Maximum compression
compression_level: 9
file_backup_count: 365         # Keep 1 year of logs
rotation_interval: daily
```

**Development Environment:**
```yaml
compress_rotated_logs: false   # No compression for easy debugging
file_backup_count: 3
```

### Reading Compressed Logs

Users can read compressed logs using standard Unix tools:

```bash
# View compressed log
zcat logs/example-service.log.jsonl.1.gz

# Search in compressed log
zgrep "ERROR" logs/example-service.log.jsonl.1.gz

# Page through compressed log
zless logs/example-service.log.jsonl.1.gz

# Or use the CLI helper
python -m example_service logs view logs/example-service.log.jsonl.1.gz --lines 100
```

---

## Priority & Effort Estimates

| Feature | Priority | Effort | Impact |
|---------|----------|--------|--------|
| **Structured Binding** | High | Medium | High developer ergonomics |
| **Time-Based Rotation** | Medium | Low | Production compliance/convenience |
| **Log Compression** | Medium | Low | Significant cost/space savings |

### Recommended Implementation Order

1. **Structured Binding** (high value, self-contained)
2. **Log Compression** (easy win, immediate benefits)
3. **Time-Based Rotation** (nice-to-have, integrates with compression)

---

## Notes

- All features should maintain backwards compatibility
- Configuration should default to current behavior (opt-in)
- Each feature should include comprehensive tests
- Documentation should be updated in `conf/logging.yaml.example`
- Consider adding examples to `docs/LOGGING.md` when implemented

---

## Related Work

- **Structured binding** integrates with existing `ContextBoundLogger` and `set_log_context()`
- **Time-based rotation** works alongside existing size-based rotation
- **Compression** is compatible with both rotation strategies
- All features respect the existing JSONL format for Loki/Elasticsearch ingestion
