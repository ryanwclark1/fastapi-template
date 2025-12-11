"""AI Infrastructure Package.

This package provides the new capability-based, composable pipeline architecture
for AI workflows with full observability.

Quick Start:
    from example_service.infra.ai import (
        InstrumentedOrchestrator,
        get_instrumented_orchestrator,
        start_ai_infrastructure,
        stop_ai_infrastructure,
    )

    # At application startup
    await start_ai_infrastructure()

    # Execute pipelines
    orchestrator = get_instrumented_orchestrator()
    result = await orchestrator.execute(
        pipeline=get_pipeline("call_analysis"),
        input_data={"audio_url": "..."},
        tenant_id="tenant-123",
    )

    # At application shutdown
    await stop_ai_infrastructure()

Architecture:
    InstrumentedOrchestrator (entry point)
        ├── CapabilityRegistry (provider discovery)
        ├── SagaCoordinator (execution + compensation)
        ├── EventStore (real-time events)
        ├── AITracer (OpenTelemetry)
        ├── AIMetrics (Prometheus)
        └── BudgetService (cost tracking)
"""

from __future__ import annotations

from decimal import Decimal
from importlib import import_module
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from example_service.core.settings.ai import AISettings

from example_service.infra.ai.instrumented_orchestrator import (
    InstrumentedOrchestrator,
    get_instrumented_orchestrator,
)
from example_service.infra.ai.pipelines import (
    get_pipeline,
    list_pipelines,
)

logger = logging.getLogger(__name__)

# Module-level state
_initialized = False


async def start_ai_infrastructure(settings: AISettings | None = None) -> bool:
    """Initialize AI infrastructure at application startup.

    This function:
    1. Registers built-in providers with the capability registry
    2. Configures observability (tracing, metrics)
    3. Configures budget service with defaults
    4. Creates global orchestrator instance

    Args:
        settings: AI settings (loads from environment if None)

    Returns:
        True if initialization succeeded
    """
    global _initialized

    if _initialized:
        logger.debug("AI infrastructure already initialized")
        return True

    try:
        # Load settings if not provided
        if settings is None:
            from example_service.core.settings import get_ai_settings
            settings = get_ai_settings()

        # 1. Initialize capability registry and register providers
        from example_service.infra.ai.capabilities import (
            get_capability_registry,
            reset_capability_registry,
        )
        from example_service.infra.ai.capabilities.builtin_providers import (
            register_builtin_providers,
        )

        # Reset registry to ensure clean state
        reset_capability_registry()
        registry = get_capability_registry()

        # Build API keys from settings
        openai_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        anthropic_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        deepgram_key = settings.deepgram_api_key.get_secret_value() if settings.deepgram_api_key else None

        # Build api_keys dict for orchestrator
        api_keys: dict[str, str] = {}
        if openai_key:
            api_keys["openai"] = openai_key
        if anthropic_key:
            api_keys["anthropic"] = anthropic_key
        if deepgram_key:
            api_keys["deepgram"] = deepgram_key

        # Register built-in providers
        register_builtin_providers(
            registry=registry,
            settings=settings,
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            deepgram_api_key=deepgram_key,
            skip_unavailable=True,
        )

        provider_count = len(registry.get_all_providers())
        logger.info(
            "Capability registry initialized",
            extra={"provider_count": provider_count},
        )

        # 2. Initialize event store
        from example_service.infra.ai.events import (
            InMemoryEventStore,
            configure_event_store,
        )

        event_store = InMemoryEventStore()
        configure_event_store(event_store)
        logger.debug("Event store initialized")

        # 3. Initialize observability components
        if settings.enable_pipeline_tracing:
            from example_service.infra.ai.observability import configure_ai_tracer

            configure_ai_tracer(enabled=True)
            logger.debug("AI tracing enabled")

        if settings.enable_pipeline_metrics:
            from example_service.infra.ai.observability import configure_ai_metrics

            configure_ai_metrics(enabled=True)
            logger.debug("AI metrics enabled")

        # 4. Initialize budget service
        if settings.enable_budget_enforcement:
            from example_service.infra.ai.observability import configure_budget_service

            configure_budget_service(
                default_daily_limit=Decimal(str(settings.default_daily_budget_usd))
                if settings.default_daily_budget_usd
                else None,
                default_monthly_limit=Decimal(str(settings.default_monthly_budget_usd))
                if settings.default_monthly_budget_usd
                else None,
            )
            logger.debug(
                "Budget service initialized",
                extra={"policy": settings.budget_policy},
            )

        # 5. Initialize agent state store with Redis if available
        try:
            from example_service.infra.ai.agents.state_store import (
                configure_redis_state_store,
            )

            redis_store = await configure_redis_state_store()
            if redis_store:
                logger.debug("Agent state store configured with Redis backend")
            else:
                logger.debug("Agent state store using in-memory backend")
        except Exception as e:
            logger.warning(
                "Failed to configure Redis state store for agents",
                extra={"error": str(e)},
            )

        # 6. Create global orchestrator
        from example_service.infra.ai.instrumented_orchestrator import (
            InstrumentedOrchestrator,
            configure_orchestrator,
        )

        orchestrator = InstrumentedOrchestrator(
            api_keys=api_keys,
            enable_tracing=settings.enable_pipeline_tracing,
            enable_metrics=settings.enable_pipeline_metrics,
            enable_budget_enforcement=settings.enable_budget_enforcement,
        )
        configure_orchestrator(orchestrator)

        _initialized = True
        logger.info(
            "AI infrastructure started",
            extra={
                "providers": provider_count,
                "tracing": settings.enable_pipeline_tracing,
                "metrics": settings.enable_pipeline_metrics,
                "budget_enforcement": settings.enable_budget_enforcement,
            },
        )
        return True

    except Exception as e:
        logger.exception(
            "Failed to initialize AI infrastructure",
            extra={"error": str(e)},
        )
        return False


async def stop_ai_infrastructure() -> None:
    """Shutdown AI infrastructure gracefully.

    This function:
    1. Clears global orchestrator
    2. Resets observability components
    3. Clears capability registry
    """
    global _initialized

    if not _initialized:
        return

    try:
        # Clear orchestrator
        from example_service.infra.ai.instrumented_orchestrator import (
            configure_orchestrator,
        )
        configure_orchestrator(None)

        # Reset event store
        from example_service.infra.ai.events import configure_event_store
        configure_event_store(None)

        # Reset agent state store
        try:
            from example_service.infra.ai.agents.state_store import reset_state_store
            reset_state_store()
        except Exception as e:
            logger.debug(f"Error resetting state store: {e}")

        # Reset registry
        from example_service.infra.ai.capabilities import reset_capability_registry
        reset_capability_registry()

        _initialized = False
        logger.info("AI infrastructure stopped")

    except Exception as e:
        logger.exception(
            "Error during AI infrastructure shutdown",
            extra={"error": str(e)},
        )


def is_ai_initialized() -> bool:
    """Check if AI infrastructure is initialized."""
    return _initialized


__all__ = [
    # Orchestrator
    "InstrumentedOrchestrator",
    # Agents (re-exported from agents subpackage)
    "agents",
    "get_instrumented_orchestrator",
    # Pipelines
    "get_pipeline",
    "is_ai_initialized",
    "list_pipelines",
    # Lifecycle
    "start_ai_infrastructure",
    "stop_ai_infrastructure",
]


def __getattr__(name: str) -> Any:
    if name == "agents":
        module = import_module("example_service.infra.ai.agents")
        globals()[name] = module
        return module
    raise AttributeError(name)
