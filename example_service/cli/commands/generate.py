"""Code generation and scaffolding commands."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click

# Templates for code generation
CRUD_TEMPLATE = '''"""CRUD operations for {model_name}."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.exceptions import NotFoundException
from example_service.core.models.{model_file} import {model_class}
from example_service.core.schemas.{schema_file} import {schema_class}Create, {schema_class}Update

if TYPE_CHECKING:
    from collections.abc import Sequence


async def get_{model_var}(db: AsyncSession, {model_var}_id: int) -> {model_class}:
    """Get {model_name} by ID.

    Args:
        db: Database session
        {model_var}_id: {model_class} ID

    Returns:
        {model_class} instance

    Raises:
        NotFoundException: If {model_var} not found
    """
    result = await db.execute(
        select({model_class}).where({model_class}.id == {model_var}_id)
    )
    {model_var} = result.scalar_one_or_none()

    if not {model_var}:
        raise NotFoundException(
            detail=f"{model_class} with id {{{model_var}_id}} not found",
            instance=f"/{model_plural}/{{{model_var}_id}}",
        )

    return {model_var}


async def get_{model_plural}(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[{model_class}]:
    """Get list of {model_plural}.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of {model_class} instances
    """
    result = await db.execute(
        select({model_class}).offset(skip).limit(limit)
    )
    return result.scalars().all()


async def create_{model_var}(
    db: AsyncSession,
    {model_var}_data: {schema_class}Create,
) -> {model_class}:
    """Create new {model_var}.

    Args:
        db: Database session
        {model_var}_data: {model_class} creation data

    Returns:
        Created {model_class} instance
    """
    {model_var} = {model_class}(**{model_var}_data.model_dump())
    db.add({model_var})
    await db.commit()
    await db.refresh({model_var})
    return {model_var}


async def update_{model_var}(
    db: AsyncSession,
    {model_var}_id: int,
    {model_var}_data: {schema_class}Update,
) -> {model_class}:
    """Update existing {model_var}.

    Args:
        db: Database session
        {model_var}_id: {model_class} ID
        {model_var}_data: {model_class} update data

    Returns:
        Updated {model_class} instance

    Raises:
        NotFoundException: If {model_var} not found
    """
    {model_var} = await get_{model_var}(db, {model_var}_id)

    update_data = {model_var}_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr({model_var}, field, value)

    await db.commit()
    await db.refresh({model_var})
    return {model_var}


async def delete_{model_var}(db: AsyncSession, {model_var}_id: int) -> None:
    """Delete {model_var}.

    Args:
        db: Database session
        {model_var}_id: {model_class} ID

    Raises:
        NotFoundException: If {model_var} not found
    """
    {model_var} = await get_{model_var}(db, {model_var}_id)
    await db.delete({model_var})
    await db.commit()
'''

MODEL_TEMPLATE = '''"""SQLAlchemy model for {model_name}."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from example_service.core.models.base import Base


class {model_class}(Base):
    """SQLAlchemy model for {model_name}."""

    __tablename__ = "{table_name}"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<{model_class}(id={{self.id}}, name={{self.name!r}})>"
'''

SCHEMA_TEMPLATE = '''"""Pydantic schemas for {model_name}."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class {schema_class}Base(BaseModel):
    """Base schema for {model_name}."""

    name: str = Field(..., min_length=1, max_length=255, description="{model_class} name")
    description: str | None = Field(None, description="{model_class} description")


class {schema_class}Create({schema_class}Base):
    """Schema for creating {model_name}."""

    pass


class {schema_class}Update(BaseModel):
    """Schema for updating {model_name}."""

    name: str | None = Field(None, min_length=1, max_length=255, description="{model_class} name")
    description: str | None = Field(None, description="{model_class} description")


class {schema_class}InDB({schema_class}Base):
    """Schema for {model_name} in database."""

    id: int = Field(..., description="{model_class} ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)


class {schema_class}({schema_class}InDB):
    """Public schema for {model_name}."""

    pass
'''

ROUTER_TEMPLATE = '''"""API routes for {model_name}."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core import crud
from example_service.core.dependencies.auth import get_current_user
from example_service.core.dependencies.database import get_db
from example_service.core.dependencies.ratelimit import RateLimited
from example_service.core.models.user import User
from example_service.core.schemas.{schema_file} import (
    {schema_class},
    {schema_class}Create,
    {schema_class}Update,
)

router = APIRouter(
    prefix="/{model_plural}",
    tags=["{model_plural}"],
)


@router.get("/", response_model=list[{schema_class}])
async def list_{model_plural}(
    _rate_limit: RateLimited,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    skip: int = 0,
    limit: int = 100,
) -> list[{schema_class}]:
    """Get list of {model_plural}.

    Args:
        db: Database session
        current_user: Authenticated user
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of {model_plural}
    """
    {model_plural} = await crud.get_{model_plural}(db, skip=skip, limit=limit)
    return [{schema_class}.model_validate({model_var}) for {model_var} in {model_plural}]


@router.get("/{{{model_var}_id}}", response_model={schema_class})
async def get_{model_var}(
    {model_var}_id: int,
    _rate_limit: RateLimited,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> {schema_class}:
    """Get {model_var} by ID.

    Args:
        {model_var}_id: {model_class} ID
        db: Database session
        current_user: Authenticated user

    Returns:
        {model_class} instance

    Raises:
        NotFoundException: If {model_var} not found
    """
    {model_var} = await crud.get_{model_var}(db, {model_var}_id)
    return {schema_class}.model_validate({model_var})


@router.post("/", response_model={schema_class}, status_code=status.HTTP_201_CREATED)
async def create_{model_var}(
    {model_var}_data: {schema_class}Create,
    _rate_limit: RateLimited,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> {schema_class}:
    """Create new {model_var}.

    Args:
        {model_var}_data: {model_class} creation data
        db: Database session
        current_user: Authenticated user

    Returns:
        Created {model_class} instance
    """
    {model_var} = await crud.create_{model_var}(db, {model_var}_data)
    return {schema_class}.model_validate({model_var})


@router.put("/{{{model_var}_id}}", response_model={schema_class})
async def update_{model_var}(
    {model_var}_id: int,
    {model_var}_data: {schema_class}Update,
    _rate_limit: RateLimited,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> {schema_class}:
    """Update existing {model_var}.

    Args:
        {model_var}_id: {model_class} ID
        {model_var}_data: {model_class} update data
        db: Database session
        current_user: Authenticated user

    Returns:
        Updated {model_class} instance

    Raises:
        NotFoundException: If {model_var} not found
    """
    {model_var} = await crud.update_{model_var}(db, {model_var}_id, {model_var}_data)
    return {schema_class}.model_validate({model_var})


@router.delete("/{{{model_var}_id}}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_{model_var}(
    {model_var}_id: int,
    _rate_limit: RateLimited,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete {model_var}.

    Args:
        {model_var}_id: {model_class} ID
        db: Database session
        current_user: Authenticated user

    Raises:
        NotFoundException: If {model_var} not found
    """
    await crud.delete_{model_var}(db, {model_var}_id)
'''

TEST_TEMPLATE = '''"""Tests for {model_name} API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.models.{model_file} import {model_class}


@pytest.fixture
async def {model_var}_data() -> dict:
    """Sample {model_var} data."""
    return {{
        "name": "Test {model_class}",
        "description": "Test description",
    }}


@pytest.fixture
async def created_{model_var}(
    db_session: AsyncSession,
    {model_var}_data: dict,
) -> {model_class}:
    """Create test {model_var}."""
    {model_var} = {model_class}(**{model_var}_data)
    db_session.add({model_var})
    await db_session.commit()
    await db_session.refresh({model_var})
    return {model_var}


class Test{schema_class}Endpoints:
    """Tests for {model_var} endpoints."""

    async def test_list_{model_plural}(
        self,
        client: AsyncClient,
        auth_headers: dict,
        created_{model_var}: {model_class},
    ) -> None:
        """Test listing {model_plural}."""
        response = await client.get("/{model_plural}/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert data[0]["name"] == created_{model_var}.name

    async def test_get_{model_var}(
        self,
        client: AsyncClient,
        auth_headers: dict,
        created_{model_var}: {model_class},
    ) -> None:
        """Test getting {model_var} by ID."""
        response = await client.get(
            f"/{model_plural}/{{created_{model_var}.id}}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created_{model_var}.id
        assert data["name"] == created_{model_var}.name

    async def test_get_{model_var}_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        """Test getting non-existent {model_var}."""
        response = await client.get("/{model_plural}/99999", headers=auth_headers)
        assert response.status_code == 404

    async def test_create_{model_var}(
        self,
        client: AsyncClient,
        auth_headers: dict,
        {model_var}_data: dict,
    ) -> None:
        """Test creating {model_var}."""
        response = await client.post(
            "/{model_plural}/",
            json={model_var}_data,
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == {model_var}_data["name"]
        assert "id" in data

    async def test_update_{model_var}(
        self,
        client: AsyncClient,
        auth_headers: dict,
        created_{model_var}: {model_class},
    ) -> None:
        """Test updating {model_var}."""
        update_data = {{"name": "Updated {model_class}"}}
        response = await client.put(
            f"/{model_plural}/{{created_{model_var}.id}}",
            json=update_data,
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == update_data["name"]

    async def test_delete_{model_var}(
        self,
        client: AsyncClient,
        auth_headers: dict,
        created_{model_var}: {model_class},
    ) -> None:
        """Test deleting {model_var}."""
        response = await client.delete(
            f"/{model_plural}/{{created_{model_var}.id}}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        # Verify deletion
        response = await client.get(
            f"/{model_plural}/{{created_{model_var}.id}}",
            headers=auth_headers,
        )
        assert response.status_code == 404
'''


def to_snake_case(text: str) -> str:
    """Convert text to snake_case."""
    # Insert underscore before uppercase letters
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
    return text.lower()


def to_plural(text: str) -> str:
    """Convert singular noun to plural (simple rules)."""
    if text.endswith("y"):
        return text[:-1] + "ies"
    elif text.endswith(("s", "x", "z", "ch", "sh")):
        return text + "es"
    else:
        return text + "s"


def get_template_context(model_name: str) -> dict[str, Any]:
    """Generate template context from model name."""
    # Convert model name to PascalCase class name
    model_class = "".join(word.capitalize() for word in model_name.replace("_", " ").split())

    # Generate various name formats
    model_var = to_snake_case(model_class)
    model_plural = to_plural(model_var)
    table_name = model_plural

    # Schema and file names
    schema_class = model_class
    schema_file = model_var
    model_file = model_var

    return {
        "model_name": model_name,
        "model_class": model_class,
        "model_var": model_var,
        "model_plural": model_plural,
        "table_name": table_name,
        "schema_class": schema_class,
        "schema_file": schema_file,
        "model_file": model_file,
    }


@click.group()
def generate() -> None:
    """Code generation and scaffolding commands.

    Generate boilerplate code for models, schemas, CRUD operations,
    API routes, and tests following FastAPI best practices.
    """


@generate.command()
@click.argument("model_name")
@click.option(
    "--all",
    "generate_all",
    is_flag=True,
    help="Generate all files (model, schema, CRUD, router, tests)",
)
@click.option("--model", is_flag=True, help="Generate SQLAlchemy model")
@click.option("--schema", is_flag=True, help="Generate Pydantic schemas")
@click.option("--crud", is_flag=True, help="Generate CRUD operations")
@click.option("--router", is_flag=True, help="Generate API router")
@click.option("--tests", is_flag=True, help="Generate test file")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def resource(
    model_name: str,
    generate_all: bool,
    model: bool,
    schema: bool,
    crud: bool,
    router: bool,
    tests: bool,
    force: bool,
) -> None:
    """Generate a complete CRUD resource.

    Creates model, schema, CRUD operations, API routes, and tests
    for a new resource following FastAPI conventions.

    Example:

        example-service generate resource Product --all

        example-service generate resource Order --model --schema --crud

    Args:
        model_name: Name of the model (e.g., 'Product', 'Order', 'user_profile')
    """
    # If no specific flags, generate all by default
    if not any([model, schema, crud, router, tests]):
        generate_all = True

    if generate_all:
        model = schema = crud = router = tests = True

    # Get template context
    ctx = get_template_context(model_name)

    # Base paths
    base_path = Path("example_service")

    # Track generated files
    generated_files = []
    skipped_files = []

    # Generate model
    if model:
        model_path = base_path / "core" / "models" / f"{ctx['model_file']}.py"
        if model_path.exists() and not force:
            skipped_files.append(str(model_path))
            click.echo(f"⏭️  Skipped (exists): {model_path}")
        else:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_text(MODEL_TEMPLATE.format(**ctx))
            generated_files.append(str(model_path))
            click.echo(f"✅ Generated model: {model_path}")

    # Generate schema
    if schema:
        schema_path = base_path / "core" / "schemas" / f"{ctx['schema_file']}.py"
        if schema_path.exists() and not force:
            skipped_files.append(str(schema_path))
            click.echo(f"⏭️  Skipped (exists): {schema_path}")
        else:
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.write_text(SCHEMA_TEMPLATE.format(**ctx))
            generated_files.append(str(schema_path))
            click.echo(f"✅ Generated schema: {schema_path}")

    # Generate CRUD
    if crud:
        crud_path = base_path / "core" / "crud" / f"{ctx['model_file']}.py"
        if crud_path.exists() and not force:
            skipped_files.append(str(crud_path))
            click.echo(f"⏭️  Skipped (exists): {crud_path}")
        else:
            crud_path.parent.mkdir(parents=True, exist_ok=True)
            crud_path.write_text(CRUD_TEMPLATE.format(**ctx))
            generated_files.append(str(crud_path))
            click.echo(f"✅ Generated CRUD: {crud_path}")

    # Generate router
    if router:
        router_path = base_path / "app" / "routers" / f"{ctx['model_plural']}.py"
        if router_path.exists() and not force:
            skipped_files.append(str(router_path))
            click.echo(f"⏭️  Skipped (exists): {router_path}")
        else:
            router_path.parent.mkdir(parents=True, exist_ok=True)
            router_path.write_text(ROUTER_TEMPLATE.format(**ctx))
            generated_files.append(str(router_path))
            click.echo(f"✅ Generated router: {router_path}")

    # Generate tests
    if tests:
        test_path = Path("tests") / "test_api" / f"test_{ctx['model_plural']}.py"
        if test_path.exists() and not force:
            skipped_files.append(str(test_path))
            click.echo(f"⏭️  Skipped (exists): {test_path}")
        else:
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_text(TEST_TEMPLATE.format(**ctx))
            generated_files.append(str(test_path))
            click.echo(f"✅ Generated tests: {test_path}")

    # Summary
    click.echo("\n" + "=" * 60)
    click.echo(f"📦 Resource '{ctx['model_class']}' scaffolding complete!")
    click.echo(f"✅ Generated {len(generated_files)} files")
    if skipped_files:
        click.echo(f"⏭️  Skipped {len(skipped_files)} existing files (use --force to overwrite)")

    # Next steps
    if generated_files:
        click.echo("\n📋 Next steps:")
        click.echo("1. Review and customize generated files")
        if model:
            click.echo("2. Add model to example_service/core/models/__init__.py")
        if router:
            click.echo("3. Register router in example_service/app/routers/__init__.py")
        if crud:
            click.echo("4. Import CRUD functions in example_service/core/crud/__init__.py")
        if model:
            click.echo(f"5. Create database migration: example-service db revision -m 'add {ctx['table_name']}'")
        if tests:
            click.echo(f"6. Run tests: pytest tests/test_api/test_{ctx['model_plural']}.py")


@generate.command()
@click.argument("name")
@click.option("--prefix", default="/api", help="Router prefix")
@click.option("--tag", help="OpenAPI tag (defaults to name)")
def router(name: str, prefix: str, tag: str | None) -> None:
    """Generate a minimal API router.

    Creates a basic FastAPI router with health check endpoint.

    Example:

        example-service generate router webhooks --prefix /webhooks

    Args:
        name: Router name (e.g., 'webhooks', 'reports')
    """
    router_name = to_snake_case(name)
    tag = tag or name

    router_content = f'''"""API routes for {name}."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(
    prefix="{prefix}/{router_name}",
    tags=["{tag}"],
)


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {{"status": "ok", "service": "{name}"}}
'''

    router_path = Path("example_service/app/routers") / f"{router_name}.py"
    router_path.parent.mkdir(parents=True, exist_ok=True)
    router_path.write_text(router_content)

    click.echo(f"✅ Generated router: {router_path}")
    click.echo("\n📋 Next step: Register in example_service/app/routers/__init__.py")
    click.echo(f"   from example_service.app.routers import {router_name}")


@generate.command()
@click.argument("name")
def middleware(name: str) -> None:
    """Generate a middleware template.

    Creates a FastAPI middleware with logging and error handling.

    Example:

        example-service generate middleware audit_log

    Args:
        name: Middleware name (e.g., 'audit_log', 'custom_auth')
    """
    middleware_name = to_snake_case(name)
    class_name = "".join(word.capitalize() for word in middleware_name.split("_")) + "Middleware"

    middleware_content = f'''"""Custom {name} middleware."""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class {class_name}(BaseHTTPMiddleware):
    """Middleware for {name}.

    Add your custom middleware logic here.
    """

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool = True,
    ) -> None:
        """Initialize middleware.

        Args:
            app: The ASGI application
            enabled: Whether middleware is enabled
        """
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request and response.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response from the handler
        """
        if not self.enabled:
            return await call_next(request)

        # Pre-processing
        logger.debug(f"Processing request: {{request.method}} {{request.url.path}}")

        try:
            # Call next middleware/handler
            response = await call_next(request)

            # Post-processing
            logger.debug(f"Request completed: {{response.status_code}}")

            return response
        except Exception as e:
            logger.error(f"Request failed: {{e}}", exc_info=True)
            raise
'''

    middleware_path = Path("example_service/app/middleware") / f"{middleware_name}.py"
    middleware_path.parent.mkdir(parents=True, exist_ok=True)
    middleware_path.write_text(middleware_content)

    click.echo(f"✅ Generated middleware: {middleware_path}")
    click.echo("\n📋 Next steps:")
    click.echo(f"1. Implement your middleware logic in {class_name}")
    click.echo("2. Register in example_service/app/middleware/__init__.py")
    click.echo("3. Add to configure_middleware() function")


@generate.command()
@click.argument("name")
def migration(name: str) -> None:
    """Generate a database migration script.

    Creates an empty Alembic migration with upgrade/downgrade functions.

    Example:

        example-service generate migration add_user_roles

    Args:
        name: Migration description
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    revision_id = timestamp[:8]  # Use date as revision ID
    migration_name = to_snake_case(name)

    migration_content = f'''"""
{name}

Revision ID: {revision_id}
Revises:
Create Date: {datetime.now().isoformat()}

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "{revision_id}"
down_revision = None  # Update this to previous revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add your migration logic here
    pass


def downgrade() -> None:
    """Downgrade database schema."""
    # Add your rollback logic here
    pass
'''

    migrations_path = Path("alembic/versions")
    migrations_path.mkdir(parents=True, exist_ok=True)

    migration_file = migrations_path / f"{timestamp}_{migration_name}.py"
    migration_file.write_text(migration_content)

    click.echo(f"✅ Generated migration: {migration_file}")
    click.echo("\n📋 Next steps:")
    click.echo("1. Update 'down_revision' with the previous migration ID")
    click.echo("2. Implement upgrade() and downgrade() functions")
    click.echo("3. Test migration: example-service db upgrade")
    click.echo("4. Test rollback: example-service db downgrade")
