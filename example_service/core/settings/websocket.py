"""WebSocket configuration settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSocketSettings(BaseSettings):
    """WebSocket server and connection settings.

    Environment variables use WS_ prefix.
    Example: WS_HEARTBEAT_INTERVAL=30
    """

    # ──────────────────────────────────────────────────────────────
    # Connection limits
    # ──────────────────────────────────────────────────────────────

    max_connections: int = Field(
        default=10000,
        ge=1,
        le=100000,
        description="Maximum concurrent WebSocket connections per instance",
    )

    max_connections_per_user: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum connections per user ID",
    )

    max_message_size: int = Field(
        default=65536,
        ge=1024,
        le=1048576,
        description="Maximum incoming message size in bytes (default 64KB)",
    )

    # ──────────────────────────────────────────────────────────────
    # Heartbeat and timeout settings
    # ──────────────────────────────────────────────────────────────

    heartbeat_interval: float = Field(
        default=30.0,
        ge=0,
        le=300,
        description="Interval between ping messages in seconds (0 to disable)",
    )

    connection_timeout: float = Field(
        default=60.0,
        ge=0,
        le=600,
        description="Close connections after this many seconds without pong (0 to disable)",
    )

    close_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Timeout for graceful WebSocket close handshake",
    )

    # ──────────────────────────────────────────────────────────────
    # Channel configuration
    # ──────────────────────────────────────────────────────────────

    channel_prefix: str = Field(
        default="ws:",
        max_length=50,
        description="Prefix for Redis PubSub channels",
    )

    default_channels: list[str] = Field(
        default_factory=lambda: ["global"],
        description="Channels all connections are subscribed to by default",
    )

    max_channels_per_connection: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum channels a single connection can subscribe to",
    )

    # ──────────────────────────────────────────────────────────────
    # Authentication and authorization
    # ──────────────────────────────────────────────────────────────

    require_auth: bool = Field(
        default=False,
        description="Require authentication for WebSocket connections",
    )

    auth_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Timeout for authentication after connection in seconds",
    )

    # ──────────────────────────────────────────────────────────────
    # Event bridge settings
    # ──────────────────────────────────────────────────────────────

    event_bridge_enabled: bool = Field(
        default=True,
        description="Enable RabbitMQ to WebSocket event bridge",
    )

    event_bridge_queue: str = Field(
        default="websocket-events",
        max_length=100,
        description="RabbitMQ queue name for events to broadcast",
    )

    event_bridge_routing_key: str = Field(
        default="ws.broadcast.*",
        max_length=100,
        description="Routing key pattern for events to bridge",
    )

    # ──────────────────────────────────────────────────────────────
    # Feature flags
    # ──────────────────────────────────────────────────────────────

    enabled: bool = Field(
        default=True,
        description="Enable WebSocket endpoints",
    )

    compression_enabled: bool = Field(
        default=True,
        description="Enable per-message deflate compression",
    )

    model_config = SettingsConfigDict(
        env_prefix="WS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        env_ignore_empty=True,
    )
