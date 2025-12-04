"""AI Pipeline feature module.

Provides pipeline-based AI processing with:
- Capability-based, composable pipeline architecture
- Real-time event streaming
- Budget enforcement
- Full observability (tracing, metrics)
"""

from __future__ import annotations

from example_service.features.ai.pipeline.router import router

__all__ = ["router"]
