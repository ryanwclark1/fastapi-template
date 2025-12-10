"""OpenTelemetry tracing dependencies for FastAPI route handlers.

This module provides FastAPI-compatible dependencies for accessing
OpenTelemetry tracing utilities for distributed tracing.

Usage:
    from example_service.core.dependencies.tracing import (
        TracerDep,
        get_tracer_dep,
    )

    @router.post("/process")
    async def process_data(
        data: ProcessData,
        tracer: TracerDep,
    ):
        with tracer.start_as_current_span("process_data") as span:
            span.set_attribute("data.size", len(data.items))
            result = await do_processing(data)
            span.add_event("processing_complete", {"count": len(result)})
        return result
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from opentelemetry.trace import Tracer


def get_tracer_dep(name: str = "example_service") -> Tracer:
    """Get an OpenTelemetry tracer instance.

    This is a thin wrapper that retrieves a tracer from the global
    tracer provider. The import is deferred to runtime to avoid
    circular dependencies.

    Args:
        name: Name for the tracer, typically the service or module name.

    Returns:
        Tracer: An OpenTelemetry tracer instance.
    """
    from example_service.infra.tracing import get_tracer

    return get_tracer(name)


def get_default_tracer() -> Tracer:
    """Get the default tracer for the application.

    Returns:
        Tracer: The default tracer instance.
    """
    return get_tracer_dep()


def tracer_factory(name: str):
    """Factory for creating named tracer dependencies.

    Use this to create module-specific tracers with custom names.

    Args:
        name: Name for the tracer.

    Returns:
        A dependency function that returns a tracer with the given name.

    Example:
        from example_service.core.dependencies.tracing import tracer_factory

        OrdersTracer = Annotated[Tracer, Depends(tracer_factory("orders"))]

        @router.post("/orders")
        async def create_order(data: OrderData, tracer: OrdersTracer):
            with tracer.start_as_current_span("create_order"):
                ...
    """

    def get_named_tracer() -> Tracer:
        return get_tracer_dep(name)

    return get_named_tracer


# Type alias for the default tracer
TracerDep = Annotated[Tracer, Depends(get_default_tracer)]
"""Default tracer dependency.

Example:
    @router.post("/process")
    async def process(data: dict, tracer: TracerDep):
        with tracer.start_as_current_span("processing"):
            ...
"""


def add_span_attributes_dep(**attributes: str | float | bool):
    """Factory for adding attributes to the current span.

    This creates a dependency that adds the specified attributes
    to the current span when the endpoint is called.

    Args:
        **attributes: Key-value pairs to add as span attributes.

    Returns:
        A dependency function that adds attributes and returns None.

    Example:
        @router.get("/items/{item_id}")
        async def get_item(
            item_id: str,
            _: Annotated[None, Depends(add_span_attributes_dep(endpoint="get_item"))],
        ):
            ...
    """

    async def add_attributes() -> None:
        from example_service.infra.tracing import add_span_attributes

        add_span_attributes(attributes)

    return add_attributes


def add_span_event_dep(name: str, **attributes: str | float | bool):
    """Factory for adding an event to the current span.

    This creates a dependency that adds a named event with optional
    attributes to the current span.

    Args:
        name: Name of the event.
        **attributes: Optional event attributes.

    Returns:
        A dependency function that adds the event and returns None.

    Example:
        @router.post("/checkout")
        async def checkout(
            _: Annotated[None, Depends(add_span_event_dep("checkout_started"))],
        ):
            ...
    """

    async def add_event() -> None:
        from example_service.infra.tracing import add_span_event

        add_span_event(name, attributes if attributes else None)

    return add_event


__all__ = [
    "TracerDep",
    "add_span_attributes_dep",
    "add_span_event_dep",
    "get_default_tracer",
    "get_tracer_dep",
    "tracer_factory",
]
