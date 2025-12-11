# mypy: disable-error-code="attr-defined,arg-type,assignment,return-value,misc,name-defined"
"""Feature flag management CLI commands.

This module provides CLI commands for managing feature flags:
- List and create feature flags
- Enable/disable flags
- Manage flag overrides
- Evaluate flags for testing
"""

from datetime import datetime
import sys

import click

from example_service.cli.utils import (
    coro,
    error,
    header,
    info,
    section,
    success,
    warning,
)


@click.group(name="flags")
def flags() -> None:
    """Feature flag management commands.

    Commands for managing feature flags, rollouts,
    targeting rules, and overrides.
    """


@flags.command(name="list")
@click.option(
    "--status",
    "-s",
    type=click.Choice(["enabled", "disabled", "percentage", "targeted"]),
    help="Filter by status",
)
@click.option(
    "--enabled/--disabled",
    default=None,
    help="Filter by enabled state",
)
@click.option(
    "--limit",
    default=100,
    type=int,
    help="Maximum flags to display (default: 100)",
)
@coro
async def list_flags(status: str | None, enabled: bool | None, limit: int) -> None:
    """List all feature flags.

    Shows flag name, status, percentage, and targeting info.
    """
    from example_service.features.featureflags.models import FlagStatus
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    header("Feature Flags")

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)

        flag_status = FlagStatus(status) if status else None
        response = await service.list_flags(
            status=flag_status,
            enabled=enabled,
            limit=limit,
        )

        if not response.items:
            info("No feature flags found")
            return

        click.echo()
        for flag in response.items:
            status_color = {
                "enabled": "green",
                "disabled": "red",
                "percentage": "yellow",
                "targeted": "blue",
            }.get(flag.status, "white")

            click.echo(f"  {flag.key}")
            click.echo(f"    Name: {flag.name}")
            click.secho(f"    Status: {flag.status}", fg=status_color)

            if flag.status == "percentage":
                click.echo(f"    Rollout: {flag.percentage}%")

            if flag.starts_at or flag.ends_at:
                time_info = []
                if flag.starts_at:
                    time_info.append(f"starts {flag.starts_at.strftime('%Y-%m-%d')}")
                if flag.ends_at:
                    time_info.append(f"ends {flag.ends_at.strftime('%Y-%m-%d')}")
                click.echo(f"    Schedule: {', '.join(time_info)}")

            if flag.description:
                click.echo(f"    Description: {flag.description[:60]}...")
            click.echo()

        success(f"Total: {response.total} flags")


@flags.command(name="show")
@click.argument("key")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@coro
async def show_flag(key: str, output_format: str) -> None:
    """Show details of a specific feature flag.

    KEY is the unique key of the feature flag.
    """
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        flag = await service.get_by_key(key)

        if not flag:
            error(f"Feature flag not found: {key}")
            sys.exit(1)

        if output_format == "json":
            import json

            data = {
                "id": str(flag.id),
                "key": flag.key,
                "name": flag.name,
                "description": flag.description,
                "status": flag.status,
                "enabled": flag.enabled,
                "percentage": flag.percentage,
                "targeting_rules": flag.targeting_rules,
                "starts_at": flag.starts_at.isoformat() if flag.starts_at else None,
                "ends_at": flag.ends_at.isoformat() if flag.ends_at else None,
                "created_at": flag.created_at.isoformat(),
                "updated_at": flag.updated_at.isoformat(),
            }
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            header(f"Feature Flag: {key}")

            section("Configuration")
            click.echo(f"  Name: {flag.name}")
            click.echo(f"  Key: {flag.key}")

            status_color = {
                "enabled": "green",
                "disabled": "red",
                "percentage": "yellow",
                "targeted": "blue",
            }.get(flag.status, "white")
            click.secho(f"  Status: {flag.status}", fg=status_color)
            click.echo(f"  Enabled: {flag.enabled}")

            if flag.percentage is not None:
                click.echo(f"  Percentage: {flag.percentage}%")

            if flag.description:
                section("Description")
                click.echo(f"  {flag.description}")

            section("Schedule")
            if flag.starts_at:
                click.echo(f"  Starts: {flag.starts_at.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                click.echo("  Starts: Immediately")
            if flag.ends_at:
                click.echo(f"  Ends: {flag.ends_at.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                click.echo("  Ends: Never")

            if flag.targeting_rules:
                section("Targeting Rules")
                for i, rule in enumerate(flag.targeting_rules, 1):
                    click.echo(f"  Rule {i}:")
                    click.echo(f"    Type: {rule.get('type')}")
                    click.echo(f"    Operator: {rule.get('operator', 'eq')}")
                    click.echo(f"    Value: {rule.get('value')}")

            section("Timestamps")
            click.echo(f"  Created: {flag.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo(f"  Updated: {flag.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

            success("Flag details retrieved")


@flags.command(name="create")
@click.option("--key", "-k", required=True, help="Unique flag key")
@click.option("--name", "-n", required=True, help="Human-readable name")
@click.option("--description", "-d", help="Flag description")
@click.option(
    "--status",
    "-s",
    type=click.Choice(["enabled", "disabled", "percentage", "targeted"]),
    default="disabled",
    help="Flag status (default: disabled)",
)
@click.option("--percentage", "-p", type=int, help="Rollout percentage (0-100)")
@click.option("--starts-at", type=click.DateTime(), help="Start date/time")
@click.option("--ends-at", type=click.DateTime(), help="End date/time")
@coro
async def create_flag(
    key: str,
    name: str,
    description: str | None,
    status: str,
    percentage: int | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> None:
    """Create a new feature flag.

    Examples:
      example-service flags create -k new_checkout -n "New Checkout Flow" -s percentage -p 25
      example-service flags create -k beta_feature -n "Beta Feature" -s disabled
    """
    from example_service.features.featureflags.models import FlagStatus
    from example_service.features.featureflags.schemas import FeatureFlagCreate
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    header("Creating Feature Flag")

    if status == "percentage" and percentage is None:
        error("--percentage is required when status is 'percentage'")
        sys.exit(1)

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)

        # Check if flag already exists
        existing = await service.get_by_key(key)
        if existing:
            error(f"Feature flag already exists: {key}")
            sys.exit(1)

        payload = FeatureFlagCreate(
            key=key,
            name=name,
            description=description,
            status=FlagStatus(status),
            enabled=status == "enabled",
            percentage=percentage or 0,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        flag = await service.create(payload)

        success(f"Feature flag created: {flag.key}")
        click.echo(f"\n  Name: {flag.name}")
        click.echo(f"  Status: {flag.status}")
        if flag.percentage:
            click.echo(f"  Percentage: {flag.percentage}%")


@flags.command(name="enable")
@click.argument("key")
@coro
async def enable_flag(key: str) -> None:
    """Enable a feature flag.

    KEY is the unique key of the feature flag.
    """
    from example_service.features.featureflags.models import FlagStatus
    from example_service.features.featureflags.schemas import FeatureFlagUpdate
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        flag = await service.update(
            key,
            FeatureFlagUpdate(status=FlagStatus.ENABLED, enabled=True),
        )

        if flag:
            success(f"Feature flag enabled: {key}")
        else:
            error(f"Feature flag not found: {key}")
            sys.exit(1)


@flags.command(name="disable")
@click.argument("key")
@coro
async def disable_flag(key: str) -> None:
    """Disable a feature flag.

    KEY is the unique key of the feature flag.
    """
    from example_service.features.featureflags.models import FlagStatus
    from example_service.features.featureflags.schemas import FeatureFlagUpdate
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        flag = await service.update(
            key,
            FeatureFlagUpdate(status=FlagStatus.DISABLED, enabled=False),
        )

        if flag:
            success(f"Feature flag disabled: {key}")
        else:
            error(f"Feature flag not found: {key}")
            sys.exit(1)


@flags.command(name="set-percentage")
@click.argument("key")
@click.argument("percentage", type=int)
@coro
async def set_percentage(key: str, percentage: int) -> None:
    """Set rollout percentage for a feature flag.

    KEY is the unique key of the feature flag.
    PERCENTAGE is the rollout percentage (0-100).
    """
    if percentage < 0 or percentage > 100:
        error("Percentage must be between 0 and 100")
        sys.exit(1)

    from example_service.features.featureflags.models import FlagStatus
    from example_service.features.featureflags.schemas import FeatureFlagUpdate
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        flag = await service.update(
            key,
            FeatureFlagUpdate(status=FlagStatus.PERCENTAGE, percentage=percentage),
        )

        if flag:
            success(f"Feature flag '{key}' set to {percentage}% rollout")
        else:
            error(f"Feature flag not found: {key}")
            sys.exit(1)


@flags.command(name="delete")
@click.argument("key")
@click.option("--force", is_flag=True, help="Skip confirmation")
@coro
async def delete_flag(key: str, force: bool) -> None:
    """Delete a feature flag.

    KEY is the unique key of the feature flag.
    This also removes all associated overrides.
    """
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    if not force:
        warning("This will delete the flag and all its overrides!")
        if not click.confirm(f"Delete feature flag '{key}'?"):
            info("Deletion cancelled")
            return

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        deleted = await service.delete(key)

        if deleted:
            success(f"Feature flag deleted: {key}")
        else:
            error(f"Feature flag not found: {key}")
            sys.exit(1)


@flags.command(name="override")
@click.argument("key")
@click.option(
    "--entity-type",
    "-t",
    type=click.Choice(["user", "tenant"]),
    required=True,
    help="Entity type",
)
@click.option("--entity-id", "-e", required=True, help="Entity ID")
@click.option("--enable/--disable", required=True, help="Override value")
@click.option("--reason", "-r", help="Reason for override")
@coro
async def create_override(
    key: str,
    entity_type: str,
    entity_id: str,
    enable: bool,
    reason: str | None,
) -> None:
    """Create or update a flag override for a user or tenant.

    KEY is the unique key of the feature flag.

    Examples:
      example-service flags override new_feature -t user -e user-123 --enable
      example-service flags override beta_feature -t tenant -e tenant-456 --disable -r "Opted out"
    """
    from example_service.features.featureflags.schemas import FlagOverrideCreate
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)

        # Verify flag exists
        flag = await service.get_by_key(key)
        if not flag:
            error(f"Feature flag not found: {key}")
            sys.exit(1)

        payload = FlagOverrideCreate(
            flag_key=key,
            entity_type=entity_type,
            entity_id=entity_id,
            enabled=enable,
            reason=reason,
        )

        await service.create_override(payload)

        action = "enabled" if enable else "disabled"
        success(f"Override created: {key} {action} for {entity_type}:{entity_id}")


@flags.command(name="remove-override")
@click.argument("key")
@click.option(
    "--entity-type",
    "-t",
    type=click.Choice(["user", "tenant"]),
    required=True,
    help="Entity type",
)
@click.option("--entity-id", "-e", required=True, help="Entity ID")
@coro
async def remove_override(key: str, entity_type: str, entity_id: str) -> None:
    """Remove a flag override.

    KEY is the unique key of the feature flag.
    """
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        deleted = await service.delete_override(key, entity_type, entity_id)

        if deleted:
            success(f"Override removed for {entity_type}:{entity_id}")
        else:
            warning("Override not found")


@flags.command(name="overrides")
@click.argument("key", required=False)
@click.option("--entity-type", "-t", help="Filter by entity type")
@click.option("--entity-id", "-e", help="Filter by entity ID")
@coro
async def list_overrides(
    key: str | None,
    entity_type: str | None,
    entity_id: str | None,
) -> None:
    """List flag overrides.

    KEY is the optional feature flag key to filter by.
    """
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    header("Flag Overrides")

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)
        overrides = await service.get_overrides(
            flag_key=key,
            entity_type=entity_type,
            entity_id=entity_id,
        )

        if not overrides:
            info("No overrides found")
            return

        click.echo()
        for override in overrides:
            status = click.style("Enabled", fg="green") if override.enabled else click.style("Disabled", fg="red")
            click.echo(f"  {override.flag_key}")
            click.echo(f"    {override.entity_type}:{override.entity_id}: {status}")
            if override.reason:
                click.echo(f"    Reason: {override.reason}")
            click.echo(f"    Created: {override.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo()

        success(f"Total: {len(overrides)} overrides")


@flags.command(name="evaluate")
@click.option("--user-id", "-u", help="User ID for evaluation context")
@click.option("--tenant-id", "-t", help="Tenant ID for evaluation context")
@click.option("--flag", "-f", "flag_keys", multiple=True, help="Specific flags to evaluate")
@click.option("--details", is_flag=True, help="Show evaluation reasons")
@coro
async def evaluate_flags(
    user_id: str | None,
    tenant_id: str | None,
    flag_keys: tuple[str, ...],
    details: bool,
) -> None:
    """Evaluate feature flags for a given context.

    Useful for testing flag configurations.

    Examples:
      example-service flags evaluate -u user-123 -t tenant-456
      example-service flags evaluate -u user-123 -f new_feature -f beta_feature --details
    """
    from example_service.features.featureflags.schemas import FlagEvaluationRequest
    from example_service.features.featureflags.service import FeatureFlagService
    from example_service.infra.database.session import async_sessionmaker

    header("Flag Evaluation")

    if user_id:
        info(f"User: {user_id}")
    if tenant_id:
        info(f"Tenant: {tenant_id}")

    async with async_sessionmaker() as session:
        service = FeatureFlagService(session)

        context = FlagEvaluationRequest(
            user_id=user_id,
            tenant_id=tenant_id,
        )

        response = await service.evaluate(
            context,
            flag_keys=list(flag_keys) if flag_keys else None,
            include_details=details,
        )

        if not response.flags:
            info("No flags evaluated")
            return

        section("Results")
        for flag_key, enabled in sorted(response.flags.items()):
            status = click.style("ON", fg="green") if enabled else click.style("OFF", fg="red")
            click.echo(f"  {flag_key}: {status}")

            if details and response.details:
                for detail in response.details:
                    if detail.key == flag_key:
                        click.echo(f"    Reason: {detail.reason}")

        success(f"Evaluated {len(response.flags)} flags")


@flags.command(name="stats")
@coro
async def flag_stats() -> None:
    """Show feature flag statistics.

    Displays counts by status and override statistics.
    """
    from sqlalchemy import func, select

    from example_service.features.featureflags.models import FeatureFlag, FlagOverride
    from example_service.infra.database.session import async_sessionmaker

    header("Feature Flag Statistics")

    async with async_sessionmaker() as session:
        # Flag counts by status
        status_counts = await session.execute(
            select(FeatureFlag.status, func.count(FeatureFlag.id))
            .group_by(FeatureFlag.status),
        )
        status_dict = {row[0]: row[1] for row in status_counts.all()}

        total_flags = sum(status_dict.values())

        section("Flags by Status")
        click.echo(f"  Total: {total_flags}")
        for status, count in status_dict.items():
            status_color = {
                "enabled": "green",
                "disabled": "red",
                "percentage": "yellow",
                "targeted": "blue",
            }.get(status, "white")
            click.secho(f"  {status.capitalize()}: {count}", fg=status_color)

        # Override counts
        override_count = await session.execute(
            select(func.count(FlagOverride.id)),
        )
        total_overrides = override_count.scalar() or 0

        override_by_type = await session.execute(
            select(FlagOverride.entity_type, func.count(FlagOverride.id))
            .group_by(FlagOverride.entity_type),
        )
        override_dict = {row[0]: row[1] for row in override_by_type.all()}

        section("Overrides")
        click.echo(f"  Total: {total_overrides}")
        for entity_type, count in override_dict.items():
            click.echo(f"  {entity_type.capitalize()}: {count}")

        success("Stats retrieved")
