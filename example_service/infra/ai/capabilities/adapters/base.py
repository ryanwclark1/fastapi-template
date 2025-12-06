"""Base adapter protocol for AI provider adapters.

All provider adapters implement this protocol to provide:
- Capability declarations with metadata
- Standardized execution interface
- Cost tracking and usage metrics
- Health check support

Design Principles:
1. Adapters wrap existing providers, don't replace them
2. OperationResult is the universal output format
3. Errors are captured in OperationResult, not raised (for fallback support)
4. Cost calculation happens in the adapter, using actual usage data
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
import logging
import time
from typing import Any

from example_service.infra.ai.capabilities.types import (
    Capability,
    CapabilityMetadata,
    OperationResult,
    ProviderRegistration,
)

logger = logging.getLogger(__name__)


class ProviderAdapter(ABC):
    """Base class for all provider adapters.

    Adapters wrap provider implementations and provide:
    - Capability declarations with metadata
    - Standardized execution interface (execute method)
    - Cost tracking using actual usage data from provider responses
    - Health check support

    Implementation Guide:
        1. Implement get_registration() to declare capabilities
        2. Implement execute() to handle operations
        3. Use _calculate_cost() helper for cost tracking
        4. Optionally override health_check() for internal providers

    Example:
        class MyProviderAdapter(ProviderAdapter):
            def __init__(self, api_key: str, model_name: str = "default"):
                self.api_key = api_key
                self.model_name = model_name
                self._provider = MyProvider(api_key)

            def get_registration(self) -> ProviderRegistration:
                return ProviderRegistration(
                    provider_name="my_provider",
                    provider_type=ProviderType.EXTERNAL,
                    capabilities=[
                        CapabilityMetadata(Capability.LLM_GENERATION, ...),
                    ],
                )

            async def execute(
                self,
                capability: Capability,
                input_data: Any,
                **options,
            ) -> OperationResult:
                # Route to appropriate method based on capability
                if capability == Capability.LLM_GENERATION:
                    return await self._generate(input_data, **options)
                raise ValueError(f"Unsupported capability: {capability}")
    """

    @abstractmethod
    def get_registration(self) -> ProviderRegistration:
        """Get the provider registration with all capabilities.

        Returns:
            ProviderRegistration with capability metadata
        """
        ...

    @abstractmethod
    async def execute(
        self,
        capability: Capability,
        input_data: Any,
        **options: Any,
    ) -> OperationResult:
        """Execute an AI operation.

        This is the main entry point for all operations. The adapter
        should route to the appropriate internal method based on capability.

        Args:
            capability: The capability to execute
            input_data: Input data (format depends on capability)
            **options: Additional options for the operation

        Returns:
            OperationResult with success/failure, data, usage, and cost

        Note:
            Implementations should NOT raise exceptions for operation failures.
            Instead, return OperationResult with success=False and error details.
            This enables fallback logic in the pipeline executor.
        """
        ...

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return self.get_registration().provider_name

    def supports(self, capability: Capability) -> bool:
        """Check if this adapter supports a capability.

        Args:
            capability: The capability to check

        Returns:
            True if supported
        """
        return self.get_registration().supports(capability)

    def get_capability_metadata(self, capability: Capability) -> CapabilityMetadata | None:
        """Get metadata for a specific capability.

        Args:
            capability: The capability to look up

        Returns:
            CapabilityMetadata if found, None otherwise
        """
        return self.get_registration().get_capability(capability)

    async def health_check(self) -> bool:
        """Check if the provider is healthy and accessible.

        Override this method for providers with health endpoints.

        Returns:
            True if healthy, False otherwise
        """
        return True

    def _create_success_result(
        self,
        capability: Capability,
        data: Any,
        usage: dict[str, Any],
        latency_ms: float,
        request_id: str | None = None,
    ) -> OperationResult:
        """Create a successful operation result.

        Helper method for consistent result creation.

        Args:
            capability: The capability that was executed
            data: The operation output
            usage: Usage metrics (tokens, duration, etc.)
            latency_ms: Operation latency
            request_id: Provider's request ID

        Returns:
            OperationResult with success=True
        """
        cost = self._calculate_cost(capability, usage)

        return OperationResult(
            success=True,
            data=data,
            provider_name=self.provider_name,
            capability=capability,
            usage=usage,
            cost_usd=cost,
            latency_ms=latency_ms,
            request_id=request_id,
        )

    def _create_error_result(
        self,
        capability: Capability,
        error: str,
        error_code: str | None = None,
        retryable: bool = False,
        latency_ms: float = 0,
    ) -> OperationResult:
        """Create a failed operation result.

        Helper method for consistent error handling.

        Args:
            capability: The capability that was attempted
            error: Error message
            error_code: Optional error code
            retryable: Whether the error is retryable
            latency_ms: Operation latency before failure

        Returns:
            OperationResult with success=False
        """
        return OperationResult(
            success=False,
            data=None,
            provider_name=self.provider_name,
            capability=capability,
            error=error,
            error_code=error_code,
            retryable=retryable,
            latency_ms=latency_ms,
        )

    def _calculate_cost(
        self,
        capability: Capability,
        usage: dict[str, Any],
    ) -> Decimal:
        """Calculate cost from usage metrics.

        Uses capability metadata for pricing.

        Args:
            capability: The capability used
            usage: Usage metrics from provider response

        Returns:
            Calculated cost in USD
        """
        cap_meta = self.get_capability_metadata(capability)
        if not cap_meta:
            return Decimal(0)

        input_tokens_val = usage.get("input_tokens", 0)
        output_tokens_val = usage.get("output_tokens", 0)
        duration_seconds_val = usage.get("duration_seconds", 0)
        character_count_val = usage.get("character_count", 0)
        request_count_val = usage.get("request_count", 1)

        return cap_meta.estimate_cost(
            input_tokens=int(input_tokens_val) if input_tokens_val is not None else 0,
            output_tokens=int(output_tokens_val) if output_tokens_val is not None else 0,
            duration_seconds=float(duration_seconds_val)
            if duration_seconds_val is not None
            else 0.0,
            character_count=int(character_count_val) if character_count_val is not None else 0,
            request_count=int(request_count_val) if request_count_val is not None else 1,
        )

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error is retryable.

        Override in subclasses for provider-specific logic.

        Args:
            error: The exception that occurred

        Returns:
            True if the operation should be retried
        """
        error_str = str(error).lower()
        retryable_patterns = [
            "timeout",
            "rate limit",
            "too many requests",
            "service unavailable",
            "connection",
            "temporary",
            "429",
            "503",
            "504",
        ]
        return any(pattern in error_str for pattern in retryable_patterns)

    def _get_error_code(self, error: Exception) -> str | None:
        """Extract error code from exception.

        Override in subclasses for provider-specific logic.

        Args:
            error: The exception that occurred

        Returns:
            Error code if extractable, None otherwise
        """
        # Check for common error attributes
        if hasattr(error, "status_code"):
            return str(error.status_code)
        if hasattr(error, "code"):
            return str(error.code)
        return None


class TimedExecution:
    """Context manager for timing operations.

    Usage:
        async with TimedExecution() as timer:
            result = await some_operation()
        print(f"Took {timer.elapsed_ms}ms")
    """

    def __init__(self) -> None:
        self.start_time: float = 0
        self.end_time: float = 0
        self.elapsed_ms: float = 0

    async def __aenter__(self) -> TimedExecution:
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, *args: object) -> None:
        self.end_time = time.perf_counter()
        self.elapsed_ms = (self.end_time - self.start_time) * 1000
