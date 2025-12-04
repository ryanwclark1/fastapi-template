"""Job system configuration settings.

Provides settings for:
- Timeout enforcement
- Retry configuration
- Result cleanup/retention
- Priority queue
- Webhook delivery
- Progress tracking
"""

from pydantic_settings import BaseSettings


class JobSettings(BaseSettings):
    """Configuration for the job management system."""

    # Timeout enforcement
    default_timeout_seconds: int = 3600
    """Default job timeout in seconds (1 hour). Jobs running longer are auto-cancelled."""

    timeout_check_interval_seconds: int = 60
    """How often to check for timed-out jobs (in seconds)."""

    # Retry configuration
    default_max_retries: int = 3
    """Default maximum retry attempts for failed jobs."""

    retry_backoff_base_seconds: float = 60.0
    """Base delay for exponential backoff between retries (seconds)."""

    retry_backoff_max_seconds: float = 3600.0
    """Maximum delay between retries (1 hour cap)."""

    retry_backoff_multiplier: float = 2.0
    """Multiplier for exponential backoff (delay = base * multiplier^attempt)."""

    # Result cleanup
    result_retention_days: int = 30
    """How long to keep completed/failed job results before cleanup."""

    cleanup_batch_size: int = 1000
    """Number of jobs to delete per cleanup batch."""

    cleanup_interval_hours: int = 24
    """How often to run the cleanup job (in hours)."""

    # Priority queue (Redis)
    redis_priority_key_prefix: str = "job:priority:"
    """Redis key prefix for priority queues."""

    redis_job_key_prefix: str = "job:data:"
    """Redis key prefix for job data cache."""

    # Webhooks
    webhook_timeout_seconds: int = 30
    """Timeout for webhook HTTP requests."""

    webhook_max_retries: int = 3
    """Maximum retry attempts for failed webhook delivery."""

    webhook_retry_delay_seconds: float = 60.0
    """Delay between webhook retry attempts."""

    # Progress tracking
    progress_update_debounce_ms: int = 500
    """Minimum interval between progress updates to avoid DB flooding."""

    # Dependency checking
    dependency_check_batch_size: int = 100
    """Number of pending jobs to check for satisfied dependencies per batch."""

    # Job submission
    max_bulk_submit_size: int = 100
    """Maximum number of jobs that can be submitted in a single bulk operation."""

    # Queue statistics
    stats_cache_ttl_seconds: int = 5
    """How long to cache queue statistics."""

    class Config:
        """Pydantic configuration."""

        env_prefix = "JOB_"
        case_sensitive = False


# Singleton instance
_settings: JobSettings | None = None


def get_job_settings() -> JobSettings:
    """Get the job settings singleton.

    Returns:
        JobSettings instance with values from environment variables.
    """
    global _settings
    if _settings is None:
        _settings = JobSettings()
    return _settings


__all__ = ["JobSettings", "get_job_settings"]
