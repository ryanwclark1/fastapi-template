"""Enum types with human-readable labels for UI generation.

Provides labeled enum types that can be used both in database columns
and for generating form choices. Each enum value has an associated
human-readable label.

Example:
    >>> from example_service.core.database.choices import LabeledStrEnum, ChoiceType
    >>>
    >>> class OrderStatus(LabeledStrEnum):
    ...     PENDING = "pending"
    ...     PROCESSING = "processing"
    ...     SHIPPED = "shipped"
    ...     DELIVERED = "delivered"
    ...
    ...     _labels = {
    ...         "pending": "Awaiting Processing",
    ...         "processing": "In Progress",
    ...         "shipped": "On Its Way",
    ...         "delivered": "Successfully Delivered",
    ...     }
    >>>
    >>> # Access labels
    >>> OrderStatus.PENDING.label
    'Awaiting Processing'
    >>>
    >>> # Generate form choices
    >>> OrderStatus.choices()
    [('pending', 'Awaiting Processing'), ('processing', 'In Progress'), ...]
    >>>
    >>> # Use in model
    >>> class Order(Base, IntegerPKMixin):
    ...     status: Mapped[str] = mapped_column(
    ...         ChoiceType(OrderStatus),
    ...         default=OrderStatus.PENDING,
    ...     )
"""

from __future__ import annotations

from enum import Enum, IntEnum, StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from sqlalchemy import Integer, String
from sqlalchemy.types import TypeDecorator

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Self

    from sqlalchemy.engine import Dialect

T = TypeVar("T")


class LabeledChoiceMixin:
    """Mixin for enums with human-readable labels.

    Provides label support for enums used in database columns.
    Subclasses should define a `_labels` class variable mapping
    values to human-readable labels.

    If no label is defined for a value, a default label is generated
    by converting the enum name to title case with underscores replaced.

    Example:
        >>> class Status(LabeledChoiceMixin, StrEnum):
        ...     DRAFT = "draft"
        ...     IN_PROGRESS = "in_progress"
        ...     COMPLETED = "completed"
        ...
        ...     _labels = {
        ...         "draft": "Draft",
        ...         "in_progress": "In Progress",
        ...         "completed": "Completed",
        ...     }
        >>>
        >>> Status.DRAFT.label
        'Draft'
        >>> Status.choices()
        [('draft', 'Draft'), ('in_progress', 'In Progress'), ('completed', 'Completed')]
    """

    # Override in subclass to define labels
    _labels: ClassVar[dict[Any, str]] = {}

    @property
    def label(self) -> str:
        """Get human-readable label for this choice.

        Returns:
            Label from _labels dict, or auto-generated from name
        """
        # First try value-based lookup
        if self.value in self._labels:  # type: ignore[attr-defined]
            return self._labels[self.value]  # type: ignore[attr-defined]

        # Fall back to name-based auto-generation
        return str(self.name).replace("_", " ").title()  # type: ignore[attr-defined]

    @classmethod
    def choices(cls) -> list[tuple[Any, str]]:
        """Return list of (value, label) tuples for form generation.

        Returns:
            List of tuples suitable for HTML select options

        Example:
            >>> Status.choices()
            [('draft', 'Draft'), ('in_progress', 'In Progress')]
        """
        return [(member.value, member.label) for member in cls]  # type: ignore[attr-defined]

    @classmethod
    def from_label(cls, label: str) -> Self | None:
        """Find enum member by label (case-insensitive).

        Args:
            label: Human-readable label to search for

        Returns:
            Enum member with matching label, or None

        Example:
            >>> Status.from_label("In Progress")
            Status.IN_PROGRESS
        """
        label_lower = label.lower()
        for member in cls:  # type: ignore[attr-defined]
            if member.label.lower() == label_lower:
                return member  # type: ignore[no-any-return]
        return None

    @classmethod
    def values(cls) -> list[Any]:
        """Return list of all enum values.

        Returns:
            List of raw enum values
        """
        return [member.value for member in cls]  # type: ignore[attr-defined]

    @classmethod
    def labels(cls) -> list[str]:
        """Return list of all labels.

        Returns:
            List of human-readable labels
        """
        return [member.label for member in cls]  # type: ignore[attr-defined]

    @classmethod
    def from_value(cls, value: Any) -> Self | None:
        """Find enum member by value.

        Args:
            value: Raw value to search for

        Returns:
            Enum member with matching value, or None
        """
        for member in cls:  # type: ignore[attr-defined]
            if member.value == value:
                return member  # type: ignore[no-any-return]
        return None


class LabeledStrEnum(LabeledChoiceMixin, StrEnum):
    """String enum with label support.

    Combines StrEnum (for string values) with LabeledChoiceMixin
    (for human-readable labels). Use when database stores string values.

    Note: Define labels using __labels__ (double underscore) to avoid
    enum member detection, or define labels after class creation.

    Example:
        >>> class Priority(LabeledStrEnum):
        ...     LOW = "low"
        ...     MEDIUM = "medium"
        ...     HIGH = "high"
        ...     URGENT = "urgent"
        >>>
        >>> # Define labels after class creation
        >>> Priority.__labels__ = {
        ...     "low": "Low Priority",
        ...     "medium": "Medium Priority",
        ...     "high": "High Priority",
        ...     "urgent": "Urgent - Immediate Action Required",
        ... }
        >>>
        >>> Priority.HIGH.label
        'High Priority'
        >>> str(Priority.HIGH)
        'high'

    Alternative using decorator:
        >>> @with_labels({
        ...     "low": "Low Priority",
        ...     "medium": "Medium Priority",
        ... })
        >>> class Priority(LabeledStrEnum):
        ...     LOW = "low"
        ...     MEDIUM = "medium"
    """

    # Use _ignore_ to exclude _labels from enum members
    _ignore_: ClassVar[list[str]] = ["_labels"]  # type: ignore[misc]
    # _labels is defined in base class as ClassVar[dict[Any, str]]
    # For StrEnum, we want dict[str, str], but Enum doesn't allow overriding
    # We'll use a type ignore to suppress the error
    _labels: ClassVar[dict[str, str]] = {}  # type: ignore[assignment,misc]


class LabeledIntEnum(LabeledChoiceMixin, IntEnum):
    """Integer enum with label support.

    Combines IntEnum (for integer values) with LabeledChoiceMixin
    (for human-readable labels). Use when database stores integer values.

    Example:
        >>> class Severity(LabeledIntEnum):
        ...     INFO = 0
        ...     WARNING = 1
        ...     ERROR = 2
        ...     CRITICAL = 3
        ...
        ...     _labels = {
        ...         0: "Informational",
        ...         1: "Warning",
        ...         2: "Error",
        ...         3: "Critical",
        ...     }
        >>>
        >>> Severity.ERROR.label
        'Error'
        >>> int(Severity.ERROR)
        2
    """

    @property
    def label(self) -> str:
        """Get human-readable label for this choice.

        Overrides base to support integer key lookup in _labels.
        """
        if self.value in self._labels:
            return self._labels[self.value]
        return str(self.name).replace("_", " ").title()


class ChoiceType(TypeDecorator[Enum]):
    """SQLAlchemy type for storing LabeledEnum values.

    Automatically converts between Python enum and database value.
    Auto-detects whether to use String or Integer storage based on
    the enum class (IntEnum vs StrEnum).

    Example:
        >>> class Order(Base, IntegerPKMixin):
        ...     __tablename__ = "orders"
        ...     status: Mapped[OrderStatus] = mapped_column(
        ...         ChoiceType(OrderStatus),
        ...         default=OrderStatus.PENDING,
        ...     )
        >>>
        >>> # Query by enum
        >>> stmt = select(Order).where(Order.status == OrderStatus.SHIPPED)
        >>>
        >>> # Access label in Python
        >>> order.status.label
        'On Its Way'

    Note:
        - Stores the raw value (string or int) in database
        - Converts to enum on retrieval
        - Works with native PostgreSQL ENUM types when combined with enums.py
    """

    cache_ok = True

    def __init__(self, enum_class: type[Enum], **kwargs: Any) -> None:
        """Initialize ChoiceType.

        Args:
            enum_class: The enum class to use for conversion
            **kwargs: Additional TypeDecorator arguments
        """
        super().__init__(**kwargs)
        self.enum_class = enum_class

        # Determine implementation type based on enum base class
        if issubclass(enum_class, IntEnum):
            self.impl = Integer()
        else:
            # Get max length from enum values, minimum 50 for safety
            max_len = max(
                (len(str(m.value)) for m in enum_class),
                default=50,
            )
            self.impl = String(max(max_len, 50))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        """Convert enum to database value.

        Args:
            value: Enum instance or raw value
            dialect: Database dialect

        Returns:
            Raw value for database storage
        """
        _ = dialect
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            return value.value
        # Allow raw values to pass through
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Enum | None:
        """Convert database value to enum.

        Args:
            value: Raw value from database
            dialect: Database dialect

        Returns:
            Enum instance
        """
        _ = dialect
        if value is None:
            return None
        return self.enum_class(value)


# =============================================================================
# Convenience Functions
# =============================================================================


def create_choices(
    name: str,
    choices: dict[str, str],
    *,
    _base: type = StrEnum,
) -> type[LabeledStrEnum]:
    """Dynamically create a labeled enum class.

    Useful when enum values come from configuration or database.

    Args:
        name: Name for the enum class
        choices: Dictionary of {value: label} pairs
        base: Base enum class (default: StrEnum)

    Returns:
        New enum class with label support

    Example:
        >>> StatusEnum = create_choices("Status", {
        ...     "draft": "Draft",
        ...     "published": "Published",
        ...     "archived": "Archived",
        ... })
        >>> StatusEnum.draft.label
        'Draft'
    """
    # Create enum members from choices keys
    members = {k.upper().replace(" ", "_").replace("-", "_"): k for k in choices}

    # Create the enum class
    enum_class = LabeledStrEnum(name, members)  # type: ignore[call-arg]

    # Attach labels
    object.__setattr__(enum_class, "_labels", choices)

    return enum_class  # type: ignore[return-value]


EnumT = TypeVar("EnumT", bound=type)


def with_labels(labels: dict[Any, str]) -> Callable[[EnumT], EnumT]:
    """Decorator to add labels to a LabeledEnum class.

    Args:
        labels: Dictionary mapping enum values to human-readable labels

    Returns:
        Decorator function

    Example:
        >>> @with_labels({
        ...     "draft": "Draft Mode",
        ...     "published": "Published",
        ...     "archived": "Archived",
        ... })
        ... class Status(LabeledStrEnum):
        ...     DRAFT = "draft"
        ...     PUBLISHED = "published"
        ...     ARCHIVED = "archived"
        >>>
        >>> Status.DRAFT.label
        'Draft Mode'
    """

    def decorator(cls: EnumT) -> EnumT:
        cls._labels = labels  # type: ignore[attr-defined]
        return cls

    return decorator


__all__ = [
    "ChoiceType",
    "LabeledChoiceMixin",
    "LabeledIntEnum",
    "LabeledStrEnum",
    "create_choices",
    "with_labels",
]
