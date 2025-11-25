"""User management commands.

This module provides CLI commands for managing users:
- List users
- Create users and superusers
- Activate/deactivate users
- Reset passwords
"""

import sys

import click

from example_service.cli.utils import coro, error, header, info, success, warning


def hash_password(password: str) -> str:
    """Hash a password using bcrypt or fallback."""
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.hash(password)
    except ImportError:
        # Fallback to hashlib if passlib not available
        import hashlib
        warning("passlib not installed, using basic hash (not recommended for production)")
        return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.verify(plain, hashed)
    except ImportError:
        import hashlib
        return hashlib.sha256(plain.encode()).hexdigest() == hashed


@click.group(name="users")
def users() -> None:
    """User management commands."""


@users.command(name="list")
@click.option(
    "--active-only",
    is_flag=True,
    default=False,
    help="Show only active users",
)
@click.option(
    "--superusers",
    is_flag=True,
    default=False,
    help="Show only superusers",
)
@click.option(
    "--limit",
    default=50,
    type=int,
    help="Maximum number of users to show (default: 50)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@coro
async def list_users(active_only: bool, superusers: bool, limit: int, output_format: str) -> None:
    """List all users in the database."""
    header("User List")

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            stmt = select(User).limit(limit)

            if active_only:
                stmt = stmt.where(User.is_active == True)  # noqa: E712

            if superusers:
                stmt = stmt.where(User.is_superuser == True)  # noqa: E712

            result = await session.execute(stmt)
            users_list = result.scalars().all()

            if not users_list:
                info("No users found")
                return

            if output_format == "json":
                import json
                data = [
                    {
                        "id": u.id,
                        "email": u.email,
                        "username": u.username,
                        "full_name": u.full_name,
                        "is_active": u.is_active,
                        "is_superuser": u.is_superuser,
                        "created_at": u.created_at.isoformat() if u.created_at else None,
                    }
                    for u in users_list
                ]
                click.echo(json.dumps(data, indent=2))
                return

            # Table format
            click.echo()
            click.echo(f"{'ID':<6} {'Username':<20} {'Email':<35} {'Active':<8} {'Super':<8}")
            click.echo("-" * 85)

            for user in users_list:
                active = click.style("Yes", fg="green") if user.is_active else click.style("No", fg="red")
                superuser = click.style("Yes", fg="cyan") if user.is_superuser else "No"

                click.echo(
                    f"{user.id:<6} {user.username:<20} {user.email:<35} {active:<17} {superuser:<8}"
                )

            click.echo()
            success(f"Total: {len(users_list)} users")

    except ImportError as e:
        error(f"Failed to import modules: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to list users: {e}")
        sys.exit(1)


@users.command(name="create")
@click.option("--email", prompt=True, help="User email address")
@click.option("--username", prompt=True, help="Username")
@click.option("--full-name", default=None, help="Full name (optional)")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="User password",
)
@coro
async def create_user(email: str, username: str, full_name: str | None, password: str) -> None:
    """Create a new regular user."""
    info(f"Creating user: {username} ({email})")

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Check if user exists
            existing = await session.execute(
                select(User).where(
                    (User.email == email) | (User.username == username)
                )
            )
            if existing.scalar_one_or_none():
                error("A user with this email or username already exists")
                sys.exit(1)

            # Create user
            user = User(
                email=email,
                username=username,
                full_name=full_name,
                hashed_password=hash_password(password),
                is_active=True,
                is_superuser=False,
            )

            session.add(user)
            await session.commit()
            await session.refresh(user)

            success("User created successfully!")
            click.echo(f"  ID:       {user.id}")
            click.echo(f"  Username: {user.username}")
            click.echo(f"  Email:    {user.email}")

    except Exception as e:
        error(f"Failed to create user: {e}")
        sys.exit(1)


@users.command(name="create-superuser")
@click.option("--email", prompt=True, help="Superuser email address")
@click.option("--username", prompt=True, help="Superuser username")
@click.option("--full-name", default=None, help="Full name (optional)")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="Superuser password",
)
@coro
async def create_superuser(email: str, username: str, full_name: str | None, password: str) -> None:
    """Create a new superuser with admin privileges."""
    info(f"Creating superuser: {username} ({email})")

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Check if user exists
            existing = await session.execute(
                select(User).where(
                    (User.email == email) | (User.username == username)
                )
            )
            if existing.scalar_one_or_none():
                error("A user with this email or username already exists")
                sys.exit(1)

            # Create superuser
            user = User(
                email=email,
                username=username,
                full_name=full_name,
                hashed_password=hash_password(password),
                is_active=True,
                is_superuser=True,
            )

            session.add(user)
            await session.commit()
            await session.refresh(user)

            success("Superuser created successfully!")
            click.echo(f"  ID:       {user.id}")
            click.echo(f"  Username: {user.username}")
            click.echo(f"  Email:    {user.email}")
            click.secho("  Role:     Superuser", fg="cyan", bold=True)

    except Exception as e:
        error(f"Failed to create superuser: {e}")
        sys.exit(1)


@users.command(name="deactivate")
@click.argument("identifier")
@coro
async def deactivate_user(identifier: str) -> None:
    """Deactivate a user account.

    IDENTIFIER can be user ID, email, or username.
    """
    warning(f"Deactivating user: {identifier}")

    if not click.confirm("Are you sure you want to deactivate this user?"):
        info("Operation cancelled")
        return

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Find user
            try:
                user_id = int(identifier)
                stmt = select(User).where(User.id == user_id)
            except ValueError:
                stmt = select(User).where(
                    (User.email == identifier) | (User.username == identifier)
                )

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                error(f"User not found: {identifier}")
                sys.exit(1)

            if not user.is_active:
                warning("User is already deactivated")
                return

            # Deactivate
            user.is_active = False
            await session.commit()

            success(f"User '{user.username}' has been deactivated")

    except Exception as e:
        error(f"Failed to deactivate user: {e}")
        sys.exit(1)


@users.command(name="activate")
@click.argument("identifier")
@coro
async def activate_user(identifier: str) -> None:
    """Activate a user account.

    IDENTIFIER can be user ID, email, or username.
    """
    info(f"Activating user: {identifier}")

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Find user
            try:
                user_id = int(identifier)
                stmt = select(User).where(User.id == user_id)
            except ValueError:
                stmt = select(User).where(
                    (User.email == identifier) | (User.username == identifier)
                )

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                error(f"User not found: {identifier}")
                sys.exit(1)

            if user.is_active:
                warning("User is already active")
                return

            # Activate
            user.is_active = True
            await session.commit()

            success(f"User '{user.username}' has been activated")

    except Exception as e:
        error(f"Failed to activate user: {e}")
        sys.exit(1)


@users.command(name="reset-password")
@click.argument("identifier")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="New password",
)
@coro
async def reset_password(identifier: str, password: str) -> None:
    """Reset a user's password.

    IDENTIFIER can be user ID, email, or username.
    """
    warning(f"Resetting password for user: {identifier}")

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Find user
            try:
                user_id = int(identifier)
                stmt = select(User).where(User.id == user_id)
            except ValueError:
                stmt = select(User).where(
                    (User.email == identifier) | (User.username == identifier)
                )

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                error(f"User not found: {identifier}")
                sys.exit(1)

            # Update password
            user.hashed_password = hash_password(password)
            await session.commit()

            success(f"Password reset successfully for user '{user.username}'")

    except Exception as e:
        error(f"Failed to reset password: {e}")
        sys.exit(1)


@users.command(name="promote")
@click.argument("identifier")
@coro
async def promote_to_superuser(identifier: str) -> None:
    """Promote a user to superuser status.

    IDENTIFIER can be user ID, email, or username.
    """
    warning(f"Promoting user to superuser: {identifier}")

    if not click.confirm("Are you sure you want to grant superuser privileges?"):
        info("Operation cancelled")
        return

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Find user
            try:
                user_id = int(identifier)
                stmt = select(User).where(User.id == user_id)
            except ValueError:
                stmt = select(User).where(
                    (User.email == identifier) | (User.username == identifier)
                )

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                error(f"User not found: {identifier}")
                sys.exit(1)

            if user.is_superuser:
                warning("User is already a superuser")
                return

            # Promote
            user.is_superuser = True
            await session.commit()

            success(f"User '{user.username}' has been promoted to superuser")

    except Exception as e:
        error(f"Failed to promote user: {e}")
        sys.exit(1)


@users.command(name="demote")
@click.argument("identifier")
@coro
async def demote_from_superuser(identifier: str) -> None:
    """Remove superuser status from a user.

    IDENTIFIER can be user ID, email, or username.
    """
    warning(f"Removing superuser status: {identifier}")

    if not click.confirm("Are you sure you want to remove superuser privileges?"):
        info("Operation cancelled")
        return

    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Find user
            try:
                user_id = int(identifier)
                stmt = select(User).where(User.id == user_id)
            except ValueError:
                stmt = select(User).where(
                    (User.email == identifier) | (User.username == identifier)
                )

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                error(f"User not found: {identifier}")
                sys.exit(1)

            if not user.is_superuser:
                warning("User is not a superuser")
                return

            # Demote
            user.is_superuser = False
            await session.commit()

            success(f"User '{user.username}' has been demoted from superuser")

    except Exception as e:
        error(f"Failed to demote user: {e}")
        sys.exit(1)


@users.command(name="show")
@click.argument("identifier")
@coro
async def show_user(identifier: str) -> None:
    """Show detailed information about a user.

    IDENTIFIER can be user ID, email, or username.
    """
    try:
        from sqlalchemy import select

        from example_service.core.models.user import User
        from example_service.infra.database import get_session

        async with get_session() as session:
            # Find user
            try:
                user_id = int(identifier)
                stmt = select(User).where(User.id == user_id)
            except ValueError:
                stmt = select(User).where(
                    (User.email == identifier) | (User.username == identifier)
                )

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                error(f"User not found: {identifier}")
                sys.exit(1)

            header(f"User: {user.username}")
            click.echo()
            click.echo(f"  ID:         {user.id}")
            click.echo(f"  Username:   {user.username}")
            click.echo(f"  Email:      {user.email}")
            click.echo(f"  Full Name:  {user.full_name or 'N/A'}")

            # Status
            status = click.style("Active", fg="green") if user.is_active else click.style("Inactive", fg="red")
            click.echo(f"  Status:     {status}")

            # Role
            role = click.style("Superuser", fg="cyan", bold=True) if user.is_superuser else "Regular User"
            click.echo(f"  Role:       {role}")

            # Timestamps
            if user.created_at:
                click.echo(f"  Created:    {user.created_at.isoformat()}")
            if user.updated_at:
                click.echo(f"  Updated:    {user.updated_at.isoformat()}")

    except Exception as e:
        error(f"Failed to show user: {e}")
        sys.exit(1)
