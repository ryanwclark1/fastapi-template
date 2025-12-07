"""Multi-tenancy database utilities and mixins.

This module provides:
- Tenant-aware model mixins
- Automatic tenant filtering for queries
- Tenant isolation at the database level
- Support for shared schema and separate schema strategies
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, Index, String, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_mixin, declared_attr

from example_service.app.middleware.tenant import get_tenant_context

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.engine import Result
    from sqlalchemy.sql import Executable

logger = logging.getLogger(__name__)


@declarative_mixin
class TenantMixin:
    """Mixin for tenant-aware models.

    This mixin adds a tenant_id column and automatic filtering
    for all queries on the model.

    Example:
        class Post(Base, TenantMixin, TimestampMixin):
            __tablename__ = "posts"

            id = Column(Integer, primary_key=True)
            title = Column(String(255), nullable=False)
            # tenant_id column added automatically

        # Queries are automatically filtered by tenant
        posts = await session.execute(
            select(Post).where(Post.title.like("%search%"))
        )
        # Only posts for current tenant are returned
    """

    @declared_attr
    def tenant_id(cls) -> Column:
        """Tenant identifier column.

        Returns:
            SQLAlchemy Column for tenant_id
        """
        return Column(
            String(255),
            nullable=False,
            index=True,
            comment="Tenant identifier for data isolation",
        )

    @declared_attr  # type: ignore[arg-type]
    def __table_args__(cls) -> tuple[Any, ...]:
        """Add composite index on tenant_id and primary key.

        Returns:
            Table arguments tuple
        """
        # Get existing table args
        existing_args = getattr(cls, "__table_args__", None)

        # Build new index
        tablename = getattr(cls, "__tablename__", None)
        if tablename is None:
            return existing_args or ()
        index_name = f"ix_{tablename}_tenant_id_id"
        new_index = Index(index_name, "tenant_id", "id")

        # Combine with existing args
        if existing_args:
            if isinstance(existing_args, dict):
                return (new_index, existing_args)
            if isinstance(existing_args, tuple):
                return (*existing_args, new_index)

        return (new_index,)


class TenantAwareSession(AsyncSession):
    """Async session with automatic tenant filtering.

    This session automatically adds tenant_id filters to all queries
    for models that use TenantMixin.

    Example:
        async with TenantAwareSession(engine) as session:
            # This query will be automatically filtered by tenant_id
            posts = await session.execute(select(Post))
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize tenant-aware session."""
        super().__init__(*args, **kwargs)
        self._tenant_id: str | None = None

        # Get tenant from context
        context = get_tenant_context()
        if context:
            self._tenant_id = context.tenant_id

    async def execute(
        self,
        statement: Executable,
        params: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        *,
        execution_options: Mapping[str, Any] | None = None,
        bind_arguments: dict[str, Any] | None = None,
        _parent_execute_state: Any | None = None,
        _add_event: Any | None = None,
        **kwargs: Any,
    ) -> Result[Any]:
        """Execute statement with automatic tenant filtering.

        Args:
            statement: SQL statement to execute
            *args: Additional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Query result
        """
        # Add tenant filter if applicable
        statement = self._add_tenant_filter(statement)
        if execution_options is None:
            return await super().execute(
                statement,
                params=params,
                bind_arguments=bind_arguments,
                _parent_execute_state=_parent_execute_state,
                _add_event=_add_event,
                **kwargs,
            )

        return await super().execute(
            statement,
            params=params,
            execution_options=execution_options,
            bind_arguments=bind_arguments,
            _parent_execute_state=_parent_execute_state,
            _add_event=_add_event,
            **kwargs,
        )

    def _add_tenant_filter(self, statement: Any) -> Any:
        """Add tenant filter to SELECT statement.

        Args:
            statement: SELECT statement

        Returns:
            Modified statement with tenant filter
        """
        if not self._tenant_id or not hasattr(statement, "column_descriptions"):
            return statement

        # Check if statement queries a tenant-aware model
        for desc in statement.column_descriptions:
            entity = desc.get("entity")
            if entity and hasattr(entity, "tenant_id"):
                statement = statement.where(entity.tenant_id == self._tenant_id)
                logger.debug(
                    "Added tenant filter to query",
                    extra={"tenant_id": self._tenant_id, "entity": entity.__name__},
                )

        return statement


def set_tenant_on_insert(mapper: Any, connection: Any, target: Any) -> None:  # noqa: ARG001
    """SQLAlchemy event listener to set tenant_id on insert.

    This event listener automatically sets the tenant_id column
    when a new record is inserted.

    Args:
        mapper: SQLAlchemy mapper (required by SQLAlchemy event protocol)
        connection: Database connection (required by SQLAlchemy event protocol)
        target: Model instance being inserted
    """
    if hasattr(target, "tenant_id") and not target.tenant_id:
        context = get_tenant_context()
        if context:
            target.tenant_id = context.tenant_id
            logger.debug(
                "Auto-set tenant_id on insert",
                extra={
                    "tenant_id": context.tenant_id,
                    "model": target.__class__.__name__,
                },
            )
        else:
            raise ValueError(
                f"Cannot insert {target.__class__.__name__} without tenant context. "
                "Either set tenant_id manually or ensure tenant middleware is active."
            )


def validate_tenant_on_update(mapper: Any, connection: Any, target: Any) -> None:  # noqa: ARG001
    """SQLAlchemy event listener to prevent tenant_id changes.

    This event listener prevents accidental tenant_id modifications
    which could lead to data leaks across tenants.

    Args:
        mapper: SQLAlchemy mapper (required by SQLAlchemy event protocol)
        connection: Database connection (required by SQLAlchemy event protocol)
        target: Model instance being updated
    """
    if hasattr(target, "tenant_id"):
        # Get original tenant_id
        history = mapper.get_property("tenant_id").impl.get_history(target, mapper)

        if history.deleted:
            original_tenant_id = history.deleted[0]
            current_tenant_id = target.tenant_id

            if original_tenant_id != current_tenant_id:
                raise ValueError(
                    f"Cannot change tenant_id from {original_tenant_id} to {current_tenant_id}. "
                    "Tenant changes are not allowed for data integrity."
                )


def register_tenant_events(base_class: type) -> None:
    """Register tenant-related SQLAlchemy events.

    This function registers event listeners for all models that use TenantMixin.
    Call this once after defining all models.

    Args:
        base_class: SQLAlchemy declarative base class

    Example:
        from example_service.core.database import Base
        from example_service.core.database.tenancy import register_tenant_events

        # After defining all models
        register_tenant_events(Base)
    """
    registry = getattr(base_class, "registry", None)
    if registry is None:
        return
    mappers = getattr(registry, "mappers", [])
    for mapper in mappers:
        model_class = mapper.class_

        # Check if model has tenant_id column
        if hasattr(model_class, "tenant_id"):
            # Register insert event
            event.listen(model_class, "before_insert", set_tenant_on_insert)

            # Register update event
            event.listen(model_class, "before_update", validate_tenant_on_update)

            logger.debug("Registered tenant events for %s", model_class.__name__)


async def create_tenant_schema(tenant_id: str, session: AsyncSession) -> None:
    """Create a separate PostgreSQL schema for a tenant.

    This function creates a dedicated schema for a tenant when using
    the "separate schema" multi-tenancy strategy.

    Args:
        tenant_id: Tenant identifier
        session: Database session

    Example:
        await create_tenant_schema("acme-corp", session)
        # Creates schema: tenant_acme_corp
    """
    # Sanitize tenant_id for schema name
    schema_name = f"tenant_{tenant_id.replace('-', '_')}"

    # Check if schema exists
    result = await session.execute(
        text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema_name"
        ),
        {"schema_name": schema_name},
    )

    if result.scalar():
        logger.info("Schema %s already exists", schema_name)
        return

    # Create schema
    await session.execute(text(f"CREATE SCHEMA {schema_name}"))
    await session.commit()

    logger.info("Created tenant schema: %s", schema_name)


async def drop_tenant_schema(tenant_id: str, session: AsyncSession) -> None:
    """Drop a tenant's PostgreSQL schema.

    WARNING: This permanently deletes all tenant data!

    Args:
        tenant_id: Tenant identifier
        session: Database session
    """
    schema_name = f"tenant_{tenant_id.replace('-', '_')}"

    await session.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
    await session.commit()

    logger.warning("Dropped tenant schema: %s", schema_name)


def get_tenant_filter(model_class: type, tenant_id: str | None = None) -> Any:
    """Get SQLAlchemy filter expression for tenant.

    Args:
        model_class: Model class with TenantMixin
        tenant_id: Tenant ID (uses context if not provided)

    Returns:
        SQLAlchemy filter expression

    Example:
        tenant_filter = get_tenant_filter(Post)
        posts = await session.execute(
            select(Post).where(tenant_filter)
        )
    """
    if not hasattr(model_class, "tenant_id"):
        raise ValueError(f"{model_class.__name__} does not have tenant_id column")

    # Get tenant ID from context if not provided
    if not tenant_id:
        context = get_tenant_context()
        if not context:
            msg = "No tenant context available and tenant_id not provided"
            raise ValueError(msg)
        tenant_id = context.tenant_id

    return model_class.tenant_id == tenant_id


class TenantIsolationError(Exception):
    """Raised when tenant isolation is violated."""
