"""Helper functions for tracking business and operational metrics."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import time
from typing import TYPE_CHECKING, Any

from example_service.infra.metrics import business

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


# ============================================================================
# Error Tracking
# ============================================================================


def track_error(
    error_type: str,
    endpoint: str,
    status_code: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """Track an error occurrence.

    Args:
        error_type: Type of error (e.g., 'validation', 'not_found', 'rate_limit')
        endpoint: API endpoint where error occurred
        status_code: HTTP status code
        extra: Additional context for logging

    Example:
            track_error("validation", "/api/v1/users", 422, {"field": "email"})
    """
    business.errors_total.labels(
        error_type=error_type,
        endpoint=endpoint,
        status_code=str(status_code),
    ).inc()

    logger.debug(
        f"Tracked error: {error_type}",
        extra={"endpoint": endpoint, "status_code": status_code, **(extra or {})},
    )


def track_validation_error(endpoint: str, field: str) -> None:
    """Track a validation error for a specific field.

    Args:
        endpoint: API endpoint where validation failed
        field: Field that failed validation

    Example:
            track_validation_error("/api/v1/users", "email")
    """
    business.validation_errors_total.labels(
        endpoint=endpoint,
        field=field,
    ).inc()


def track_unhandled_exception(exception_type: str, endpoint: str) -> None:
    """Track an unhandled exception.

    Args:
        exception_type: Type of exception (e.g., 'ValueError', 'KeyError')
        endpoint: API endpoint where exception occurred

    Example:
            track_unhandled_exception("ValueError", "/api/v1/data")
    """
    business.exceptions_unhandled_total.labels(
        exception_type=exception_type,
        endpoint=endpoint,
    ).inc()


# ============================================================================
# Rate Limiting Tracking
# ============================================================================


def track_rate_limit_hit(endpoint: str, limit_type: str = "ip") -> None:
    """Track when rate limit is hit.

    Args:
        endpoint: API endpoint where rate limit was hit
        limit_type: Type of rate limit (ip, user, api_key)

    Example:
            track_rate_limit_hit("/api/v1/data", "user")
    """
    business.rate_limit_hits_total.labels(
        endpoint=endpoint,
        limit_type=limit_type,
    ).inc()


def track_rate_limit_check(endpoint: str, allowed: bool) -> None:
    """Track a rate limit check.

    Args:
        endpoint: API endpoint being checked
        allowed: Whether the request was allowed

    Example:
            track_rate_limit_check("/api/v1/data", allowed=True)
    """
    result = "allowed" if allowed else "denied"
    business.rate_limit_checks_total.labels(
        endpoint=endpoint,
        result=result,
    ).inc()


def update_rate_limit_remaining(key: str, endpoint: str, remaining: int) -> None:
    """Update remaining rate limit tokens gauge.

    Args:
        key: Rate limit key (e.g., user ID, IP address)
        endpoint: API endpoint
        remaining: Number of remaining tokens

    Example:
            update_rate_limit_remaining("user:123", "/api/v1/data", 47)
    """
    business.rate_limit_remaining.labels(
        key=key,
        endpoint=endpoint,
    ).set(remaining)


def update_rate_limiter_protection_status(status: str) -> None:
    """Update rate limiter protection status gauge.

    Args:
        status: Protection status ('active', 'degraded', 'disabled')

    Example:
            update_rate_limiter_protection_status("degraded")
    """
    status_map = {"active": 1.0, "degraded": 0.5, "disabled": 0.0}
    business.rate_limiter_protection_status.set(status_map.get(status, 0.0))


def track_rate_limiter_state_transition(from_state: str, to_state: str) -> None:
    """Track rate limiter state transition.

    Args:
        from_state: Previous state
        to_state: New state

    Example:
            track_rate_limiter_state_transition("active", "degraded")
    """
    business.rate_limiter_state_transitions_total.labels(
        from_state=from_state,
        to_state=to_state,
    ).inc()


def track_rate_limiter_redis_error(error_type: str) -> None:
    """Track Redis error during rate limit check.

    Args:
        error_type: Type of error ('timeout', 'connection', 'auth', 'other')

    Example:
            track_rate_limiter_redis_error("connection")
    """
    business.rate_limiter_redis_errors_total.labels(error_type=error_type).inc()


# ============================================================================
# Circuit Breaker Tracking
# ============================================================================


def update_circuit_breaker_state(circuit_name: str, state: str) -> None:
    """Update circuit breaker state gauge.

    Args:
        circuit_name: Name of the circuit breaker
        state: Current state ('closed', 'half_open', 'open')

    Example:
            update_circuit_breaker_state("auth_service", "open")
    """
    state_map = {"closed": 0, "half_open": 1, "open": 2}
    business.circuit_breaker_state.labels(circuit_name=circuit_name).set(state_map.get(state, 0))


def track_circuit_breaker_failure(circuit_name: str) -> None:
    """Track a circuit breaker failure.

    Args:
        circuit_name: Name of the circuit breaker

    Example:
            track_circuit_breaker_failure("auth_service")
    """
    business.circuit_breaker_failures_total.labels(circuit_name=circuit_name).inc()


def track_circuit_breaker_success(circuit_name: str) -> None:
    """Track a circuit breaker success.

    Args:
        circuit_name: Name of the circuit breaker

    Example:
            track_circuit_breaker_success("auth_service")
    """
    business.circuit_breaker_successes_total.labels(circuit_name=circuit_name).inc()


def track_circuit_breaker_state_change(circuit_name: str, from_state: str, to_state: str) -> None:
    """Track a circuit breaker state change.

    Args:
        circuit_name: Name of the circuit breaker
        from_state: Previous state
        to_state: New state

    Example:
            track_circuit_breaker_state_change("auth_service", "closed", "open")
    """
    business.circuit_breaker_state_changes_total.labels(
        circuit_name=circuit_name,
        from_state=from_state,
        to_state=to_state,
    ).inc()


def track_circuit_breaker_rejected(circuit_name: str) -> None:
    """Track a request rejected by circuit breaker.

    Args:
        circuit_name: Name of the circuit breaker

    Example:
            track_circuit_breaker_rejected("auth_service")
    """
    business.circuit_breaker_rejected_total.labels(circuit_name=circuit_name).inc()


# ============================================================================
# Retry Tracking
# ============================================================================


def track_retry_attempt(operation: str, attempt_number: int) -> None:
    """Track a retry attempt.

    Args:
        operation: Name of the operation being retried
        attempt_number: Current attempt number (1-indexed)

    Example:
            track_retry_attempt("fetch_user_data", 2)
    """
    business.retry_attempts_total.labels(
        operation=operation,
        attempt_number=str(attempt_number),
    ).inc()


def track_retry_exhausted(operation: str) -> None:
    """Track when all retry attempts are exhausted.

    Args:
        operation: Name of the operation that failed

    Example:
            track_retry_exhausted("fetch_user_data")
    """
    business.retry_exhausted_total.labels(operation=operation).inc()


def track_retry_success(operation: str, attempts_needed: int) -> None:
    """Track successful operation after retries.

    Args:
        operation: Name of the operation
        attempts_needed: Number of attempts needed to succeed

    Example:
            track_retry_success("fetch_user_data", 3)
    """
    business.retry_success_after_failure_total.labels(
        operation=operation,
        attempts_needed=str(attempts_needed),
    ).inc()


# ============================================================================
# API Usage Tracking
# ============================================================================


def track_api_call(endpoint: str, method: str, is_authenticated: bool) -> None:
    """Track an API endpoint call.

    Args:
        endpoint: API endpoint path
        method: HTTP method
        is_authenticated: Whether user is authenticated

    Example:
            track_api_call("/api/v1/users", "GET", True)
    """
    user_type = "authenticated" if is_authenticated else "anonymous"
    business.api_endpoint_calls_total.labels(
        endpoint=endpoint,
        method=method,
        user_type=user_type,
    ).inc()


def track_response_size(endpoint: str, method: str, size_bytes: int) -> None:
    """Track API response size.

    Args:
        endpoint: API endpoint path
        method: HTTP method
        size_bytes: Response size in bytes

    Example:
            track_response_size("/api/v1/users", "GET", 1024)
    """
    business.api_response_size_bytes.labels(
        endpoint=endpoint,
        method=method,
    ).observe(size_bytes)


def track_request_size(endpoint: str, method: str, size_bytes: int) -> None:
    """Track API request size.

    Args:
        endpoint: API endpoint path
        method: HTTP method
        size_bytes: Request size in bytes

    Example:
            track_request_size("/api/v1/users", "POST", 512)
    """
    business.api_request_size_bytes.labels(
        endpoint=endpoint,
        method=method,
    ).observe(size_bytes)


# ============================================================================
# Authentication Tracking
# ============================================================================


def track_auth_attempt(method: str, success: bool) -> None:
    """Track an authentication attempt.

    Args:
        method: Authentication method (token, api_key, oauth)
        success: Whether authentication succeeded

    Example:
            track_auth_attempt("token", True)
    """
    result = "success" if success else "failure"
    business.auth_attempts_total.labels(
        method=method,
        result=result,
    ).inc()


def track_token_validation(result: str) -> None:
    """Track token validation result.

    Args:
        result: Validation result (valid, invalid, expired)

    Example:
            track_token_validation("valid")
    """
    business.auth_token_validations_total.labels(result=result).inc()


def track_token_cache(is_hit: bool) -> None:
    """Track auth token cache hit/miss.

    Args:
        is_hit: Whether cache was hit

    Example:
            track_token_cache(True)
    """
    result = "hit" if is_hit else "miss"
    business.auth_token_cache_hits_total.labels(result=result).inc()


def track_permission_check(permission: str, allowed: bool) -> None:
    """Track permission check.

    Args:
        permission: Permission being checked
        allowed: Whether permission was granted

    Example:
            track_permission_check("admin", False)
    """
    result = "allowed" if allowed else "denied"
    business.permission_checks_total.labels(
        permission=permission,
        result=result,
    ).inc()


# ============================================================================
# External Service Tracking
# ============================================================================


@asynccontextmanager
async def track_external_service_call(service_name: str, endpoint: str) -> AsyncIterator[None]:
    """Context manager to track external service call with timing.

    Args:
        service_name: Name of the external service
        endpoint: Service endpoint being called

    Example:
            async with track_external_service_call("auth_service", "/verify"):
            result = await httpx.get("https://auth.example.com/verify")
    """
    start_time = time.time()
    status = "success"

    try:
        yield
    except Exception as e:
        status = "error"
        error_type = type(e).__name__
        business.external_service_errors_total.labels(
            service_name=service_name,
            error_type=error_type,
        ).inc()
        raise
    finally:
        duration = time.time() - start_time

        business.external_service_calls_total.labels(
            service_name=service_name,
            endpoint=endpoint,
            status=status,
        ).inc()

        business.external_service_duration_seconds.labels(
            service_name=service_name,
            endpoint=endpoint,
        ).observe(duration)


def track_external_service_timeout(service_name: str) -> None:
    """Track external service timeout.

    Args:
        service_name: Name of the external service

    Example:
            track_external_service_timeout("auth_service")
    """
    business.external_service_timeouts_total.labels(service_name=service_name).inc()


# ============================================================================
# Business Domain Tracking
# ============================================================================


def track_user_action(action_type: str, is_authenticated: bool) -> None:
    """Track user action.

    Args:
        action_type: Type of action (create, update, delete, view)
        is_authenticated: Whether user is authenticated

    Example:
            track_user_action("create", True)
    """
    user_type = "authenticated" if is_authenticated else "anonymous"
    business.user_actions_total.labels(
        action_type=action_type,
        user_type=user_type,
    ).inc()


def track_feature_usage(feature_name: str, is_authenticated: bool) -> None:
    """Track feature usage.

    Args:
        feature_name: Name of the feature
        is_authenticated: Whether user is authenticated

    Example:
            track_feature_usage("export_data", True)
    """
    user_type = "authenticated" if is_authenticated else "anonymous"
    business.feature_usage_total.labels(
        feature_name=feature_name,
        user_type=user_type,
    ).inc()


def track_slow_query(operation: str) -> None:
    """Track slow database query (>1s).

    Args:
        operation: Database operation

    Example:
            track_slow_query("select_users")
    """
    business.slow_queries_total.labels(operation=operation).inc()


def track_slow_request(endpoint: str, method: str) -> None:
    """Track slow HTTP request (>5s).

    Args:
        endpoint: API endpoint
        method: HTTP method

    Example:
            track_slow_request("/api/v1/reports", "GET")
    """
    business.slow_requests_total.labels(
        endpoint=endpoint,
        method=method,
    ).inc()


# ============================================================================
# Dependency Health Tracking
# ============================================================================


def update_dependency_health(dependency_name: str, dependency_type: str, is_healthy: bool) -> None:
    """Update dependency health status.

    Args:
        dependency_name: Name of the dependency
        dependency_type: Type of dependency (database, cache, queue, api)
        is_healthy: Whether dependency is healthy

    Example:
            update_dependency_health("postgres", "database", True)
    """
    health_value = 1 if is_healthy else 0
    business.dependency_health.labels(
        dependency_name=dependency_name,
        dependency_type=dependency_type,
    ).set(health_value)


@asynccontextmanager
async def track_dependency_check(dependency_name: str) -> AsyncIterator[None]:
    """Context manager to track dependency health check duration.

    Args:
        dependency_name: Name of the dependency

    Example:
            async with track_dependency_check("postgres"):
            await db.execute("SELECT 1")
    """
    start_time = time.time()

    try:
        yield
    finally:
        duration = time.time() - start_time
        business.dependency_check_duration_seconds.labels(dependency_name=dependency_name).observe(
            duration,
        )
