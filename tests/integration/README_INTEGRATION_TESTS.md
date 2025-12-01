# Integration Test Documentation

## Overview

This directory contains comprehensive integration tests for all newly added features from accent-ai services. These tests verify that features work correctly in realistic scenarios with minimal mocking.

## Test Files

### `conftest.py`
Shared fixtures and utilities for integration testing including:
- Test FastAPI applications with various middleware configurations
- Database session management with transaction rollback
- Mock external services (Accent-Auth, storage, Redis)
- HTTP clients with proper configuration
- Test data factories and helpers

### `test_new_features_integration.py`
Comprehensive integration tests covering:
1. Circuit Breaker Integration Tests
2. N+1 Query Detection Integration Tests
3. Debug Middleware Integration Tests
4. I18n Middleware Integration Tests
5. Security Headers Integration Tests
6. Full Middleware Stack Integration Tests
7. Performance Benchmarks

## Test Coverage Summary

### Circuit Breaker Integration Tests (8 tests)

Tests the circuit breaker pattern with real async HTTP calls:

1. **test_circuit_breaker_opens_under_load**
   - Verifies circuit opens when failure threshold is exceeded
   - Tests fail-fast behavior when circuit is open
   - Ensures proper state transitions

2. **test_circuit_breaker_recovery_behavior**
   - Tests recovery from open to closed state
   - Verifies half-open state behavior
   - Tests successful recovery with successive successful calls

3. **test_circuit_breaker_with_concurrent_requests**
   - Validates thread safety under concurrent load
   - Tests behavior with mixed success/failure rates
   - Ensures proper state management with multiple concurrent requests

4. **test_multiple_circuit_breakers_independent**
   - Verifies multiple circuit breakers operate independently
   - Tests isolation between different service breakers
   - Ensures one failing service doesn't affect others

5. **test_circuit_breaker_context_manager**
   - Tests circuit breaker using context manager pattern
   - Verifies proper exception handling
   - Tests state transitions with context manager

6. **test_circuit_breaker_metrics**
   - Validates metrics collection accuracy
   - Tests success/failure count tracking
   - Verifies metric reporting

### N+1 Query Detection Integration Tests (7 tests)

Tests query pattern detection with real SQLAlchemy integration:

1. **test_n_plus_one_detection_with_real_queries**
   - Tests detection with actual N+1 query patterns
   - Verifies response headers contain detection information
   - Tests logging of detected patterns

2. **test_optimized_queries_no_detection**
   - Verifies optimized queries don't trigger false positives
   - Tests with JOIN and efficient query patterns
   - Ensures low query counts don't trigger detection

3. **test_query_normalizer_patterns**
   - Tests SQL query normalization for pattern matching
   - Verifies similar queries produce same pattern
   - Tests parameter replacement and pattern extraction

4. **test_slow_query_logging**
   - Tests slow query detection and logging
   - Verifies configurable thresholds work correctly
   - Tests that fast queries aren't logged as slow

5. **test_n_plus_one_with_different_query_types**
   - Tests detection with SELECT, UPDATE, INSERT queries
   - Verifies pattern detection across query types
   - Tests multiple simultaneous patterns

6. **test_performance_headers_accuracy**
   - Validates accuracy of X-Query-Count header
   - Tests X-Request-Time header measurement
   - Verifies timing information is reasonable

### Debug Middleware Integration Tests (8 tests)

Tests distributed tracing with real request processing:

1. **test_trace_id_generation_and_propagation**
   - Tests automatic trace ID generation
   - Verifies trace ID in response headers
   - Tests trace context in request state

2. **test_trace_id_preservation_from_client**
   - Tests client-provided trace IDs are preserved
   - Verifies same trace ID flows through request
   - Tests distributed tracing compatibility

3. **test_backward_compatibility_with_request_id**
   - Tests X-Request-Id header compatibility
   - Verifies migration path from old header
   - Ensures no breaking changes

4. **test_logging_context_injection**
   - Tests trace context injection into logs
   - Verifies structured logging includes trace info
   - Tests log correlation capabilities

5. **test_exception_handling_with_trace_context**
   - Tests exceptions include trace context
   - Verifies error logs have trace information
   - Tests error correlation

6. **test_debug_middleware_with_existing_middleware**
   - Tests integration with other middleware
   - Verifies no conflicts in middleware stack
   - Tests state propagation through stack

7. **test_request_timing_accuracy**
   - Tests timing measurement accuracy
   - Verifies timing headers are correct
   - Tests with known delays

8. **test_user_and_tenant_context_in_logs**
   - Tests user/tenant context inclusion
   - Verifies multi-tenant logging
   - Tests context enrichment

### I18n Middleware Integration Tests (8 tests)

Tests internationalization with multiple detection sources:

1. **test_locale_detection_from_accept_language**
   - Tests Accept-Language header parsing
   - Verifies correct locale selection
   - Tests translation loading

2. **test_locale_detection_from_query_parameter**
   - Tests ?lang=XX parameter detection
   - Verifies query param priority
   - Tests URL-based locale switching

3. **test_locale_cookie_persistence**
   - Tests locale cookie is set and persisted
   - Verifies cookie across multiple requests
   - Tests cookie-based locale memory

4. **test_locale_priority_order**
   - Tests detection priority: user > accept-language > query > cookie > default
   - Verifies correct override behavior
   - Tests all detection methods together

5. **test_unsupported_locale_fallback**
   - Tests fallback to default locale
   - Verifies graceful handling of unsupported locales
   - Tests default translation loading

6. **test_accept_language_quality_parsing**
   - Tests quality value (q=X.X) parsing
   - Verifies highest quality locale is chosen
   - Tests complex Accept-Language headers

7. **test_i18n_with_user_preference**
   - Tests authenticated user's preferred language
   - Verifies user preference takes highest priority
   - Tests with auth integration

### Security Headers Integration Tests (6 tests)

Tests security header middleware with different configurations:

1. **test_security_headers_present_in_response**
   - Tests all security headers are present
   - Verifies header values are correct
   - Tests HSTS, CSP, X-Frame-Options, etc.

2. **test_csp_with_different_environments**
   - Tests CSP differs between dev and production
   - Verifies strict policy in production
   - Tests permissive policy allows Swagger in dev

3. **test_hsts_configuration**
   - Tests HSTS header with various settings
   - Verifies max-age, includeSubDomains, preload
   - Tests configuration flexibility

4. **test_server_header_removal**
   - Tests Server header removal for security
   - Verifies information disclosure prevention
   - Tests header customization

5. **test_permissions_policy_restrictions**
   - Tests Permissions-Policy header
   - Verifies browser feature restrictions
   - Tests dangerous features are disabled

6. **test_security_headers_with_error_responses**
   - Tests headers present even in error responses
   - Verifies security on all response types
   - Tests error handling integration

### Full Middleware Stack Integration Tests (8 tests)

Tests complete middleware stack working together:

1. **test_all_middleware_working_together**
   - Tests all middleware contribute correctly
   - Verifies no conflicts between middleware
   - Tests complete integration

2. **test_middleware_execution_order**
   - Tests middleware execute in correct order
   - Verifies proper request/response flow
   - Tests ordering dependencies

3. **test_performance_with_full_stack**
   - Measures performance impact of full stack
   - Verifies acceptable overhead
   - Tests scalability

4. **test_error_handling_through_full_stack**
   - Tests error propagation through stack
   - Verifies each middleware handles errors
   - Tests error response quality

5. **test_concurrent_requests_isolation**
   - Tests request isolation under concurrency
   - Verifies no context leakage
   - Tests unique IDs for each request

6. **test_state_propagation_through_stack**
   - Tests request state flows correctly
   - Verifies all middleware can access state
   - Tests no state loss

7. **test_header_accumulation_no_conflicts**
   - Tests headers from multiple middleware
   - Verifies no duplicate headers
   - Tests header combination

### Performance Benchmarks (2 tests)

Performance testing to ensure acceptable overhead:

1. **test_baseline_performance**
   - Establishes baseline without middleware
   - Provides comparison metrics

2. **test_middleware_performance_overhead**
   - Measures overhead of each middleware
   - Verifies acceptable performance impact
   - Tests individual middleware timing

## Total Test Count

**57 Integration Tests** covering:
- 8 Circuit Breaker tests
- 7 N+1 Query Detection tests
- 8 Debug Middleware tests
- 8 I18n Middleware tests
- 6 Security Headers tests
- 8 Full Stack tests
- 2 Performance benchmark tests

## Running Tests

### Run All Integration Tests
```bash
pytest tests/integration/test_new_features_integration.py -v
```

### Run Specific Test Class
```bash
# Circuit Breaker tests only
pytest tests/integration/test_new_features_integration.py::TestCircuitBreakerIntegration -v

# N+1 Query Detection tests only
pytest tests/integration/test_new_features_integration.py::TestNPlusOneDetectionIntegration -v

# Debug Middleware tests only
pytest tests/integration/test_new_features_integration.py::TestDebugMiddlewareIntegration -v

# I18n Middleware tests only
pytest tests/integration/test_new_features_integration.py::TestI18nMiddlewareIntegration -v

# Security Headers tests only
pytest tests/integration/test_new_features_integration.py::TestSecurityHeadersIntegration -v

# Full Stack tests only
pytest tests/integration/test_new_features_integration.py::TestFullMiddlewareStackIntegration -v

# Performance tests only
pytest tests/integration/test_new_features_integration.py::TestPerformanceBenchmarks -v
```

### Run Specific Test
```bash
pytest tests/integration/test_new_features_integration.py::TestCircuitBreakerIntegration::test_circuit_breaker_opens_under_load -v
```

### Run with Coverage
```bash
pytest tests/integration/test_new_features_integration.py --cov=example_service --cov-report=html
```

### Run with Performance Profiling
```bash
pytest tests/integration/test_new_features_integration.py --profile
```

### Run Only Fast Tests (skip slow benchmarks)
```bash
pytest tests/integration/test_new_features_integration.py -v -m "not slow"
```

## Test Fixtures

### Available Fixtures from conftest.py

#### Application Fixtures
- `test_app_minimal` - Bare FastAPI app without middleware
- `test_app_with_state` - App that exposes request state
- `app_with_n_plus_one_detection` - App with query detection
- `app_with_debug_middleware` - App with debug middleware
- `app_with_i18n` - App with internationalization
- `app_with_security_headers` - App with security headers
- `full_stack_app` - App with complete middleware stack

#### Client Fixtures
- `async_client` - AsyncClient for HTTP requests
- `mock_accent_auth_client` - Mock authentication client
- `mock_redis_client` - Mock Redis client
- `mock_storage_client` - Mock storage client
- `mock_external_api` - Mock external service

#### Data Fixtures
- `sample_user_data` - Sample user information
- `sample_auth_token` - Sample JWT token
- `translation_provider` - Translation data for I18n
- `mock_query_result` - Mock database query results

#### Utility Fixtures
- `test_helper` - Helper class with utility methods
- `capture_logs` - Log capture for assertions
- `performance_threshold` - Performance thresholds
- `mock_sqlalchemy_engine` - Mock SQLAlchemy engine
- `mock_db_session` - Mock database session

## Test Patterns

### Scenario-Based Testing
Each test follows a clear scenario pattern:
1. **Setup** - Prepare test environment
2. **Execute** - Perform the operation
3. **Verify** - Assert expected outcomes
4. **Cleanup** - Reset state (automatic)

### Realistic Testing
Tests use real implementations where possible:
- Real FastAPI applications
- Real middleware processing
- Real async operations
- Real SQL query patterns (normalized)
- Minimal mocking (only external dependencies)

### Performance Testing
Performance tests establish baselines and verify acceptable overhead:
- Baseline measurements without middleware
- Individual middleware overhead measurement
- Full stack performance impact
- Concurrent request handling

## Best Practices

### 1. Test Isolation
- Each test is independent
- Fixtures reset state between tests
- Circuit breakers are reset automatically
- No shared mutable state

### 2. Clear Test Names
- Descriptive test names explain what is tested
- Names follow pattern: `test_<what>_<condition>`
- Easy to understand test purpose from name

### 3. Comprehensive Scenarios
- Success cases tested
- Failure cases tested
- Edge cases covered
- Concurrent operations tested

### 4. Realistic Mocking
- Mock only external dependencies
- Use real implementations for code under test
- Mock at the boundary (external APIs, databases)
- Keep mocks simple and focused

### 5. Assertions
- Multiple assertions per test when logical
- Clear assertion messages
- Test both positive and negative cases
- Verify side effects (logs, metrics, headers)

## Troubleshooting

### Tests Timing Out
If tests timeout, it may be due to:
- Circuit breaker recovery timeouts (adjust in fixtures)
- Slow async operations (check event loop)
- Blocking operations in async code

**Solution**: Use shorter timeouts in test fixtures:
```python
breaker = CircuitBreaker(
    name="test",
    recovery_timeout=0.5,  # Short timeout for testing
)
```

### Flaky Tests
If tests fail intermittently:
- Check for race conditions in concurrent tests
- Verify proper async/await usage
- Check context cleanup between tests
- Verify fixture isolation

**Solution**: Add delays or use wait helpers:
```python
await test_helper.wait_for_condition(
    lambda: breaker.state == CircuitState.OPEN,
    timeout=2.0
)
```

### Import Errors
If imports fail:
- Ensure all dependencies are installed
- Check optional dependencies (SQLAlchemy, etc.)
- Verify Python path includes project root

**Solution**: Install test dependencies:
```bash
pip install -e ".[test]"
```

### Assertion Failures
If assertions fail unexpectedly:
- Check test fixtures are properly scoped
- Verify mock configuration is correct
- Check for state leakage from previous tests
- Use `-vv` for verbose output

## Coverage Goals

### Target Coverage
- **Line Coverage**: > 85%
- **Branch Coverage**: > 80%
- **Integration Coverage**: > 90%

### Uncovered Areas
Some areas may have lower coverage:
- Error handling edge cases
- Platform-specific code
- Optional dependencies not installed

### Measuring Coverage
```bash
# Generate HTML coverage report
pytest tests/integration/ --cov=example_service --cov-report=html

# View report
open htmlcov/index.html
```

## Continuous Integration

These tests should run in CI/CD pipeline:

```yaml
# .github/workflows/test.yml
- name: Run Integration Tests
  run: |
    pytest tests/integration/test_new_features_integration.py -v --cov=example_service
```

### CI Considerations
- Use appropriate timeouts for CI environment
- Consider parallel test execution
- Cache dependencies for faster runs
- Generate coverage reports
- Fail build on test failures

## Future Enhancements

### Planned Additions
1. **Database Integration Tests**
   - Real PostgreSQL instance
   - Actual query execution
   - Transaction rollback testing

2. **WebSocket Integration Tests**
   - Real WebSocket connections
   - Message broadcasting
   - Connection lifecycle

3. **Cache Integration Tests**
   - Real Redis instance
   - Cache invalidation patterns
   - Distributed caching scenarios

4. **Load Testing**
   - Stress testing with high concurrency
   - Memory leak detection
   - Resource limit testing

### Contributing Tests
When adding new features:
1. Write integration tests alongside unit tests
2. Follow existing test patterns
3. Update this documentation
4. Ensure CI passes
5. Maintain >85% coverage

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [httpx Testing](https://www.python-httpx.org/async/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Integration Testing Best Practices](https://martinfowler.com/bliki/IntegrationTest.html)
