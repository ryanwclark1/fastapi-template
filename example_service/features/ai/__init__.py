"""AI services feature module.

Provides AI processing capabilities including:
- Audio transcription (single/dual channel)
- PII redaction and masking
- Conversation summarization
- Sentiment analysis
- Coaching analysis
- Cost tracking and usage metrics
- Agent configuration and management
"""

from __future__ import annotations

from .agent_resolver import AgentResolver
from .integration import (
    create_agent_config_from_db,
    get_agent_config,
    get_agent_config_by_key,
)
from .models import Agent, AIJob, AIUsageLog, TenantAIConfig, TenantAIFeature
from .repository import AgentRepository
from .schemas import (
    AgentCreate,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
)
from .service import AgentService

__all__ = [
    "AIJob",
    "AIUsageLog",
    "Agent",
    "AgentCreate",
    "AgentExecuteRequest",
    "AgentExecuteResponse",
    "AgentListResponse",
    "AgentRepository",
    "AgentResolver",
    "AgentResponse",
    "AgentService",
    "AgentUpdate",
    "TenantAIConfig",
    "TenantAIFeature",
    "create_agent_config_from_db",
    "get_agent_config",
    "get_agent_config_by_key",
]
