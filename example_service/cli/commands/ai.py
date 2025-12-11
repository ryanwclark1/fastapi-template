# mypy: disable-error-code="attr-defined,arg-type,assignment,return-value,misc,name-defined"
"""AI operations CLI commands.

This module provides CLI commands for managing AI functionality:
- List and manage AI jobs
- View AI usage and costs
- Configure AI providers
- Monitor rate limits and budgets
"""

from datetime import datetime, timedelta
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


@click.group(name="ai")
def ai() -> None:
    """AI operations management commands.

    Commands for managing AI processing jobs, usage tracking,
    provider configuration, and cost monitoring.
    """


@ai.command(name="jobs")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to list jobs for",
)
@click.option(
    "--status",
    "-s",
    type=click.Choice(["pending", "processing", "completed", "failed", "cancelled"]),
    help="Filter by job status",
)
@click.option(
    "--type",
    "job_type",
    type=click.Choice(
        ["transcription", "pii_redaction", "summary", "sentiment", "coaching", "full_analysis"],
    ),
    help="Filter by job type",
)
@click.option(
    "--limit",
    default=20,
    type=int,
    help="Maximum jobs to display (default: 20)",
)
@coro
async def list_jobs(tenant_id: str, status: str | None, job_type: str | None, limit: int) -> None:
    """List AI processing jobs for a tenant.

    Shows job ID, type, status, progress, and timing information.
    """
    from sqlalchemy import desc, select

    from example_service.features.ai.models import AIJob
    from example_service.infra.database.session import async_sessionmaker

    header(f"AI Jobs for Tenant: {tenant_id}")

    async with async_sessionmaker() as session:
        stmt = select(AIJob).where(AIJob.tenant_id == tenant_id)

        if status:
            stmt = stmt.where(AIJob.status == status.upper())
        if job_type:
            stmt = stmt.where(AIJob.job_type == job_type)

        stmt = stmt.order_by(desc(AIJob.created_at)).limit(limit)

        result = await session.execute(stmt)
        jobs = result.scalars().all()

        if not jobs:
            info("No jobs found matching the criteria")
            return

        click.echo()
        for job in jobs:
            status_color = {
                "PENDING": "yellow",
                "PROCESSING": "blue",
                "COMPLETED": "green",
                "FAILED": "red",
                "CANCELLED": "white",
            }.get(job.status, "white")

            click.echo(f"  Job ID: {job.id}")
            click.echo(f"    Type: {job.job_type}")
            click.secho(f"    Status: {job.status}", fg=status_color)
            click.echo(f"    Progress: {job.progress_percentage}%")
            if job.current_step:
                click.echo(f"    Current Step: {job.current_step}")
            click.echo(f"    Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if job.completed_at:
                click.echo(f"    Completed: {job.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if job.duration_seconds:
                click.echo(f"    Duration: {job.duration_seconds:.1f}s")
            if job.error_message:
                click.secho(f"    Error: {job.error_message}", fg="red")
            click.echo()

        success(f"Total: {len(jobs)} jobs displayed")


@ai.command(name="job")
@click.argument("job_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@coro
async def show_job(job_id: str, output_format: str) -> None:
    """Show details of a specific AI job.

    JOB_ID is the UUID of the AI job.
    """
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from example_service.features.ai.models import AIJob
    from example_service.infra.database.session import async_sessionmaker

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        error(f"Invalid job ID format: {job_id}")
        sys.exit(1)

    async with async_sessionmaker() as session:
        stmt = (
            select(AIJob)
            .where(AIJob.id == job_uuid)
            .options(selectinload(AIJob.usage_logs))
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()

        if not job:
            error(f"Job not found: {job_id}")
            sys.exit(1)

        if output_format == "json":
            import json

            job_data = {
                "id": str(job.id),
                "tenant_id": job.tenant_id,
                "job_type": job.job_type,
                "status": job.status,
                "progress_percentage": job.progress_percentage,
                "current_step": job.current_step,
                "input_data": job.input_data,
                "result_data": job.result_data,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "duration_seconds": job.duration_seconds,
                "usage_logs": [
                    {
                        "provider": log.provider_name,
                        "model": log.model_name,
                        "operation": log.operation_type,
                        "cost_usd": log.cost_usd,
                        "duration_seconds": log.duration_seconds,
                    }
                    for log in job.usage_logs
                ],
            }
            click.echo(json.dumps(job_data, indent=2, default=str))
        else:
            header(f"AI Job: {job_id}")

            section("Basic Information")
            click.echo(f"  Tenant ID: {job.tenant_id}")
            click.echo(f"  Job Type: {job.job_type}")
            click.echo(f"  Status: {job.status}")
            click.echo(f"  Progress: {job.progress_percentage}%")
            if job.current_step:
                click.echo(f"  Current Step: {job.current_step}")

            section("Timing")
            click.echo(f"  Created: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if job.started_at:
                click.echo(f"  Started: {job.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if job.completed_at:
                click.echo(f"  Completed: {job.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if job.duration_seconds:
                click.echo(f"  Duration: {job.duration_seconds:.1f}s")

            if job.error_message:
                section("Error")
                click.secho(f"  {job.error_message}", fg="red")

            if job.usage_logs:
                section("Usage & Costs")
                total_cost = 0.0
                for log in job.usage_logs:
                    click.echo(f"  - {log.operation_type}:")
                    click.echo(f"      Provider: {log.provider_name} ({log.model_name})")
                    click.echo(f"      Cost: ${log.cost_usd:.4f}")
                    click.echo(f"      Duration: {log.duration_seconds:.2f}s")
                    total_cost += log.cost_usd
                click.echo(f"\n  Total Cost: ${total_cost:.4f}")

            success("Job details retrieved")


@ai.command(name="cancel")
@click.argument("job_id")
@click.option("--force", is_flag=True, help="Force cancellation without confirmation")
@coro
async def cancel_job(job_id: str, force: bool) -> None:
    """Cancel an AI processing job.

    JOB_ID is the UUID of the AI job to cancel.
    Only pending or processing jobs can be cancelled.
    """
    from uuid import UUID

    from sqlalchemy import select

    from example_service.features.ai.models import AIJob
    from example_service.infra.database.session import async_sessionmaker

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        error(f"Invalid job ID format: {job_id}")
        sys.exit(1)

    async with async_sessionmaker() as session:
        stmt = select(AIJob).where(AIJob.id == job_uuid)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()

        if not job:
            error(f"Job not found: {job_id}")
            sys.exit(1)

        if job.status not in ("PENDING", "PROCESSING"):
            warning(f"Job cannot be cancelled (status: {job.status})")
            return

        if not force and not click.confirm(f"Cancel job {job_id}?"):
            info("Cancellation aborted")
            return

        job.status = "CANCELLED"
        await session.commit()

        success(f"Job {job_id} cancelled")


@ai.command(name="usage")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to show usage for",
)
@click.option(
    "--days",
    default=30,
    type=int,
    help="Number of days to analyze (default: 30)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@coro
async def show_usage(tenant_id: str, days: int, output_format: str) -> None:
    """Show AI usage and cost metrics for a tenant.

    Displays usage broken down by provider, model, and operation type.
    """
    from datetime import UTC

    from sqlalchemy import func, select

    from example_service.features.ai.models import AIUsageLog
    from example_service.infra.database.session import async_sessionmaker

    header(f"AI Usage for Tenant: {tenant_id}")
    info(f"Period: Last {days} days")

    start_date = datetime.now(UTC) - timedelta(days=days)

    async with async_sessionmaker() as session:
        # Total stats
        total_stmt = select(
            func.count(AIUsageLog.id).label("count"),
            func.sum(AIUsageLog.cost_usd).label("total_cost"),
            func.sum(AIUsageLog.duration_seconds).label("total_duration"),
        ).where(
            AIUsageLog.tenant_id == tenant_id,
            AIUsageLog.created_at >= start_date,
        )

        total_result = await session.execute(total_stmt)
        total_row = total_result.one()

        # By provider
        provider_stmt = (
            select(
                AIUsageLog.provider_name,
                func.count(AIUsageLog.id).label("count"),
                func.sum(AIUsageLog.cost_usd).label("cost"),
            )
            .where(
                AIUsageLog.tenant_id == tenant_id,
                AIUsageLog.created_at >= start_date,
            )
            .group_by(AIUsageLog.provider_name)
        )
        provider_result = await session.execute(provider_stmt)
        by_provider = provider_result.all()

        # By operation type
        operation_stmt = (
            select(
                AIUsageLog.operation_type,
                func.count(AIUsageLog.id).label("count"),
                func.sum(AIUsageLog.cost_usd).label("cost"),
            )
            .where(
                AIUsageLog.tenant_id == tenant_id,
                AIUsageLog.created_at >= start_date,
            )
            .group_by(AIUsageLog.operation_type)
        )
        operation_result = await session.execute(operation_stmt)
        by_operation = operation_result.all()

        if output_format == "json":
            import json

            data = {
                "tenant_id": tenant_id,
                "period_days": days,
                "total_operations": total_row.count or 0,
                "total_cost_usd": float(total_row.total_cost or 0),
                "total_duration_seconds": float(total_row.total_duration or 0),
                "by_provider": {row.provider_name: {"count": row.count, "cost_usd": float(row.cost or 0)} for row in by_provider},
                "by_operation": {row.operation_type: {"count": row.count, "cost_usd": float(row.cost or 0)} for row in by_operation},
            }
            click.echo(json.dumps(data, indent=2))
        else:
            section("Summary")
            click.echo(f"  Total Operations: {total_row.count or 0:,}")
            click.echo(f"  Total Cost: ${total_row.total_cost or 0:.4f}")
            click.echo(f"  Total Duration: {total_row.total_duration or 0:.1f}s")

            if by_provider:
                section("By Provider")
                for row in by_provider:
                    click.echo(f"  {row.provider_name}:")
                    click.echo(f"    Operations: {row.count:,}")
                    click.echo(f"    Cost: ${row.cost or 0:.4f}")

            if by_operation:
                section("By Operation Type")
                for row in by_operation:
                    click.echo(f"  {row.operation_type}:")
                    click.echo(f"    Operations: {row.count:,}")
                    click.echo(f"    Cost: ${row.cost or 0:.4f}")

            success("Usage stats retrieved")


@ai.command(name="configs")
@click.option(
    "--tenant-id",
    "-t",
    help="Tenant ID to list configs for (optional)",
)
@coro
async def list_configs(tenant_id: str | None) -> None:
    """List AI provider configurations.

    Shows configured providers, models, and active status.
    """
    from sqlalchemy import select

    from example_service.features.ai.models import TenantAIConfig
    from example_service.infra.database.session import async_sessionmaker

    header("AI Provider Configurations")

    async with async_sessionmaker() as session:
        stmt = select(TenantAIConfig)
        if tenant_id:
            stmt = stmt.where(TenantAIConfig.tenant_id == tenant_id)

        stmt = stmt.order_by(TenantAIConfig.tenant_id, TenantAIConfig.provider_type)

        result = await session.execute(stmt)
        configs = result.scalars().all()

        if not configs:
            info("No AI configurations found")
            return

        current_tenant = None
        for config in configs:
            if config.tenant_id != current_tenant:
                current_tenant = config.tenant_id
                section(f"Tenant: {current_tenant}")

            status = click.style("Active", fg="green") if config.is_active else click.style("Inactive", fg="red")
            click.echo(f"  {config.provider_type} - {config.provider_name}")
            click.echo(f"    Status: {status}")
            if config.model_name:
                click.echo(f"    Model: {config.model_name}")
            click.echo(f"    API Key: {'******' if config.encrypted_api_key else 'Not Set'}")
            click.echo()

        success(f"Total: {len(configs)} configurations")


@ai.command(name="features")
@click.option(
    "--tenant-id",
    "-t",
    required=True,
    help="Tenant ID to show features for",
)
@coro
async def show_features(tenant_id: str) -> None:
    """Show AI feature configuration for a tenant.

    Displays enabled features, PII settings, and budget limits.
    """
    from sqlalchemy import select

    from example_service.features.ai.models import TenantAIFeature
    from example_service.infra.database.session import async_sessionmaker

    header(f"AI Features for Tenant: {tenant_id}")

    async with async_sessionmaker() as session:
        stmt = select(TenantAIFeature).where(TenantAIFeature.tenant_id == tenant_id)
        result = await session.execute(stmt)
        feature = result.scalar_one_or_none()

        if not feature:
            warning("No AI feature configuration found for this tenant")
            info("Using default configuration")
            return

        section("Feature Toggles")
        features = [
            ("Transcription", feature.transcription_enabled),
            ("PII Redaction", feature.pii_redaction_enabled),
            ("Summary", feature.summary_enabled),
            ("Sentiment Analysis", feature.sentiment_enabled),
            ("Coaching Analysis", feature.coaching_enabled),
        ]
        for name, enabled in features:
            status = click.style("Enabled", fg="green") if enabled else click.style("Disabled", fg="red")
            click.echo(f"  {name}: {status}")

        section("PII Configuration")
        if feature.pii_entity_types:
            click.echo(f"  Entity Types: {', '.join(feature.pii_entity_types)}")
        if feature.pii_confidence_threshold:
            click.echo(f"  Confidence Threshold: {feature.pii_confidence_threshold:.0%}")

        section("Limits")
        if feature.max_audio_duration_seconds:
            click.echo(f"  Max Audio Duration: {feature.max_audio_duration_seconds}s")
        if feature.max_concurrent_jobs:
            click.echo(f"  Max Concurrent Jobs: {feature.max_concurrent_jobs}")

        section("Budget")
        if feature.monthly_budget_usd:
            click.echo(f"  Monthly Budget: ${feature.monthly_budget_usd:.2f}")
        click.echo(f"  Cost Alerts: {'Enabled' if feature.enable_cost_alerts else 'Disabled'}")

        success("Feature configuration retrieved")


@ai.command(name="pipelines")
@coro
async def list_pipelines() -> None:
    """List available AI pipelines and their estimated costs.

    Shows predefined pipelines with their steps and cost estimates.
    """
    header("Available AI Pipelines")

    # Define available pipelines (these would normally come from a registry)
    pipelines = [
        {
            "name": "call_analysis",
            "description": "Full call analysis with transcription, PII redaction, summary, and coaching",
            "steps": ["transcribe", "redact_pii", "summarize", "analyze_sentiment", "generate_coaching"],
            "estimated_cost": "$0.05-0.15 per minute of audio",
            "estimated_duration": "2-5 minutes",
        },
        {
            "name": "transcription",
            "description": "Audio transcription with optional speaker diarization",
            "steps": ["transcribe"],
            "estimated_cost": "$0.006 per minute of audio",
            "estimated_duration": "~1x audio duration",
        },
        {
            "name": "pii_redaction",
            "description": "Detect and redact PII from text",
            "steps": ["detect_pii", "redact_text"],
            "estimated_cost": "$0.001 per 1000 characters",
            "estimated_duration": "<1 second per 1000 chars",
        },
        {
            "name": "summarization",
            "description": "Generate summary from transcript or text",
            "steps": ["summarize"],
            "estimated_cost": "$0.002 per 1000 tokens",
            "estimated_duration": "2-10 seconds",
        },
    ]

    for pipeline in pipelines:
        section(pipeline["name"])
        click.echo(f"  Description: {pipeline['description']}")
        click.echo(f"  Steps: {' -> '.join(pipeline['steps'])}")
        click.echo(f"  Estimated Cost: {pipeline['estimated_cost']}")
        click.echo(f"  Estimated Duration: {pipeline['estimated_duration']}")
        click.echo()

    success(f"Total: {len(pipelines)} pipelines available")


@ai.command(name="estimate")
@click.argument("pipeline_name")
@click.option(
    "--duration",
    "-d",
    type=int,
    help="Audio duration in seconds (for transcription pipelines)",
)
@click.option(
    "--characters",
    "-c",
    type=int,
    help="Number of characters (for text pipelines)",
)
@coro
async def estimate_cost(pipeline_name: str, duration: int | None, characters: int | None) -> None:
    """Estimate cost for running a pipeline.

    PIPELINE_NAME is the name of the pipeline to estimate costs for.

    Examples:
      example-service ai estimate call_analysis --duration 300
      example-service ai estimate pii_redaction --characters 10000
    """
    header(f"Cost Estimate: {pipeline_name}")

    # Cost estimates per provider/operation
    rates = {
        "transcription": 0.0001,  # per second of audio
        "pii_redaction": 0.000001,  # per character
        "summarization": 0.00001,  # per input character
        "sentiment": 0.000005,  # per character
        "coaching": 0.00002,  # per input character
    }

    pipeline_steps: dict[str, list[str]] = {
        "call_analysis": ["transcription", "pii_redaction", "summarization", "sentiment", "coaching"],
        "transcription": ["transcription"],
        "pii_redaction": ["pii_redaction"],
        "summarization": ["summarization"],
    }

    if pipeline_name not in pipeline_steps:
        error(f"Unknown pipeline: {pipeline_name}")
        info(f"Available pipelines: {', '.join(pipeline_steps.keys())}")
        sys.exit(1)

    steps = pipeline_steps[pipeline_name]

    total_cost = 0.0
    click.echo()

    for step in steps:
        step_cost = 0.0
        if step == "transcription" and duration:
            step_cost = rates["transcription"] * duration
            click.echo(f"  {step}: ${step_cost:.4f} ({duration}s audio)")
        elif step in ("pii_redaction", "summarization", "sentiment", "coaching") and characters:
            step_cost = rates[step] * characters
            click.echo(f"  {step}: ${step_cost:.4f} ({characters:,} chars)")
        elif step == "transcription" and not duration:
            warning(f"  {step}: Requires --duration for estimate")
        elif not characters:
            warning(f"  {step}: Requires --characters for estimate")

        total_cost += step_cost

    click.echo()
    click.echo(f"  Estimated Total: ${total_cost:.4f}")

    if not duration and "transcription" in steps:
        info("\nProvide --duration for transcription cost estimate")
    if not characters and any(s in steps for s in ["pii_redaction", "summarization"]):
        info("Provide --characters for text processing cost estimate")

    success("Estimate complete")
