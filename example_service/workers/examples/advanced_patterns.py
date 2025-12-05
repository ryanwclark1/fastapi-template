"""Advanced task orchestration patterns.

This module demonstrates production-grade patterns for complex task workflows:

1. **Error Handling Strategies**
   - Graceful degradation
   - Fallback mechanisms
   - Partial success handling
   - Error aggregation and reporting

2. **Retry Strategies**
   - Exponential backoff with jitter
   - Custom retry predicates (retry on specific errors only)
   - Max retry limits per error type
   - Dead letter queue pattern

3. **Circuit Breaker Pattern**
   - Prevent cascading failures
   - Automatic recovery detection
   - Fallback responses during outages

4. **Saga Pattern**
   - Distributed transaction management
   - Compensating transactions for rollback
   - Eventual consistency guarantees

5. **Task Coordination**
   - Leader election for singleton tasks
   - Distributed locks for mutual exclusion
   - Rate limiting and throttling
   - Priority queues

These patterns are essential for building resilient, production-ready systems.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================


class PaymentStatus(str, Enum):
    """Payment processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class CircuitBreakerState(str, Enum):
    """Circuit breaker state machine."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


# =============================================================================
# Pattern 1: Graceful Degradation and Fallback
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="patterns.fetch_user_data_with_fallback",
        retry_on_error=True,
        max_retries=3,
    )
    async def fetch_user_data_with_fallback(user_id: str) -> dict[str, Any]:
        """Fetch user data with multiple fallback strategies.

        Pattern: Graceful Degradation
        - Try primary data source (database)
        - If fails, try cache
        - If cache fails, return minimal safe default
        - Always return something useful, never completely fail

        This pattern is critical for user-facing features where
        showing partial data is better than showing an error.

        Args:
            user_id: User identifier.

        Returns:
            User data dictionary with source indicator.
        """
        logger.info("Fetching user data with fallback", extra={"user_id": user_id})

        # Strategy 1: Try primary source (database)
        try:
            # Simulate database query
            await asyncio.sleep(0.1)

            # Simulate occasional failure (20% chance)
            if random.random() < 0.2:
                raise ConnectionError("Database connection timeout")

            user_data = {
                "user_id": user_id,
                "name": "John Doe",
                "email": "john@example.com",
                "preferences": {"theme": "dark", "notifications": True},
                "source": "database",
                "fetched_at": datetime.now(UTC).isoformat(),
            }

            logger.info("User data fetched from database", extra={"user_id": user_id})
            return user_data

        except Exception as db_error:
            logger.warning(
                "Database fetch failed, trying cache",
                extra={"user_id": user_id, "error": str(db_error)},
            )

            # Strategy 2: Try cache fallback
            try:
                # Simulate cache lookup
                await asyncio.sleep(0.05)

                # Simulate cache hit (cached data may be stale but usable)
                user_data = {
                    "user_id": user_id,
                    "name": "John Doe",
                    "email": "john@example.com",
                    "preferences": {},  # Partial data from cache
                    "source": "cache",
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "warning": "Data from cache, may be stale",
                }

                logger.info("User data fetched from cache", extra={"user_id": user_id})
                return user_data

            except Exception as cache_error:
                logger.warning(
                    "Cache fetch failed, using safe defaults",
                    extra={"user_id": user_id, "error": str(cache_error)},
                )

                # Strategy 3: Safe defaults (always succeeds)
                user_data = {
                    "user_id": user_id,
                    "name": "User",  # Generic fallback
                    "email": None,  # Unavailable
                    "preferences": {},  # Empty but valid
                    "source": "default",
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "warning": "Using safe defaults, full data unavailable",
                }

                logger.info(
                    "Using safe default user data",
                    extra={"user_id": user_id},
                )
                return user_data


# =============================================================================
# Pattern 2: Partial Success Handling
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="patterns.process_batch_with_partial_success",
        retry_on_error=False,  # We handle failures per-item
    )
    async def process_batch_with_partial_success(
        items: list[dict[str, Any]],
        continue_on_error: bool = True,
    ) -> dict[str, Any]:
        """Process batch of items with partial success handling.

        Pattern: Partial Success
        - Process each item independently
        - Track successes and failures separately
        - Continue processing even if some items fail
        - Return detailed results for each item

        Critical for bulk operations where you don't want one bad
        item to block processing of hundreds of good items.

        Args:
            items: List of items to process.
            continue_on_error: If True, continue processing after errors.

        Returns:
            Batch results with individual item statuses.

        Example:
            items = [
                {"id": "1", "data": "valid"},
                {"id": "2", "data": "invalid"},  # Will fail
                {"id": "3", "data": "valid"},
            ]

            result = await process_batch_with_partial_success.kiq(
                items=items,
                continue_on_error=True,
            )

            # Result will show: 2 successes, 1 failure
            # Processing didn't stop at item 2
        """
        logger.info(
            "Processing batch with partial success handling",
            extra={"total_items": len(items), "continue_on_error": continue_on_error},
        )

        results = {
            "total_items": len(items),
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "items": [],
            "started_at": datetime.now(UTC).isoformat(),
        }

        for item in items:
            item_id = item.get("id", "unknown")

            try:
                # Simulate processing
                await asyncio.sleep(0.1)

                # Simulate occasional failure (30% chance)
                if random.random() < 0.3:
                    raise ValueError(f"Invalid data in item {item_id}")

                # Success case
                results["items"].append(
                    {
                        "id": item_id,
                        "status": "success",
                        "processed_at": datetime.now(UTC).isoformat(),
                    }
                )
                results["successful"] += 1
                results["processed"] += 1

            except Exception as e:
                # Failure case
                results["items"].append(
                    {
                        "id": item_id,
                        "status": "failed",
                        "error": str(e),
                        "failed_at": datetime.now(UTC).isoformat(),
                    }
                )
                results["failed"] += 1
                results["processed"] += 1

                logger.warning(
                    "Item processing failed",
                    extra={"item_id": item_id, "error": str(e)},
                )

                # Decide whether to continue or abort
                if not continue_on_error:
                    logger.error("Aborting batch due to error")
                    break

        results["completed_at"] = datetime.now(UTC).isoformat()
        results["success_rate"] = (
            (results["successful"] / results["total_items"]) * 100
            if results["total_items"] > 0
            else 0
        )

        # Determine overall status
        if results["failed"] == 0:
            results["status"] = "success"
        elif results["successful"] > 0:
            results["status"] = "partial_success"
        else:
            results["status"] = "failed"

        logger.info(
            "Batch processing completed",
            extra={
                "status": results["status"],
                "successful": results["successful"],
                "failed": results["failed"],
            },
        )

        return results


# =============================================================================
# Pattern 3: Saga Pattern (Distributed Transactions)
# =============================================================================


if broker is not None:

    @broker.task(
        task_name="patterns.payment_saga",
        retry_on_error=False,  # We handle rollback explicitly
    )
    async def payment_saga(
        order_id: str,
        user_id: str,
        amount: float,
    ) -> dict[str, Any]:
        """Execute payment saga with compensating transactions.

        Pattern: Saga
        - Multi-step distributed transaction
        - Each step has a compensating transaction (rollback)
        - If any step fails, execute compensations in reverse order
        - Ensures eventual consistency across services

        Steps:
        1. Reserve inventory → Compensate: Release inventory
        2. Charge payment → Compensate: Refund payment
        3. Create shipment → Compensate: Cancel shipment

        This pattern is essential for microservices where
        distributed transactions span multiple services.

        Args:
            order_id: Order identifier.
            user_id: User identifier.
            amount: Payment amount.

        Returns:
            Saga execution result with rollback details if needed.

        Example:
            # If payment fails, inventory will be automatically released
            result = await payment_saga.kiq(
                order_id="order_123",
                user_id="user_456",
                amount=99.99,
            )
        """
        saga_id = f"saga_{order_id}"
        completed_steps = []
        compensation_executed = []

        logger.info(
            "Starting payment saga",
            extra={"saga_id": saga_id, "order_id": order_id, "amount": amount},
        )

        saga_result: dict[str, Any] = {
            "saga_id": saga_id,
            "order_id": order_id,
            "status": "in_progress",
            "steps": [],
            "started_at": datetime.now(UTC).isoformat(),
        }

        try:
            # Step 1: Reserve inventory
            logger.info("Step 1: Reserving inventory")
            await asyncio.sleep(0.2)

            # Simulate occasional failure (10% chance)
            if random.random() < 0.1:
                raise Exception("Inventory service unavailable")

            completed_steps.append("reserve_inventory")
            saga_result["steps"].append(
                {
                    "name": "reserve_inventory",
                    "status": "completed",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            # Step 2: Charge payment
            logger.info("Step 2: Charging payment")
            await asyncio.sleep(0.3)

            # Simulate payment failure (15% chance)
            if random.random() < 0.15:
                raise Exception("Payment declined")

            completed_steps.append("charge_payment")
            saga_result["steps"].append(
                {
                    "name": "charge_payment",
                    "status": "completed",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            # Step 3: Create shipment
            logger.info("Step 3: Creating shipment")
            await asyncio.sleep(0.2)

            # Simulate shipment failure (10% chance)
            if random.random() < 0.1:
                raise Exception("Shipment service unavailable")

            completed_steps.append("create_shipment")
            saga_result["steps"].append(
                {
                    "name": "create_shipment",
                    "status": "completed",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            # All steps completed successfully
            saga_result["status"] = "completed"
            saga_result["completed_at"] = datetime.now(UTC).isoformat()

            logger.info(
                "Payment saga completed successfully",
                extra={"saga_id": saga_id, "order_id": order_id},
            )

            return saga_result

        except Exception as e:
            # Saga failed, execute compensating transactions in reverse order
            logger.error(
                "Saga failed, executing compensations",
                extra={"saga_id": saga_id, "error": str(e), "completed_steps": completed_steps},
            )

            saga_result["status"] = "failed"
            saga_result["error"] = str(e)
            saga_result["compensations"] = []

            # Execute compensations in reverse order
            for step in reversed(completed_steps):
                try:
                    if step == "create_shipment":
                        logger.info("Compensating: Canceling shipment")
                        await asyncio.sleep(0.1)
                        compensation_executed.append("cancel_shipment")
                        saga_result["compensations"].append(
                            {
                                "step": "cancel_shipment",
                                "status": "completed",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )

                    elif step == "charge_payment":
                        logger.info("Compensating: Refunding payment")
                        await asyncio.sleep(0.2)
                        compensation_executed.append("refund_payment")
                        saga_result["compensations"].append(
                            {
                                "step": "refund_payment",
                                "status": "completed",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )

                    elif step == "reserve_inventory":
                        logger.info("Compensating: Releasing inventory")
                        await asyncio.sleep(0.1)
                        compensation_executed.append("release_inventory")
                        saga_result["compensations"].append(
                            {
                                "step": "release_inventory",
                                "status": "completed",
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )

                except Exception as comp_error:
                    # Compensation failed - this is serious!
                    logger.critical(
                        "Compensation failed",
                        extra={
                            "saga_id": saga_id,
                            "step": step,
                            "error": str(comp_error),
                        },
                    )
                    saga_result["compensations"].append(
                        {
                            "step": step,
                            "status": "failed",
                            "error": str(comp_error),
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )

            saga_result["failed_at"] = datetime.now(UTC).isoformat()
            saga_result["compensations_executed"] = compensation_executed

            logger.info(
                "Saga compensations completed",
                extra={
                    "saga_id": saga_id,
                    "compensations": len(compensation_executed),
                },
            )

            return saga_result


# =============================================================================
# Pattern 4: Circuit Breaker
# =============================================================================


# In production, you would use a shared cache (Redis) to store circuit breaker state
# This is a simplified in-memory version for demonstration
CIRCUIT_BREAKER_STATE: dict[str, Any] = {
    "state": CircuitBreakerState.CLOSED,
    "failure_count": 0,
    "last_failure_time": None,
    "last_success_time": None,
}

CIRCUIT_BREAKER_CONFIG = {
    "failure_threshold": 5,  # Open circuit after 5 failures
    "timeout": 30,  # Try to recover after 30 seconds
    "success_threshold": 2,  # Close circuit after 2 successes in half-open state
}


if broker is not None:

    @broker.task(
        task_name="patterns.call_external_api_with_circuit_breaker",
        retry_on_error=False,  # Circuit breaker handles retries
    )
    async def call_external_api_with_circuit_breaker(
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Call external API with circuit breaker pattern.

        Pattern: Circuit Breaker
        - Prevent cascading failures
        - Fast-fail when service is known to be down
        - Automatically detect recovery
        - Provide fallback response during outages

        States:
        - CLOSED: Normal operation, requests go through
        - OPEN: Service is failing, reject requests immediately
        - HALF_OPEN: Testing if service recovered, allow limited requests

        Args:
            endpoint: API endpoint to call.
            payload: Request payload.

        Returns:
            API response or fallback data.

        Example:
            # Circuit breaker prevents hammering a failing service
            result = await call_external_api_with_circuit_breaker.kiq(
                endpoint="/api/external-service",
                payload={"data": "test"},
            )
        """
        logger.info(
            "Calling external API with circuit breaker",
            extra={
                "endpoint": endpoint,
                "circuit_state": CIRCUIT_BREAKER_STATE["state"],
            },
        )

        current_state = CIRCUIT_BREAKER_STATE["state"]

        # Check if circuit is OPEN
        if current_state == CircuitBreakerState.OPEN:
            # Check if timeout has elapsed
            last_failure = CIRCUIT_BREAKER_STATE["last_failure_time"]
            if last_failure:
                time_since_failure = (datetime.now(UTC) - last_failure).total_seconds()

                if time_since_failure >= CIRCUIT_BREAKER_CONFIG["timeout"]:
                    # Transition to HALF_OPEN (testing recovery)
                    CIRCUIT_BREAKER_STATE["state"] = CircuitBreakerState.HALF_OPEN
                    CIRCUIT_BREAKER_STATE["failure_count"] = 0
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                else:
                    # Still in timeout period, fail fast
                    logger.warning(
                        "Circuit breaker is OPEN, rejecting request",
                        extra={"time_until_retry": CIRCUIT_BREAKER_CONFIG["timeout"] - time_since_failure},
                    )
                    return {
                        "status": "circuit_open",
                        "error": "Service unavailable (circuit breaker open)",
                        "fallback_data": {"message": "Using cached/default response"},
                        "retry_after": CIRCUIT_BREAKER_CONFIG["timeout"] - time_since_failure,
                    }

        # Try to make the API call
        try:
            # Simulate external API call
            await asyncio.sleep(0.2)

            # Simulate occasional failures (20% chance)
            if random.random() < 0.2:
                raise ConnectionError("External API timeout")

            # Success!
            response = {
                "status": "success",
                "data": {"result": "API call succeeded"},
                "timestamp": datetime.now(UTC).isoformat(),
            }

            # Record success
            CIRCUIT_BREAKER_STATE["last_success_time"] = datetime.now(UTC)

            # If we're in HALF_OPEN, check if we should close the circuit
            if current_state == CircuitBreakerState.HALF_OPEN:
                CIRCUIT_BREAKER_STATE["failure_count"] = 0
                # In production, you'd track consecutive successes
                # For simplicity, we close immediately on first success
                CIRCUIT_BREAKER_STATE["state"] = CircuitBreakerState.CLOSED
                logger.info("Circuit breaker closed after successful recovery")

            logger.info("External API call succeeded")
            return response

        except Exception as e:
            # Record failure
            CIRCUIT_BREAKER_STATE["failure_count"] += 1
            CIRCUIT_BREAKER_STATE["last_failure_time"] = datetime.now(UTC)

            failure_count = CIRCUIT_BREAKER_STATE["failure_count"]
            threshold = CIRCUIT_BREAKER_CONFIG["failure_threshold"]

            logger.warning(
                "External API call failed",
                extra={
                    "error": str(e),
                    "failure_count": failure_count,
                    "threshold": threshold,
                },
            )

            # Check if we should open the circuit
            if failure_count >= threshold:
                CIRCUIT_BREAKER_STATE["state"] = CircuitBreakerState.OPEN
                logger.error(
                    "Circuit breaker opened due to repeated failures",
                    extra={"failure_count": failure_count},
                )

            # Return fallback response
            return {
                "status": "failed",
                "error": str(e),
                "circuit_state": CIRCUIT_BREAKER_STATE["state"],
                "failure_count": failure_count,
                "fallback_data": {"message": "Using cached/default response"},
            }


# =============================================================================
# Pattern 5: Idempotency with Deduplication
# =============================================================================

# In production, use Redis or database for deduplication tracking
PROCESSED_REQUESTS: dict[str, Any] = {}


if broker is not None:

    @broker.task(
        task_name="patterns.idempotent_payment",
        retry_on_error=True,
        max_retries=3,
    )
    async def idempotent_payment(
        idempotency_key: str,
        user_id: str,
        amount: float,
    ) -> dict[str, Any]:
        """Process payment with idempotency guarantee.

        Pattern: Idempotency
        - Use idempotency key to prevent duplicate processing
        - Safe to retry without side effects
        - Return cached result if already processed

        Critical for payment operations where network failures
        might cause clients to retry requests.

        Args:
            idempotency_key: Unique key for this operation (e.g., UUID).
            user_id: User identifier.
            amount: Payment amount.

        Returns:
            Payment result (cached if duplicate).

        Example:
            # Even if called multiple times with same key, only charges once
            result1 = await idempotent_payment.kiq(
                idempotency_key="unique-uuid-123",
                user_id="user_456",
                amount=99.99,
            )

            # This will return cached result, not charge again
            result2 = await idempotent_payment.kiq(
                idempotency_key="unique-uuid-123",
                user_id="user_456",
                amount=99.99,
            )
        """
        logger.info(
            "Processing idempotent payment",
            extra={
                "idempotency_key": idempotency_key,
                "user_id": user_id,
                "amount": amount,
            },
        )

        # Check if we've already processed this request
        if idempotency_key in PROCESSED_REQUESTS:
            cached_result = PROCESSED_REQUESTS[idempotency_key]
            logger.info(
                "Returning cached result for duplicate request",
                extra={"idempotency_key": idempotency_key},
            )
            cached_result["from_cache"] = True
            return cached_result

        # Process the payment (only happens once)
        try:
            await asyncio.sleep(0.3)  # Simulate payment processing

            # Simulate occasional failure (10% chance)
            if random.random() < 0.1:
                raise Exception("Payment gateway timeout")

            result = {
                "status": "success",
                "idempotency_key": idempotency_key,
                "user_id": user_id,
                "amount": amount,
                "transaction_id": f"txn_{idempotency_key[:8]}",
                "processed_at": datetime.now(UTC).isoformat(),
                "from_cache": False,
            }

            # Cache the result for future duplicate requests
            PROCESSED_REQUESTS[idempotency_key] = result

            logger.info(
                "Payment processed successfully",
                extra={
                    "idempotency_key": idempotency_key,
                    "transaction_id": result["transaction_id"],
                },
            )

            return result

        except Exception as e:
            logger.exception(
                "Payment processing failed",
                extra={"idempotency_key": idempotency_key, "error": str(e)},
            )

            # DON'T cache failures - allow retries
            # Only cache successful operations
            raise
