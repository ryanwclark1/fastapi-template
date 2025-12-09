"""GraphQL server configuration settings.

Controls the GraphQL endpoint, playground, subscriptions, and query limits.
Environment variables use GRAPHQL_ prefix.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

GraphQLIDE = Literal["graphiql", "apollo-sandbox", "pathfinder", "playground", False]


class GraphQLSettings(BaseSettings):
    """GraphQL server configuration.

    Environment variables use GRAPHQL_ prefix.
    Example: GRAPHQL_ENABLED=true, GRAPHQL_PATH=/graphql
    """

    # Enable/disable GraphQL
    enabled: bool = Field(
        default=True,
        description="Enable GraphQL endpoint",
    )

    # Endpoint configuration
    path: str = Field(
        default="/graphql",
        min_length=1,
        max_length=255,
        pattern=r"^/.*$",
        description="GraphQL endpoint path",
    )

    # Playground/IDE configuration (follows same pattern as docs)
    graphql_ide: GraphQLIDE = Field(
        default="graphiql",
        description=(
            "GraphQL IDE to use: graphiql, apollo-sandbox, pathfinder, playground, or false to disable"
        ),
    )
    disable_playground: bool = Field(
        default=False,
        description="Disable GraphQL playground/IDE (like disable_docs for REST)",
    )

    # Query limits for security
    max_query_depth: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum query nesting depth",
    )
    max_complexity: int = Field(
        default=1000,
        ge=100,
        le=50000,
        description="Maximum query complexity score",
    )

    # Pagination defaults
    default_page_size: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Default pagination size for connections",
    )
    max_page_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum pagination size for connections",
    )

    # Subscriptions
    subscriptions_enabled: bool = Field(
        default=True,
        description="Enable GraphQL subscriptions (WebSocket)",
    )
    subscription_keepalive_interval: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description="Keepalive ping interval for subscriptions in seconds",
    )

    # Introspection (security)
    introspection_enabled: bool = Field(
        default=True,
        description="Enable GraphQL schema introspection (disable in production for security)",
    )

    # Feature Toggles
    # Enable/disable specific GraphQL features without code changes
    feature_reminders: bool = Field(
        default=True,
        description="Enable reminder queries/mutations/subscriptions",
    )
    feature_tags: bool = Field(
        default=True,
        description="Enable tag queries/mutations",
    )
    feature_flags: bool = Field(
        default=True,
        description="Enable feature flag management queries/mutations",
    )
    feature_files: bool = Field(
        default=True,
        description="Enable file upload/management queries/mutations",
    )
    feature_webhooks: bool = Field(
        default=True,
        description="Enable webhook management queries/mutations",
    )
    feature_audit_logs: bool = Field(
        default=True,
        description="Enable audit log queries (read-only)",
    )
    feature_ai: bool = Field(
        default=False,
        description="Enable AI/ML features (experimental)",
    )
    feature_tasks: bool = Field(
        default=True,
        description="Enable task management queries/mutations",
    )
    feature_search: bool = Field(
        default=True,
        description="Enable search queries",
    )

    model_config = SettingsConfigDict(
        env_prefix="GRAPHQL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    @model_validator(mode="after")
    def validate_playground_requires_enabled(self) -> GraphQLSettings:
        """Validate that playground settings make sense."""
        if self.disable_playground and self.graphql_ide:
            # If playground is disabled, IDE setting is ignored
            pass
        return self

    @property
    def playground_enabled(self) -> bool:
        """Check if GraphQL playground is enabled."""
        return not self.disable_playground and self.graphql_ide is not False

    def get_graphql_ide(self) -> GraphQLIDE:
        """Get GraphQL IDE setting or False if disabled."""
        if self.disable_playground:
            return False
        return self.graphql_ide

    @property
    def is_configured(self) -> bool:
        """Check if GraphQL is enabled and configured."""
        return self.enabled
