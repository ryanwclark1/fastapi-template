# accent-bus Patterns Review for example_service Enhancement

This document captures additional patterns from `accent-bus` that should be considered for the `example_service` FastStream messaging enhancements.

## Key Patterns from accent-bus

### 1. DLQ Middleware with Advanced Retry Logic

**Location**: `accent_bus/dlq_middleware.py`

**Key Features**:
- Automatic retry wrapping for all subscribers
- Exception-based retry decisions (`should_retry_exception()`)
- Time-based retry limits (`max_retry_duration_ms`)
- Jitter in retry delays (prevents thundering herd)
- Retry statistics tracking in message headers
- Multiple retry policies (IMMEDIATE, LINEAR, EXPONENTIAL, FIBONACCI)

**Recommendation for example_service**:
- Consider adding DLQ middleware pattern as optional enhancement
- Document exception-based retry decisions
- Add time-based retry limits to retry decorator usage examples
- Show jitter configuration in retry examples

### 2. DLQ Utilities for Inspection and Replay

**Location**: `accent_bus/dlq_utils.py`

**Key Features**:
- `DLQInspector` class for inspecting DLQ messages
- `replay_message()` for replaying failed messages
- `get_stats()` for DLQ statistics
- `format_message_summary()` for human-readable summaries
- `DLQMonitor` for alerting on DLQ conditions

**Recommendation for example_service**:
- Add as optional enhancement (not required for basic template)
- Provides production-ready DLQ management tools
- Useful for operations and debugging

### 3. Connection State Management

**Location**: `accent_bus/broker.py` (ConnectionState enum)

**Key Features**:
- Enum-based connection states: DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, FAILED
- State tracking throughout connection lifecycle
- Health status includes state information

**Recommendation for example_service**:
- Add connection state enum to broker.py
- Include state in health check responses
- Document state transitions

### 4. DLQ Metrics Integration

**Location**: `accent_bus/metrics/dlq.py`

**Key Features**:
- Retry attempt metrics
- DLQ message movement metrics
- Retry duration metrics
- Retry success/failure metrics
- Collectd-formatted metrics

**Recommendation for example_service**:
- Add as optional enhancement
- Integrate with existing Prometheus metrics
- Document available DLQ metrics

### 5. Event Middleware with Security

**Location**: `accent_bus/middleware.py`

**Key Features**:
- Format string injection prevention
- Secure routing key computation
- Access control computation
- Header generation with metadata

**Recommendation for example_service**:
- Document security considerations in examples
- Show secure routing key patterns
- Note format string injection risks

### 6. Structured Event Organization

**Location**: `accent_bus/events/`

**Key Features**:
- Separate `models.py` and `routing.py` files per event domain
- Base event class with computed fields
- Routing key format strings
- Access control requirements

**Recommendation for example_service**:
- Document event organization patterns
- Show routing key format examples
- Reference accent-bus structure as advanced pattern

## Integration Recommendations

### High Priority (Include in Core Plan)
1. ✅ Connection state management (enum + health check)
2. ✅ Exception-based retry decisions (document in examples)
3. ✅ Time-based retry limits (show in retry examples)
4. ✅ DLQ message inspection utilities (add to dlq_patterns.py)

### Medium Priority (Optional Enhancements)
1. DLQ middleware pattern (automatic retry wrapping)
2. DLQ metrics integration
3. DLQ replay utilities
4. DLQ monitoring and alerting

### Low Priority (Documentation Only)
1. Security patterns (format string injection prevention)
2. Advanced event organization patterns
3. Multiple retry policies (beyond exponential)

## Updated Plan Considerations

The current plan should be enhanced with:

1. **Connection State Tracking**: Add to broker.py health check
2. **DLQ Utilities**: Add to dlq_patterns.py examples
3. **Exception-Based Retry**: Document in retry_patterns.py
4. **Time-Based Retry Limits**: Show in retry decorator examples
5. **DLQ Metrics**: Optional enhancement section

These patterns from accent-bus complement the existing plan and provide production-ready patterns for the template.

