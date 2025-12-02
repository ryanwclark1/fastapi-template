"""Query complexity limiting extension for GraphQL operations.

Prevents expensive queries from overloading the server by calculating and limiting
the complexity score of each operation. Complexity is calculated based on query depth,
field count, and list multipliers.

Usage:
    from example_service.features.graphql.extensions.complexity_limiter import ComplexityLimiter

    extensions = [
        QueryDepthLimiter(max_depth=10),  # Basic depth check
        ComplexityLimiter(max_complexity=1000),  # Complexity scoring
        GraphQLRateLimiter(),
    ]
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from graphql import GraphQLError
from graphql.language import (
    FieldNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    OperationDefinitionNode,
)
from graphql.type import GraphQLList, GraphQLObjectType
from strawberry.extensions import SchemaExtension

logger = logging.getLogger(__name__)

__all__ = ["ComplexityConfig", "ComplexityLimiter"]


class ComplexityConfig:
    """Configuration for complexity calculation.

    Provides customizable complexity scoring rules.
    """

    # Base costs
    FIELD_COST = 1  # Cost per field
    OBJECT_COST = 1  # Cost per object type
    LIST_COST = 10  # Cost multiplier for list fields
    CONNECTION_COST = 10  # Cost multiplier for Relay connections

    # Max limits
    DEFAULT_MAX_COMPLEXITY = 1000
    DEFAULT_MAX_DEPTH = 10

    # Field-specific costs (can be customized per field)
    EXPENSIVE_FIELDS: ClassVar[dict[str, int]] = {
        "search": 20,  # Search operations are expensive
        "export": 50,  # Export operations are very expensive
        "aggregate": 15,  # Aggregations are expensive
        "analyze": 25,  # Analysis operations are expensive
    }


class ComplexityLimiter(SchemaExtension):
    """Limit GraphQL query complexity to prevent expensive operations.

    This extension calculates a complexity score for each operation based on:
    - Query depth (nested levels)
    - Field count (total fields requested)
    - List multipliers (lists increase complexity)
    - Custom field costs (expensive operations)

    The complexity score is calculated before execution and queries exceeding
    the limit are rejected with a COMPLEXITY_LIMIT_EXCEEDED error.

    Example complexity calculation:
        query {
            reminders(first: 50) {      # List multiplier: 50x
                edges {                  # +1 field
                    node {               # +1 field
                        id               # +1 field
                        title            # +1 field
                        tags {           # List (unknown size): 10x
                            name         # +1 field
                        }
                    }
                }
            }
        }
        # Complexity: 50 * (1 + 1 + 1 + 1 + 10 * 1) = 50 * 15 = 750

    Example:
        schema = strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=[
                ComplexityLimiter(max_complexity=1000, max_depth=10),
            ],
        )
    """

    def __init__(
        self,
        max_complexity: int | None = None,
        max_depth: int | None = None,
        config: ComplexityConfig | None = None,
    ):
        """Initialize complexity limiter.

        Args:
            max_complexity: Maximum allowed complexity score (default: 1000)
            max_depth: Maximum query depth (default: 10)
            config: Custom complexity configuration
        """
        self.max_complexity = max_complexity or ComplexityConfig.DEFAULT_MAX_COMPLEXITY
        self.max_depth = max_depth or ComplexityConfig.DEFAULT_MAX_DEPTH
        self.config = config or ComplexityConfig()

    def on_execute(self) -> None:
        """Check complexity before executing operation.

        This hook runs before query execution and can reject the operation
        if complexity limits are exceeded.

        Raises:
            GraphQLError: If complexity or depth limit is exceeded
        """
        execution_context = self.execution_context

        # Get operation
        operation = execution_context.operation
        if not operation:
            return

        # Get operation type
        operation_type = execution_context.operation_type
        if not operation_type:
            return

        # Skip complexity checks for introspection queries
        if self._is_introspection_query(operation):
            return

        try:
            # Calculate complexity
            complexity_score, max_depth = self._calculate_complexity(operation)

            # Check depth limit
            if max_depth > self.max_depth:
                logger.warning(
                    "GraphQL query depth exceeded",
                    extra={
                        "operation_type": operation_type,
                        "operation_name": execution_context.operation_name,
                        "max_depth": max_depth,
                        "limit": self.max_depth,
                    },
                )
                raise GraphQLError(
                    f"Query depth {max_depth} exceeds limit of {self.max_depth}",
                    extensions={
                        "code": "DEPTH_LIMIT_EXCEEDED",
                        "max_depth": max_depth,
                        "limit": self.max_depth,
                    },
                )

            # Check complexity limit
            if complexity_score > self.max_complexity:
                logger.warning(
                    "GraphQL query complexity exceeded",
                    extra={
                        "operation_type": operation_type,
                        "operation_name": execution_context.operation_name,
                        "complexity": complexity_score,
                        "limit": self.max_complexity,
                    },
                )
                raise GraphQLError(
                    f"Query complexity {complexity_score} exceeds limit of {self.max_complexity}",
                    extensions={
                        "code": "COMPLEXITY_LIMIT_EXCEEDED",
                        "complexity": complexity_score,
                        "limit": self.max_complexity,
                    },
                )

            # Log complexity for monitoring
            logger.debug(
                "GraphQL query complexity",
                extra={
                    "operation_type": operation_type,
                    "operation_name": execution_context.operation_name,
                    "complexity": complexity_score,
                    "depth": max_depth,
                },
            )

        except GraphQLError:
            raise
        except Exception as e:
            # Don't fail the operation if complexity calculation has issues
            logger.error(
                "Complexity calculation failed",
                extra={
                    "error": str(e),
                    "operation_type": operation_type,
                    "operation_name": execution_context.operation_name,
                },
            )

    def _is_introspection_query(self, operation: OperationDefinitionNode) -> bool:
        """Check if this is an introspection query.

        Introspection queries are used by tools and should not be rate limited.

        Args:
            operation: GraphQL operation

        Returns:
            True if this is an introspection query
        """
        # Check if query contains __schema or __type fields
        for selection in operation.selection_set.selections:
            if isinstance(selection, FieldNode) and selection.name.value.startswith("__"):
                return True
        return False

    def _calculate_complexity(self, operation: OperationDefinitionNode) -> tuple[int, int]:
        """Calculate complexity score and max depth for an operation.

        Args:
            operation: GraphQL operation to analyze

        Returns:
            Tuple of (complexity_score, max_depth)
        """
        # Get schema and type info
        schema = self.execution_context.schema
        operation_type = schema.query_type  # Default to query type

        if operation.operation.value == "mutation":
            operation_type = schema.mutation_type
        elif operation.operation.value == "subscription":
            operation_type = schema.subscription_type

        if not operation_type:
            return 0, 0

        # Calculate complexity for all selections
        complexity, depth = self._calculate_selection_set_complexity(
            operation.selection_set.selections,
            operation_type,
            depth=1,
            multiplier=1,
        )

        return complexity, depth

    def _calculate_selection_set_complexity(
        self,
        selections: Any,
        parent_type: GraphQLObjectType,
        depth: int,
        multiplier: int,
    ) -> tuple[int, int]:
        """Calculate complexity for a selection set.

        Args:
            selections: Field selections
            parent_type: Parent GraphQL type
            depth: Current depth level
            multiplier: Current multiplier (from parent lists)

        Returns:
            Tuple of (complexity_score, max_depth)
        """
        total_complexity = 0
        max_depth = depth

        for selection in selections:
            if isinstance(selection, FieldNode):
                field_complexity, field_depth = self._calculate_field_complexity(
                    selection, parent_type, depth, multiplier
                )
                total_complexity += field_complexity
                max_depth = max(max_depth, field_depth)

            elif isinstance(selection, InlineFragmentNode):
                # Handle inline fragments
                if selection.selection_set:
                    fragment_complexity, fragment_depth = self._calculate_selection_set_complexity(
                        selection.selection_set.selections,
                        parent_type,
                        depth,
                        multiplier,
                    )
                    total_complexity += fragment_complexity
                    max_depth = max(max_depth, fragment_depth)

            elif isinstance(selection, FragmentSpreadNode):
                # Handle fragment spreads (would need fragment definitions)
                # For now, add a base cost
                total_complexity += self.config.FIELD_COST * multiplier

        return total_complexity, max_depth

    def _calculate_field_complexity(
        self,
        field: FieldNode,
        parent_type: GraphQLObjectType,
        depth: int,
        multiplier: int,
    ) -> tuple[int, int]:
        """Calculate complexity for a single field.

        Args:
            field: GraphQL field node
            parent_type: Parent GraphQL type
            depth: Current depth level
            multiplier: Current multiplier (from parent lists)

        Returns:
            Tuple of (complexity_score, max_depth)
        """
        field_name = field.name.value

        # Base field cost
        field_cost = self.config.FIELD_COST

        # Add custom cost for expensive fields
        if field_name in self.config.EXPENSIVE_FIELDS:
            field_cost = self.config.EXPENSIVE_FIELDS[field_name]

        # Get field type from schema
        field_type = None
        if hasattr(parent_type, "fields") and field_name in parent_type.fields:
            field_type = parent_type.fields[field_name].type

        # Calculate list multiplier
        field_multiplier = multiplier
        if field_type and isinstance(field_type, GraphQLList):
            # Check for list size arguments
            list_size = self._get_list_size(field)
            field_multiplier *= list_size

        # Apply multiplier to field cost
        complexity = field_cost * field_multiplier

        # Calculate nested complexity
        max_depth = depth
        if field.selection_set:
            # Get inner type for nested calculations
            inner_type = self._get_inner_type(field_type) if field_type else None

            if inner_type and isinstance(inner_type, GraphQLObjectType):
                nested_complexity, nested_depth = self._calculate_selection_set_complexity(
                    field.selection_set.selections,
                    inner_type,
                    depth + 1,
                    field_multiplier,
                )
                complexity += nested_complexity
                max_depth = max(max_depth, nested_depth)

        return complexity, max_depth

    def _get_list_size(self, field: FieldNode) -> int:
        """Get list size from field arguments.

        Looks for 'first', 'last', or 'limit' arguments to determine list size.

        Args:
            field: GraphQL field node

        Returns:
            List size (defaults to LIST_COST if not specified)
        """
        if not field.arguments:
            return self.config.LIST_COST

        for arg in field.arguments:
            if arg.name.value in ("first", "last", "limit") and hasattr(arg.value, "value"):
                # Get the value
                return min(int(arg.value.value), self.config.LIST_COST * 10)

        return self.config.LIST_COST

    def _get_inner_type(self, field_type: Any) -> Any:
        """Unwrap GraphQL type to get inner type.

        Handles List, NonNull wrappers.

        Args:
            field_type: GraphQL type

        Returns:
            Innermost type
        """
        while hasattr(field_type, "of_type"):
            field_type = field_type.of_type
        return field_type


# ============================================================================
# Usage Examples
# ============================================================================

"""
Example: Basic usage with default limits
    from example_service.features.graphql.extensions.complexity_limiter import ComplexityLimiter

    extensions = [
        ComplexityLimiter(),  # 1000 max complexity, 10 max depth
    ]

Example: Custom limits
    extensions = [
        ComplexityLimiter(
            max_complexity=5000,  # Allow more complex queries
            max_depth=15,  # Allow deeper nesting
        ),
    ]

Example: Custom field costs
    from example_service.features.graphql.extensions.complexity_limiter import (
        ComplexityConfig,
        ComplexityLimiter,
    )

    config = ComplexityConfig()
    config.EXPENSIVE_FIELDS = {
        "search": 50,  # Increase cost of search
        "export": 100,  # Very expensive
        "analytics": 75,  # Custom expensive operation
    }

    extensions = [
        ComplexityLimiter(config=config),
    ]

Example: Client error handling
    # When complexity limit is exceeded, client receives:
    {
        "errors": [{
            "message": "Query complexity 1500 exceeds limit of 1000",
            "extensions": {
                "code": "COMPLEXITY_LIMIT_EXCEEDED",
                "complexity": 1500,
                "limit": 1000
            }
        }]
    }

    # Client should reduce query complexity by:
    # - Reducing the 'first' argument on connections
    # - Requesting fewer fields
    # - Reducing nesting depth
    # - Splitting into multiple smaller queries

Example: Combined with other extensions
    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        extensions=[
            QueryDepthLimiter(max_depth=10),  # Basic depth check
            ComplexityLimiter(max_complexity=1000),  # Complexity scoring
            GraphQLRateLimiter(),  # Rate limiting
        ],
        process_errors=process_graphql_errors,  # Error handling
    )

Note: Complexity calculation is approximate and may not catch all expensive queries.
It's designed as a first line of defense against obviously expensive operations.

For production use, combine with:
- Rate limiting (GraphQLRateLimiter)
- Request timeouts
- Query cost analysis from real usage patterns
- Monitoring and alerting on query performance
"""
