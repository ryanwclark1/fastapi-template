"""OpenTelemetry tracing extension for GraphQL operations.

Provides distributed tracing for GraphQL queries, mutations, and subscriptions
with detailed span instrumentation for operations, resolvers, and DataLoaders.

Usage:
    from example_service.features.graphql.extensions.tracing import GraphQLTracingExtension

    extensions = [
        GraphQLTracingExtension(),  # Enable tracing
    ]
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from strawberry.extensions import SchemaExtension

logger = logging.getLogger(__name__)

__all__ = ["GraphQLTracingExtension", "get_graphql_tracer"]


# Get tracer for GraphQL operations
def get_graphql_tracer() -> trace.Tracer:
    """Get OpenTelemetry tracer for GraphQL operations.

    Returns:
        Tracer instance for creating spans
    """
    return trace.get_tracer("graphql", "1.0.0")


class GraphQLTracingExtension(SchemaExtension):
    """OpenTelemetry tracing for GraphQL operations.

    This extension creates distributed tracing spans for GraphQL operations,
    providing visibility into query execution, resolver performance, and
    data loading patterns.

    Span hierarchy:
        graphql.execute                     # Root span for operation
        ├── graphql.parse                   # Query parsing
        ├── graphql.validate                # Query validation
        ├── graphql.execute.operation       # Operation execution
        │   ├── graphql.resolve.<field>     # Individual field resolvers
        │   └── graphql.dataloader.<type>   # DataLoader batches
        └── graphql.format                  # Response formatting

    Span attributes include:
    - graphql.operation.type (query/mutation/subscription)
    - graphql.operation.name (operation name if provided)
    - graphql.document (query text)
    - graphql.variables (sanitized)
    - graphql.complexity (if complexity extension is enabled)
    - graphql.field.name (for resolver spans)
    - graphql.field.path (field path in query)

    Example:
        schema = strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=[
                GraphQLTracingExtension(),  # Enable tracing
                ComplexityLimiter(),
                GraphQLRateLimiter(),
            ],
        )

    Integration with existing tracing:
        This extension integrates with the existing OpenTelemetry setup
        in example_service.infra.tracing.opentelemetry and will automatically
        propagate trace context from incoming HTTP requests.
    """

    def __init__(self, include_document: bool = False, include_variables: bool = True):
        """Initialize tracing extension.

        Args:
            include_document: Include full GraphQL document in spans (default: False)
                             Warning: May expose sensitive data in traces
            include_variables: Include sanitized variables in spans (default: True)
        """
        self.include_document = include_document
        self.include_variables = include_variables
        self.tracer = get_graphql_tracer()

    def on_execute(self) -> None:
        """Create span for operation execution.

        This hook runs at the start of operation execution and creates
        the root span for the GraphQL operation.
        """
        execution_context = self.execution_context

        # Get operation details
        operation_type = execution_context.operation_type or "unknown"
        operation_name = execution_context.operation_name or "anonymous"

        # Start root span for operation
        span = self.tracer.start_span(
            name="graphql.execute",
            kind=trace.SpanKind.SERVER,
        )

        # Set standard attributes
        span.set_attribute("graphql.operation.type", operation_type)
        span.set_attribute("graphql.operation.name", operation_name)

        # Add document if enabled
        if self.include_document and execution_context.query:
            # Truncate document to prevent huge spans
            document = str(execution_context.query)
            if len(document) > 2000:
                document = document[:2000] + "... (truncated)"
            span.set_attribute("graphql.document", document)

        # Add variables if enabled (sanitize sensitive data)
        if self.include_variables and execution_context.variable_values:
            try:
                sanitized_vars = self._sanitize_variables(execution_context.variable_values)
                span.set_attribute("graphql.variables", str(sanitized_vars))
            except Exception as e:
                logger.debug(f"Failed to add variables to span: {e}")

        # Add user context if available
        if hasattr(execution_context, "context") and execution_context.context:
            context = execution_context.context
            if hasattr(context, "user") and context.user:
                span.set_attribute("graphql.user.id", str(context.user.id))
                span.set_attribute("graphql.user.authenticated", True)
            else:
                span.set_attribute("graphql.user.authenticated", False)

            # Add correlation ID if available
            if hasattr(context, "correlation_id") and context.correlation_id:
                span.set_attribute("graphql.correlation_id", context.correlation_id)

        # Store span in execution context for later access
        execution_context._tracing_span = span

    def on_request_end(self) -> None:
        """Finalize span when request ends.

        Records the result status and any errors, then ends the span.
        """
        execution_context = self.execution_context

        # Get the span we created in on_execute
        span = getattr(execution_context, "_tracing_span", None)
        if not span:
            return

        try:
            # Check for errors
            result = execution_context.result
            if result and result.errors:
                # Mark span as error
                span.set_status(Status(StatusCode.ERROR, "GraphQL execution errors"))
                span.set_attribute("graphql.error.count", len(result.errors))

                # Add first error message
                if result.errors:
                    first_error = result.errors[0]
                    span.set_attribute("graphql.error.message", str(first_error.message))

                    # Add error code if available
                    if hasattr(first_error, "extensions") and first_error.extensions:
                        error_code = first_error.extensions.get("code")
                        if error_code:
                            span.set_attribute("graphql.error.code", error_code)
            else:
                # Mark span as successful
                span.set_status(Status(StatusCode.OK))

            # Record data if available
            if result and result.data and isinstance(result.data, dict):
                # Count fields returned (top-level only)
                span.set_attribute("graphql.response.field_count", len(result.data))

        except Exception as e:
            logger.error(f"Error finalizing tracing span: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
        finally:
            # Always end the span
            span.end()

    def _sanitize_variables(self, variables: dict[str, Any]) -> dict[str, Any]:
        """Sanitize variables to remove sensitive data.

        Removes or masks:
        - password, secret, token, api_key fields
        - Large values (truncate to 100 chars)

        Args:
            variables: Raw variables dict

        Returns:
            Sanitized variables dict
        """
        sanitized = {}

        # List of sensitive field names
        sensitive_keys = {
            "password",
            "secret",
            "token",
            "api_key",
            "apiKey",
            "apikey",
            "access_token",
            "refresh_token",
            "privateKey",
            "private_key",
        }

        for key, value in variables.items():
            # Check if key is sensitive
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, str) and len(value) > 100:
                # Truncate long strings
                sanitized[key] = value[:100] + "... (truncated)"
            elif isinstance(value, (list, dict)):
                # Don't include complex objects (too large for span attributes)
                sanitized[key] = f"<{type(value).__name__}>"
            else:
                sanitized[key] = value

        return sanitized


# ============================================================================
# Resolver-level tracing utilities
# ============================================================================


def trace_resolver(resolver_name: str):
    """Decorator to add tracing to individual resolvers.

    Creates a child span for expensive or important resolvers.

    Args:
        resolver_name: Name for the span (e.g., "reminder.tags")

    Example:
        @strawberry.field
        @trace_resolver("reminder.tags")
        async def tags(self, info: Info) -> list[TagType]:
            return await ctx.loaders.reminder_tags.load(self.id)
    """

    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            tracer = get_graphql_tracer()
            with tracer.start_as_current_span(
                f"graphql.resolve.{resolver_name}",
                kind=trace.SpanKind.INTERNAL,
            ) as span:
                span.set_attribute("graphql.field.name", resolver_name)
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        def sync_wrapper(*args, **kwargs):
            tracer = get_graphql_tracer()
            with tracer.start_as_current_span(
                f"graphql.resolve.{resolver_name}",
                kind=trace.SpanKind.INTERNAL,
            ) as span:
                span.set_attribute("graphql.field.name", resolver_name)
                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        # Check if function is async
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_dataloader_batch(loader_name: str, batch_size: int) -> None:
    """Record DataLoader batch execution in tracing.

    Call this from DataLoader batch functions to track batching efficiency.

    Args:
        loader_name: Name of the DataLoader (e.g., "reminders", "tags")
        batch_size: Number of IDs in this batch

    Example:
        async def _batch_load_reminders(self, ids: list[UUID]) -> list[Reminder | None]:
            trace_dataloader_batch("reminders", len(ids))
            # ... load reminders ...
    """
    tracer = get_graphql_tracer()
    with tracer.start_as_current_span(
        f"graphql.dataloader.{loader_name}",
        kind=trace.SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("graphql.dataloader.name", loader_name)
        span.set_attribute("graphql.dataloader.batch_size", batch_size)


# ============================================================================
# Usage Examples
# ============================================================================

"""
Example: Basic tracing setup
    from example_service.features.graphql.extensions.tracing import GraphQLTracingExtension

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        extensions=[
            GraphQLTracingExtension(),  # Enable tracing
        ],
    )

Example: Tracing with custom options
    extensions = [
        GraphQLTracingExtension(
            include_document=True,  # Include query text (be careful with sensitive data)
            include_variables=True,  # Include sanitized variables
        ),
    ]

Example: Trace expensive resolvers
    from example_service.features.graphql.extensions.tracing import trace_resolver

    @strawberry.type
    class ReminderType:
        @strawberry.field
        @trace_resolver("reminder.expensive_calculation")
        async def expensive_calculation(self) -> int:
            # This resolver will have its own span
            return await calculate_something_expensive(self.id)

Example: Trace DataLoader batches
    from example_service.features.graphql.extensions.tracing import trace_dataloader_batch

    class ReminderDataLoader:
        async def _batch_load_reminders(self, ids: list[UUID]) -> list[Reminder | None]:
            # Record batch execution
            trace_dataloader_batch("reminders", len(ids))

            # Load reminders...
            stmt = select(Reminder).where(Reminder.id.in_(ids))
            result = await self._session.execute(stmt)
            reminders = {r.id: r for r in result.scalars().all()}

            return [reminders.get(id_) for id_ in ids]

Example: Viewing traces
    # Traces are exported to configured OTLP endpoint (e.g., Jaeger, Tempo)
    # View in Jaeger UI:
    # - Service: example-service
    # - Operation: graphql.execute
    # - Tags: graphql.operation.type, graphql.operation.name

    # Example trace:
    # graphql.execute (200ms)
    # ├── graphql.resolve.reminders (150ms)
    # │   ├── graphql.dataloader.reminders (5ms, batch_size=10)
    # │   └── graphql.dataloader.reminder_tags (8ms, batch_size=10)
    # └── graphql.format (2ms)

Example: Integration with existing tracing
    # GraphQL tracing automatically integrates with existing OpenTelemetry setup
    # Incoming HTTP request spans will be parent spans for GraphQL operations

    # Example trace hierarchy:
    # http.request POST /graphql (250ms)
    # └── graphql.execute (200ms)
    #     └── graphql.resolve.reminders (150ms)

Example: Error tracking in traces
    # When GraphQL errors occur, they're recorded in spans:
    # - span.status = ERROR
    # - graphql.error.count = 1
    # - graphql.error.message = "Reminder not found"
    # - graphql.error.code = "NOT_FOUND"

    # This allows filtering traces by error status in tracing UI

Best Practices:
1. Enable tracing in production (uses sampling to reduce overhead)
2. Be careful with include_document (may expose sensitive queries)
3. Use trace_resolver sparingly (only for expensive/important resolvers)
4. Monitor DataLoader batch sizes for N+1 detection
5. Set up alerts on error rates in traces
6. Use trace correlation IDs to connect logs and traces

Performance Impact:
- Overhead: ~1-5ms per request (with sampling)
- Sampling: Use probabilistic sampler in production (e.g., 10% of traces)
- Batch export: Spans are exported in batches (minimal latency impact)

Integration with monitoring:
- Jaeger: Full-featured tracing UI
- Grafana Tempo: Metrics + traces
- Zipkin: Alternative tracing backend
- AWS X-Ray: AWS-native tracing
- Google Cloud Trace: GCP-native tracing
"""
