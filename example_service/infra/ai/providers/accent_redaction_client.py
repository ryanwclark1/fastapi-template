"""Client for accent-redaction PII detection and masking service.

Provides integration with the accent-redaction microservice for:
- PII entity detection
- Text redaction/masking
- Configurable entity types
- Batch processing support
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from example_service.infra.ai.providers.base import (
    PIIEntity,
    PIIRedactionResult,
    ProviderError,
)

logger = logging.getLogger(__name__)


class AccentRedactionProvider:
    """Client for accent-redaction PII service.

    Communicates with the accent-redaction microservice to detect
    and redact PII in text and transcripts.

    Features:
    - Multiple entity types (EMAIL, PHONE, SSN, CREDIT_CARD, etc.)
    - Configurable confidence threshold
    - Multiple redaction methods (mask, replace, hash, remove)
    - Batch processing support
    - Segment-level redaction for transcripts
    """

    def __init__(
        self,
        service_url: str,
        api_key: str | None = None,
        entity_types: list[str] | None = None,
        confidence_threshold: float = 0.7,
        redaction_method: str = "mask",
        timeout: int = 60,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Initialize accent-redaction client.

        Args:
            service_url: URL of accent-redaction service
            api_key: Optional API key for service
            entity_types: Default PII entity types to detect
            confidence_threshold: Minimum confidence (0.0-1.0)
            redaction_method: How to redact (mask|replace|hash|remove)
            timeout: Request timeout in seconds
            **kwargs: Additional arguments
        """
        self.service_url = service_url.rstrip("/")
        self.api_key = api_key
        self.default_entity_types = entity_types or [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "US_SSN",
        ]
        self.confidence_threshold = confidence_threshold
        self.redaction_method = redaction_method
        self.timeout = timeout

        # Create HTTP client
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.AsyncClient(
            base_url=self.service_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout),
        )

    async def detect_pii(
        self,
        text: str,
        entity_types: list[str] | None = None,
        confidence_threshold: float | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> list[PIIEntity]:
        """Detect PII entities in text.

        Args:
            text: Text to analyze
            entity_types: Entity types to detect (None = use defaults)
            confidence_threshold: Minimum confidence (None = use default)
            **kwargs: Additional parameters

        Returns:
            List of detected PII entities

        Raises:
            ProviderError: If detection fails
        """
        try:
            # Prepare request
            payload = {
                "text": text,
                "options": {
                    "entities": entity_types or self.default_entity_types,
                    "confidence_threshold": confidence_threshold or self.confidence_threshold,
                    "return_entities": True,
                    "generate_report": False,
                },
            }

            # Call analyze endpoint
            response = await self.client.post("/api/v1/pii/analyze", json=payload)
            response.raise_for_status()

            data = response.json()

            # Parse entities
            entities = []
            for entity_data in data.get("pii_entities", []):
                entities.append(
                    PIIEntity(
                        type=entity_data["type"],
                        text=entity_data["text"],
                        start=entity_data["start"],
                        end=entity_data["end"],
                        score=entity_data["score"],
                    )
                )

            return entities

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"PII detection failed with status {e.response.status_code}: {e.response.text}",
                provider="accent_redaction",
                operation="pii_detection",
                original_error=e,
            ) from e
        except Exception as e:
            raise ProviderError(
                f"PII detection failed: {e}",
                provider="accent_redaction",
                operation="pii_detection",
                original_error=e,
            ) from e

    async def redact_pii(
        self,
        text: str,
        entity_types: list[str] | None = None,
        redaction_method: str | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> PIIRedactionResult:
        """Detect and redact PII in text.

        Args:
            text: Text to redact
            entity_types: Entity types to redact (None = use defaults)
            redaction_method: Redaction method (None = use default)
            **kwargs: Additional parameters

        Returns:
            PIIRedactionResult with original, redacted text, and entities

        Raises:
            ProviderError: If redaction fails
        """
        try:
            # Prepare request
            payload = {
                "text": text,
                "options": {
                    "entities": entity_types or self.default_entity_types,
                    "confidence_threshold": self.confidence_threshold,
                    "redaction_method": redaction_method or self.redaction_method,
                    "return_entities": True,
                    "generate_report": False,
                },
            }

            # Call process endpoint
            response = await self.client.post("/api/v1/pii/process", json=payload)
            response.raise_for_status()

            data = response.json()

            # Parse entities
            entities = []
            for entity_data in data.get("pii_entities", []):
                entities.append(
                    PIIEntity(
                        type=entity_data["type"],
                        text=entity_data["text"],
                        start=entity_data["start"],
                        end=entity_data["end"],
                        score=entity_data["score"],
                        anonymized_text=entity_data.get("anonymized_text"),
                    )
                )

            # Build redaction map
            redaction_map = {}
            for entity in entities:
                if entity.anonymized_text:
                    redaction_map[entity.text] = entity.anonymized_text

            return PIIRedactionResult(
                original_text=data["original_text"],
                redacted_text=data["anonymized_text"],
                entities=entities,
                redaction_map=redaction_map,
                provider_metadata={
                    "processing_time": data.get("processing_time"),
                    "service": "accent-redaction",
                },
            )

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"PII redaction failed with status {e.response.status_code}: {e.response.text}",
                provider="accent_redaction",
                operation="pii_redaction",
                original_error=e,
            ) from e
        except Exception as e:
            raise ProviderError(
                f"PII redaction failed: {e}",
                provider="accent_redaction",
                operation="pii_redaction",
                original_error=e,
            ) from e

    async def redact_transcript_segments(
        self,
        segments: list[dict[str, Any]],
        entity_types: list[str] | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> PIIRedactionResult:
        """Redact PII in transcript segments.

        Args:
            segments: List of transcript segments with text, start, end, speaker
            entity_types: Entity types to redact
            **kwargs: Additional parameters

        Returns:
            PIIRedactionResult with redacted segments

        Raises:
            ProviderError: If redaction fails
        """
        try:
            # Prepare request
            payload = {
                "segments": segments,
                "options": {
                    "entities": entity_types or self.default_entity_types,
                    "confidence_threshold": self.confidence_threshold,
                    "redaction_method": self.redaction_method,
                    "return_entities": True,
                    "preserve_formatting": True,
                },
            }

            # Call process endpoint
            response = await self.client.post("/api/v1/pii/process", json=payload)
            response.raise_for_status()

            data = response.json()

            # Parse entities
            entities = []
            for entity_data in data.get("pii_entities", []):
                entities.append(
                    PIIEntity(
                        type=entity_data["type"],
                        text=entity_data["text"],
                        start=entity_data["start"],
                        end=entity_data["end"],
                        score=entity_data["score"],
                        anonymized_text=entity_data.get("anonymized_text"),
                    )
                )

            # Get redacted text (combined from segments)
            redacted_text = data.get("anonymized_text", "")

            # Build original text from segments
            original_text = " ".join(seg.get("text", "") for seg in segments)

            return PIIRedactionResult(
                original_text=original_text,
                redacted_text=redacted_text,
                entities=entities,
                redaction_map=None,
                provider_metadata={
                    "anonymized_segments": data.get("anonymized_segments"),
                    "processing_time": data.get("processing_time"),
                    "service": "accent-redaction",
                },
            )

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Transcript redaction failed with status {e.response.status_code}: {e.response.text}",
                provider="accent_redaction",
                operation="transcript_redaction",
                original_error=e,
            ) from e
        except Exception as e:
            raise ProviderError(
                f"Transcript redaction failed: {e}",
                provider="accent_redaction",
                operation="transcript_redaction",
                original_error=e,
            ) from e

    def get_supported_entity_types(self) -> list[str]:
        """Get list of supported PII entity types.

        Returns:
            List of entity type names
        """
        # Based on accent-redaction implementation
        return [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "US_SSN",
            "US_PASSPORT",
            "MEDICAL_LICENSE",
            "IP_ADDRESS",
            "LOCATION",
            "DATE_TIME",
            "US_DRIVER_LICENSE",
            "US_BANK_NUMBER",
            "CRYPTO",
            "URL",
            "AGE",
        ]

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> AccentRedactionProvider:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
