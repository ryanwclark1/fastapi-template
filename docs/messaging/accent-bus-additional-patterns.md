# Additional accent-bus Patterns for Consideration

This document captures additional sophisticated patterns from `accent-bus` that could enhance the `example_service` template, beyond what was already incorporated.

## Key Additional Patterns

### 1. Event Organization with Models and Routing Files

**Location**: `accent_bus/events/{domain}/models.py` and `routing.py`

**Pattern**:
- Separate `models.py` for event Pydantic models
- Separate `routing.py` for routing key formats and access control
- Domain-based organization (e.g., `events/user/`, `events/call/`)

**Example Structure**:
```
events/
  user/
    models.py      # UserCreatedEvent, UserUpdatedEvent, etc.
    routing.py     # routing_key_fmt, required_acl_fmt per event
  call/
    models.py
    routing.py
```

**Recommendation for example_service**:
- Document this as an advanced pattern for larger services
- Keep current flat structure for simplicity
- Reference accent-bus structure in documentation as a scaling pattern

### 2. BaseEvent with Computed Fields

**Location**: `accent_bus/events/base.py`

**Key Features**:
- `@computed_field` for dynamic routing keys
- Automatic header generation via `headers()` method
- Support for ClassVar static values or computed fields
- Automatic escaping of routing key values

**Pattern**:
```python
class BaseEvent(BaseModel):
    content: dict[str, Any]

    @computed_field
    def routing_key(self) -> str:
        # Computed from routing_key_fmt and content
        return fmt.format(**escaped_vars)

    def headers(self) -> dict[str, Any]:
        # Auto-generates headers from model fields
        return self.model_dump(exclude={"content"})
```

**Recommendation for example_service**:
- Current `BaseEvent` is simpler and sufficient
- Document accent-bus pattern as advanced option for dynamic routing
- Consider adding `headers()` method to current BaseEvent if needed

### 3. DLQ Configuration with Advanced Retry Policies

**Location**: `accent_bus/dlq.py`

**Key Features**:
- Multiple retry policies: IMMEDIATE, LINEAR, EXPONENTIAL, FIBONACCI
- Jitter support to prevent thundering herd
- Exception-based retry decisions (`should_retry_exception()`)
- Time-based retry limits (`max_retry_duration_ms`)
- Retry statistics tracking in message headers

**Recommendation for example_service**:
- Current `utils.retry` decorator uses exponential backoff (sufficient)
- Document accent-bus patterns as advanced options
- Consider adding jitter configuration to retry decorator examples
- Document exception-based retry decisions (already in examples)

### 4. DLQ Retry Statistics in Headers

**Location**: `accent_bus/dlq.py` - `DLQRetryStatistics`

**Key Features**:
- Tracks attempts, delays, duration, exceptions
- Serializes to/from message headers
- Enables detailed retry analysis

**Recommendation for example_service**:
- Document as advanced pattern
- Current retry decorator has statistics but not in headers
- Could add header serialization as optional enhancement

### 5. DLQ Metrics Integration

**Location**: `accent_bus/metrics/dlq.py`

**Key Features**:
- Collectd-formatted metrics
- Retry attempt, success, failure metrics
- DLQ movement and replay metrics
- Retry delay and duration metrics

**Recommendation for example_service**:
- Current Prometheus metrics are sufficient
- Document accent-bus collectd pattern as alternative
- Both approaches are valid

### 6. EventMiddleware Security Features

**Location**: `accent_bus/middleware.py`

**Key Security Features**:
- Format string injection prevention
- Field extraction and validation before formatting
- Forbidden attribute blocking (__class__, __dict__, etc.)
- Routing key length enforcement (255 char limit)
- UUID validation
- Idempotent escaping

**Recommendation for example_service**:
- Document security considerations in examples
- Add note about format string injection risks
- Show secure routing key patterns
- Current simple approach is fine for basic use cases

### 7. AccentBroker Composition Pattern

**Location**: `accent_bus/broker.py`

**Key Features**:
- Wraps FastStream RabbitBroker using composition
- Automatic metadata injection
- Connection state management
- DLQ middleware integration
- Health status reporting

**Recommendation for example_service**:
- Current direct FastStream usage is simpler and sufficient
- Document AccentBroker pattern as advanced wrapper option
- Useful for services needing accent-specific domain patterns

### 8. DLQ Inspector and Monitor

**Location**: `accent_bus/dlq_utils.py`

**Key Features**:
- `DLQInspector` for message inspection and replay
- `DLQMonitor` for alerting on DLQ conditions
- Statistics collection
- Message replay functionality

**Recommendation for example_service**:
- Already included basic DLQ utilities in `examples/dlq_patterns.py`
- Could enhance with full inspector pattern (optional)
- Current examples are sufficient for template

## Summary of Recommendations

### High Value (Consider Adding)
1. **Exception-based retry decisions** - ✅ Already documented in examples
2. **Time-based retry limits** - Document in retry examples
3. **Jitter configuration** - Document in retry examples
4. **Security considerations** - Add security notes to documentation

### Medium Value (Document as Advanced Patterns)
1. **Event organization structure** - Document as scaling pattern
2. **DLQ retry statistics in headers** - Document as advanced option
3. **Multiple retry policies** - Document as advanced option
4. **AccentBroker wrapper pattern** - Document as advanced option

### Low Value (Already Covered or Not Needed)
1. **DLQ metrics** - Prometheus metrics are sufficient
2. **DLQ inspector** - Basic utilities already provided
3. **BaseEvent computed fields** - Current simple approach is fine

## Action Items

1. ✅ Document exception-based retry decisions (already in retry_patterns.py)
2. Add security considerations section to faststream-patterns.md
3. Document time-based retry limits in retry examples
4. Document jitter configuration in retry examples
5. Add note about format string injection prevention
6. Document event organization patterns as advanced scaling option

## Conclusion

The current `example_service` implementation covers the essential patterns. The additional accent-bus patterns are:
- **Security-focused**: Format string injection prevention (document, don't implement unless needed)
- **Advanced retry**: Multiple policies, statistics in headers (document as options)
- **Organization**: Domain-based event structure (document as scaling pattern)
- **Metrics**: Collectd vs Prometheus (both valid, Prometheus already integrated)

The template is production-ready as-is, with accent-bus patterns documented as advanced options for teams that need them.

