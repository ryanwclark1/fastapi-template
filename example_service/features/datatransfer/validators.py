"""Entity-specific validators for data transfer operations.

Provides a registry of validators for different entity types with
custom validation logic that goes beyond basic type checking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class ValidationError:
    """Represents a validation error."""

    def __init__(
        self,
        field: str,
        message: str,
        value: Any = None,
        code: str | None = None,
    ) -> None:
        """Initialize validation error.

        Args:
            field: Field that failed validation.
            message: Error message.
            value: The invalid value.
            code: Error code for programmatic handling.
        """
        self.field = field
        self.message = message
        self.value = value
        self.code = code or "validation_error"

    def __repr__(self) -> str:
        return f"ValidationError(field={self.field}, message={self.message})"


class ValidationResult:
    """Result of validation operation."""

    def __init__(self) -> None:
        self.errors: list[ValidationError] = []
        self.warnings: list[str] = []
        self.transformed_data: dict[str, Any] | None = None

    @property
    def is_valid(self) -> bool:
        """Check if validation passed."""
        return len(self.errors) == 0

    def add_error(
        self,
        field: str,
        message: str,
        value: Any = None,
        code: str | None = None,
    ) -> None:
        """Add a validation error."""
        self.errors.append(ValidationError(field, message, value, code))

    def add_warning(self, message: str) -> None:
        """Add a validation warning."""
        self.warnings.append(message)


class EntityValidator(ABC):
    """Base class for entity-specific validators.

    Implement this class to provide custom validation logic for
    specific entity types during import operations.

    Example:
        class ReminderValidator(EntityValidator):
            def validate(self, data: dict) -> ValidationResult:
                result = ValidationResult()

                # Check remind_at is in the future
                remind_at = data.get("remind_at")
                if remind_at and remind_at < datetime.now(UTC):
                    result.add_error(
                        "remind_at",
                        "Reminder date must be in the future",
                        remind_at,
                        "future_date_required",
                    )

                return result
    """

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """Return the entity type this validator handles."""

    @abstractmethod
    def validate(self, data: dict[str, Any]) -> ValidationResult:
        """Validate a single record.

        Args:
            data: Record data to validate.

        Returns:
            ValidationResult with any errors or warnings.
        """

    def pre_process(self, data: dict[str, Any]) -> dict[str, Any]:
        """Pre-process data before validation.

        Override to transform or normalize data before validation.

        Args:
            data: Raw record data.

        Returns:
            Pre-processed data.
        """
        return data

    def post_process(self, data: dict[str, Any]) -> dict[str, Any]:
        """Post-process data after validation.

        Override to transform data after validation passes.

        Args:
            data: Validated record data.

        Returns:
            Post-processed data ready for import.
        """
        return data


class ReminderValidator(EntityValidator):
    """Validator for reminder entity imports."""

    @property
    def entity_type(self) -> str:
        return "reminders"

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        # Validate title length
        title = data.get("title")
        if title:
            if len(title) < 1:
                result.add_error("title", "Title cannot be empty", title, "min_length")
            elif len(title) > 500:
                result.add_error(
                    "title",
                    "Title cannot exceed 500 characters",
                    title,
                    "max_length",
                )

        # Validate description length
        description = data.get("description")
        if description and len(description) > 5000:
            result.add_error(
                "description",
                "Description cannot exceed 5000 characters",
                description,
                "max_length",
            )

        # Validate remind_at is in the future (for new reminders)
        remind_at = data.get("remind_at")
        if remind_at:
            if isinstance(remind_at, str):
                try:
                    remind_at = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
                except ValueError:
                    result.add_error(
                        "remind_at",
                        "Invalid datetime format",
                        remind_at,
                        "invalid_format",
                    )
                    return result

            if remind_at < datetime.now(UTC):
                result.add_warning(
                    f"Reminder date {remind_at} is in the past"
                )

        return result


class WebhookValidator(EntityValidator):
    """Validator for webhook entity imports."""

    # URL pattern for basic validation
    URL_PATTERN = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"  # domain
        r"[A-Z]{2,6}\.?|"  # top-level domain
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # or ipv4
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",  # path
        re.IGNORECASE,
    )

    @property
    def entity_type(self) -> str:
        return "webhooks"

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        # Validate name
        name = data.get("name")
        if name:
            if len(name) < 1:
                result.add_error("name", "Name cannot be empty", name, "min_length")
            elif len(name) > 255:
                result.add_error(
                    "name",
                    "Name cannot exceed 255 characters",
                    name,
                    "max_length",
                )

        # Validate URL format
        url = data.get("url")
        if url:
            if not self.URL_PATTERN.match(url):
                result.add_error(
                    "url",
                    "Invalid URL format. Must be a valid HTTP/HTTPS URL.",
                    url,
                    "invalid_url",
                )

            # Security: block internal URLs
            if url and any(
                internal in url.lower()
                for internal in ["localhost", "127.0.0.1", "0.0.0.0", "internal"]
            ):
                result.add_warning(
                    f"URL '{url}' appears to point to an internal address"
                )

        # Validate events is a list
        events = data.get("events")
        if events is not None and not isinstance(events, list):
            result.add_error(
                "events",
                "Events must be a list",
                events,
                "invalid_type",
            )

        return result


class ValidatorRegistry:
    """Registry for entity validators.

    Manages registration and retrieval of entity-specific validators.

    Example:
        registry = ValidatorRegistry()
        registry.register(ReminderValidator())

        validator = registry.get("reminders")
        if validator:
            result = validator.validate(data)
    """

    def __init__(self) -> None:
        self._validators: dict[str, EntityValidator] = {}

    def register(self, validator: EntityValidator) -> None:
        """Register a validator for an entity type.

        Args:
            validator: Validator instance to register.
        """
        self._validators[validator.entity_type] = validator
        logger.debug("Registered validator for entity type: %s", validator.entity_type)

    def get(self, entity_type: str) -> EntityValidator | None:
        """Get validator for an entity type.

        Args:
            entity_type: Entity type name.

        Returns:
            Validator if registered, None otherwise.
        """
        return self._validators.get(entity_type)

    def has_validator(self, entity_type: str) -> bool:
        """Check if a validator is registered for an entity type.

        Args:
            entity_type: Entity type name.

        Returns:
            True if validator exists.
        """
        return entity_type in self._validators

    def list_validators(self) -> list[str]:
        """Get list of entity types with registered validators.

        Returns:
            List of entity type names.
        """
        return list(self._validators.keys())


# Global validator registry
_validator_registry: ValidatorRegistry | None = None


def get_validator_registry() -> ValidatorRegistry:
    """Get the global validator registry.

    Initializes with default validators on first call.

    Returns:
        ValidatorRegistry instance.
    """
    global _validator_registry
    if _validator_registry is None:
        _validator_registry = ValidatorRegistry()
        # Register built-in validators
        _validator_registry.register(ReminderValidator())
        _validator_registry.register(WebhookValidator())
    return _validator_registry


def validate_entity(
    entity_type: str,
    data: dict[str, Any],
) -> ValidationResult:
    """Validate entity data using registered validator.

    Args:
        entity_type: Type of entity.
        data: Record data to validate.

    Returns:
        ValidationResult (always valid if no validator registered).
    """
    registry = get_validator_registry()
    validator = registry.get(entity_type)

    if validator is None:
        # No custom validator, return valid result
        return ValidationResult()

    # Pre-process
    processed_data = validator.pre_process(data)

    # Validate
    result = validator.validate(processed_data)

    # Store transformed data if validation passed
    if result.is_valid:
        result.transformed_data = validator.post_process(processed_data)

    return result


def register_validator(validator: EntityValidator) -> None:
    """Register a custom validator.

    Args:
        validator: Validator instance to register.
    """
    registry = get_validator_registry()
    registry.register(validator)


def create_validator(
    entity_type: str,
    validate_fn: Callable[[dict[str, Any]], ValidationResult],
) -> EntityValidator:
    """Create a simple validator from a function.

    Args:
        entity_type: Entity type name.
        validate_fn: Validation function.

    Returns:
        EntityValidator instance.

    Example:
        def validate_custom(data):
            result = ValidationResult()
            if not data.get("required_field"):
                result.add_error("required_field", "This field is required")
            return result

        validator = create_validator("custom_entity", validate_custom)
        register_validator(validator)
    """

    class FunctionalValidator(EntityValidator):
        @property
        def entity_type(self) -> str:
            return entity_type

        def validate(self, data: dict[str, Any]) -> ValidationResult:
            return validate_fn(data)

    return FunctionalValidator()
