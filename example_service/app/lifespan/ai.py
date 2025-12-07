"""AI pipeline infrastructure lifespan management."""

from __future__ import annotations

import logging

from .registry import lifespan_registry

logger = logging.getLogger(__name__)

# Track if AI infrastructure was started
_ai_infrastructure_started = False


@lifespan_registry.register(
    name="ai",
    startup_order=50,
    requires=["core"],
)
async def startup_ai(
    ai_settings: object,
    **kwargs: object,
) -> None:
    """Initialize AI pipeline infrastructure.

    Includes capability registry, observability, and budget enforcement.

    Args:
        ai_settings: AI settings
        **kwargs: Additional settings (ignored)
    """
    global _ai_infrastructure_started

    from example_service.core.settings.ai import AISettings

    settings = (
        AISettings.model_validate(ai_settings)
        if not isinstance(ai_settings, AISettings)
        else ai_settings
    )

    _ai_infrastructure_started = False
    if settings.enable_pipeline_api:
        try:
            from example_service.infra.ai import start_ai_infrastructure

            _ai_infrastructure_started = await start_ai_infrastructure(settings)
            if _ai_infrastructure_started:
                logger.info(
                    "AI pipeline infrastructure started",
                    extra={
                        "tracing": settings.enable_pipeline_tracing,
                        "metrics": settings.enable_pipeline_metrics,
                        "budget_enforcement": settings.enable_budget_enforcement,
                    },
                )
        except Exception as e:
            logger.warning(
                "Failed to start AI pipeline infrastructure",
                extra={"error": str(e)},
            )


@lifespan_registry.register(name="ai")
async def shutdown_ai(**kwargs: object) -> None:
    """Stop AI pipeline infrastructure.

    Args:
        **kwargs: Settings (ignored)
    """
    global _ai_infrastructure_started

    # Stop AI pipeline infrastructure first (has no external dependencies)
    if _ai_infrastructure_started:
        try:
            from example_service.infra.ai import stop_ai_infrastructure

            await stop_ai_infrastructure()
            logger.info("AI pipeline infrastructure stopped")
        except Exception as e:
            logger.warning(
                "Error stopping AI pipeline infrastructure",
                extra={"error": str(e)},
            )


def get_ai_infrastructure_started() -> bool:
    """Get whether AI infrastructure was successfully started.

    Returns:
        True if AI infrastructure is started, False otherwise.
    """
    return _ai_infrastructure_started
