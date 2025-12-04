##GraphQL Feature Configuration

This document explains how to enable/disable GraphQL features and add new ones.

## Architecture Overview

The GraphQL schema uses a **modular, plug-and-play architecture**:

```
Features → Feature Registry → Schema Composition → Final Schema
```

Each feature is self-contained with its own:
- Query resolvers
- Mutation resolvers
- Subscription resolvers
- GraphQL types
- Pydantic schemas

Features can be toggled on/off without modifying any core code.

## Disabling a Feature

GraphQL features are controlled via **environment variables** using the `GRAPHQL_FEATURE_` prefix. This integrates with the existing settings system in `core/settings/graphql.py`.

### Environment Variables (Recommended)

Add to your `.env` file or export in your shell:

```bash
# .env or environment
GRAPHQL_FEATURE_TAGS=false
GRAPHQL_FEATURE_AUDIT_LOGS=false
GRAPHQL_FEATURE_AI=true
```

All features are **enabled by default** except experimental ones (ai=false).

### Available Feature Toggles

```bash
GRAPHQL_FEATURE_REMINDERS=true     # Reminder queries/mutations/subscriptions
GRAPHQL_FEATURE_TAGS=true          # Tag queries/mutations
GRAPHQL_FEATURE_FLAGS=true         # Feature flag management
GRAPHQL_FEATURE_FILES=true         # File upload/management
GRAPHQL_FEATURE_WEBHOOKS=true      # Webhook management
GRAPHQL_FEATURE_AUDIT_LOGS=true    # Audit log queries (read-only)
GRAPHQL_FEATURE_AI=false           # AI/ML features (experimental)
```

### Example: Disable Tags and Files

```bash
# .env
GRAPHQL_FEATURE_TAGS=false
GRAPHQL_FEATURE_FILES=false
```

That's it! The schema will automatically exclude tags and files resolvers.

### Checking Feature Status in Code

```python
from example_service.features.graphql.config import get_graphql_features

features = get_graphql_features()

if features.tags:
    print("Tags feature is enabled")

if features.ai:
    print("AI feature is enabled")

# Get list of enabled features
enabled = features.get_enabled_features()
print(f"Enabled features: {enabled}")
# Output: ['reminders', 'feature_flags', 'webhooks', 'audit_logs']
```

## Adding a New Feature (AI Example)

Here's how to add AI chat functionality to your GraphQL API:

### Step 1: Create AI Types

```python
# example_service/features/graphql/types/ai.py
from __future__ import annotations

import strawberry
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strawberry.types import Info


@strawberry.type(description="AI chat message")
class ChatMessage:
    """AI chat message."""

    role: str = strawberry.field(description="Message role (user/assistant)")
    content: str = strawberry.field(description="Message content")
    timestamp: str = strawberry.field(description="ISO timestamp")


@strawberry.type(description="AI chat response")
class ChatResponse:
    """Response from AI chat."""

    message: ChatMessage = strawberry.field(description="AI's response message")
    model: str = strawberry.field(description="Model used (e.g., gpt-4)")
    tokens_used: int = strawberry.field(description="Total tokens consumed")


@strawberry.input(description="Input for AI chat")
class ChatInput:
    """Input for AI chat mutation."""

    message: str = strawberry.field(description="User's message")
    conversation_id: str | None = strawberry.field(
        default=None,
        description="Conversation ID for context",
    )
    model: str = strawberry.field(
        default="gpt-4",
        description="AI model to use",
    )


__all__ = ["ChatMessage", "ChatResponse", "ChatInput"]
```

### Step 2: Create AI Queries

```python
# example_service/features/graphql/resolvers/ai_queries.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import strawberry

from example_service.features.graphql.types.ai import ChatMessage

if TYPE_CHECKING:
    from strawberry.types import Info
    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def chat_history_query(
    info: Info[GraphQLContext, None],
    conversation_id: strawberry.ID,
) -> list[ChatMessage]:
    """Get chat history for a conversation.

    Args:
        info: Strawberry info with context
        conversation_id: Conversation UUID

    Returns:
        List of chat messages in chronological order
    """
    ctx = info.context

    try:
        conv_uuid = UUID(str(conversation_id))
    except ValueError:
        return []

    # Load from your AI service/database
    # messages = await ai_service.get_history(ctx.session, conv_uuid)

    # For now, return empty (implement your AI service)
    logger.info(f"Fetching chat history for conversation: {conv_uuid}")
    return []


__all__ = ["chat_history_query"]
```

### Step 3: Create AI Mutations

```python
# example_service/features/graphql/resolvers/ai_mutations.py
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import strawberry

from example_service.features.graphql.types.ai import ChatInput, ChatResponse, ChatMessage

if TYPE_CHECKING:
    from strawberry.types import Info
    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def chat_mutation(
    info: Info[GraphQLContext, None],
    input: ChatInput,
) -> ChatResponse:
    """Send a message to AI and get response.

    Args:
        info: Strawberry info with context
        input: Chat input with message and optional context

    Returns:
        ChatResponse with AI's message
    """
    ctx = info.context

    logger.info(f"Processing chat message: {input.message[:50]}...")

    # Call your AI service (OpenAI, Anthropic, local model, etc.)
    # response = await ai_service.chat(
    #     message=input.message,
    #     conversation_id=input.conversation_id,
    #     model=input.model,
    # )

    # For demonstration, return mock response
    from datetime import datetime, UTC

    return ChatResponse(
        message=ChatMessage(
            role="assistant",
            content=f"Mock AI response to: {input.message}",
            timestamp=datetime.now(UTC).isoformat(),
        ),
        model=input.model,
        tokens_used=100,
    )


__all__ = ["chat_mutation"]
```

### Step 4: Create AI Subscriptions

```python
# example_service/features/graphql/resolvers/ai_subscriptions.py
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, AsyncGenerator

import strawberry

from example_service.features.graphql.types.ai import ChatMessage

if TYPE_CHECKING:
    from strawberry.types import Info
    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)


async def streaming_chat_subscription(
    info: Info[GraphQLContext, None],
    conversation_id: strawberry.ID,
) -> AsyncGenerator[ChatMessage]:
    """Stream AI responses token by token (like ChatGPT).

    Args:
        info: Strawberry info with context
        conversation_id: Conversation to stream responses for

    Yields:
        ChatMessage chunks as they're generated
    """
    logger.info(f"Starting streaming chat for conversation: {conversation_id}")

    # Connect to your streaming AI service
    # async for chunk in ai_service.stream_chat(conversation_id):
    #     yield ChatMessage(
    #         role="assistant",
    #         content=chunk,
    #         timestamp=datetime.now(UTC).isoformat(),
    #     )

    # Mock streaming for demonstration
    from datetime import datetime, UTC

    words = ["Hello", "this", "is", "a", "streaming", "response"]
    for word in words:
        await asyncio.sleep(0.1)  # Simulate processing delay
        yield ChatMessage(
            role="assistant",
            content=word,
            timestamp=datetime.now(UTC).isoformat(),
        )


__all__ = ["streaming_chat_subscription"]
```

### Step 5: Register AI Feature

```python
# example_service/features/graphql/resolvers/feature_registry.py
from example_service.features.graphql.config import get_feature_registry

# Import all feature resolvers
from example_service.features.graphql.resolvers import queries as reminder_queries
from example_service.features.graphql.resolvers import mutations as reminder_mutations
from example_service.features.graphql.resolvers.tags_queries import tag_query, tags_query
from example_service.features.graphql.resolvers.tags_mutations import (
    create_tag_mutation,
    update_tag_mutation,
    delete_tag_mutation,
)
# ... other features ...

# AI feature imports
from example_service.features.graphql.resolvers.ai_queries import chat_history_query
from example_service.features.graphql.resolvers.ai_mutations import chat_mutation
from example_service.features.graphql.resolvers.ai_subscriptions import streaming_chat_subscription


def register_all_features() -> None:
    """Register all GraphQL features with the registry."""
    registry = get_feature_registry()

    # Register reminders feature
    registry.register(
        "reminders",
        queries=[
            reminder_queries.reminder,
            reminder_queries.reminders,
            reminder_queries.overdue_reminders,
        ],
        mutations=[
            reminder_mutations.create_reminder,
            reminder_mutations.update_reminder,
            reminder_mutations.complete_reminder,
            reminder_mutations.delete_reminder,
        ],
    )

    # Register tags feature
    registry.register(
        "tags",
        queries=[tag_query, tags_query],
        mutations=[create_tag_mutation, update_tag_mutation, delete_tag_mutation],
    )

    # Register AI feature (NEW!)
    registry.register(
        "ai",
        queries=[chat_history_query],
        mutations=[chat_mutation],
        subscriptions=[streaming_chat_subscription],
    )

    # ... register other features ...


__all__ = ["register_all_features"]
```

### Step 6: Enable AI Feature

Add to your `.env` file:

```bash
# .env
GRAPHQL_FEATURE_AI=true
```

Or export as an environment variable:

```bash
export GRAPHQL_FEATURE_AI=true
```

### Step 7: Use in Schema

The AI queries/mutations/subscriptions are now automatically available:

```graphql
# Query chat history
query {
  chatHistory(conversationId: "123") {
    role
    content
    timestamp
  }
}

# Send chat message
mutation {
  chat(input: {
    message: "What is FastAPI?"
    model: "gpt-4"
  }) {
    message {
      content
    }
    tokensUsed
  }
}

# Stream AI response
subscription {
  streamingChat(conversationId: "123") {
    role
    content
  }
}
```

## Feature-Specific Schemas

You can create different schemas for different use cases by using different environment variable files:

### Public API (Limited Features)

```bash
# .env.public
GRAPHQL_FEATURE_REMINDERS=true
GRAPHQL_FEATURE_TAGS=true
GRAPHQL_FEATURE_FLAGS=false      # Internal only
GRAPHQL_FEATURE_FILES=true
GRAPHQL_FEATURE_WEBHOOKS=false   # Internal only
GRAPHQL_FEATURE_AUDIT_LOGS=false # Internal only
GRAPHQL_FEATURE_AI=true
```

Run with: `ENV_FILE=.env.public python -m example_service`

### Admin API (All Features)

```bash
# .env.admin
GRAPHQL_FEATURE_REMINDERS=true
GRAPHQL_FEATURE_TAGS=true
GRAPHQL_FEATURE_FLAGS=true
GRAPHQL_FEATURE_FILES=true
GRAPHQL_FEATURE_WEBHOOKS=true
GRAPHQL_FEATURE_AUDIT_LOGS=true
GRAPHQL_FEATURE_AI=true
```

Run with: `ENV_FILE=.env.admin python -m example_service`

### Internal API (No AI, No Files)

```bash
# .env.internal
GRAPHQL_FEATURE_REMINDERS=true
GRAPHQL_FEATURE_TAGS=true
GRAPHQL_FEATURE_FLAGS=true
GRAPHQL_FEATURE_FILES=false      # Use separate file service
GRAPHQL_FEATURE_WEBHOOKS=true
GRAPHQL_FEATURE_AUDIT_LOGS=true
GRAPHQL_FEATURE_AI=false         # Use separate AI service
```

Run with: `ENV_FILE=.env.internal python -m example_service`

### Docker Compose Example

```yaml
# docker-compose.yml
services:
  public-api:
    image: example-service
    environment:
      - GRAPHQL_FEATURE_FLAGS=false
      - GRAPHQL_FEATURE_WEBHOOKS=false
      - GRAPHQL_FEATURE_AUDIT_LOGS=false
    ports:
      - "8000:8000"

  admin-api:
    image: example-service
    environment:
      - GRAPHQL_FEATURE_REMINDERS=true
      - GRAPHQL_FEATURE_FLAGS=true
      - GRAPHQL_FEATURE_WEBHOOKS=true
      - GRAPHQL_FEATURE_AUDIT_LOGS=true
    ports:
      - "8001:8000"
```

## Benefits of This Architecture

1. **Zero Core Changes**: Add/remove features without touching schema.py
2. **Environment-Specific**: Different features per deployment (dev/staging/prod)
3. **Client-Specific**: Different schemas for web/mobile/internal clients
4. **Easy Testing**: Disable expensive features in tests (AI, file uploads)
5. **Gradual Rollout**: Enable features for specific users/tenants
6. **Clear Dependencies**: Each feature is self-contained
7. **Documentation**: Auto-generate feature list from configuration

## Testing with Feature Toggles

```python
# tests/conftest.py
import pytest
from example_service.features.graphql.config import GraphQLFeatures, set_graphql_features


@pytest.fixture
def minimal_graphql_features():
    """Only enable minimal features for fast tests."""
    features = GraphQLFeatures(
        reminders=True,
        tags=False,
        feature_flags=False,
        files=False,
        webhooks=False,
        audit_logs=False,
        ai=False,  # Don't call AI APIs in tests
    )
    set_graphql_features(features)
    yield features


@pytest.fixture
def ai_enabled_features():
    """Enable AI for AI-specific tests."""
    features = GraphQLFeatures(
        reminders=False,
        tags=False,
        feature_flags=False,
        files=False,
        webhooks=False,
        audit_logs=False,
        ai=True,  # Only AI feature
    )
    set_graphql_features(features)
    yield features
```

## Migration Path

To migrate existing code to this architecture:

1. **Keep current schema working** - No breaking changes
2. **Register existing features** - Add to feature_registry.py
3. **Update schema composition** - Use registry in schema.py
4. **Test thoroughly** - Ensure all features still work
5. **Add new features** - Use modular pattern going forward
6. **Deprecate old pattern** - Eventually remove hardcoded resolvers

The modular architecture is **opt-in** - existing code continues working while you gradually adopt the pattern for new features.
