"""Scheduler management commands.

This module provides CLI commands for managing APScheduler jobs:
- List scheduled jobs
- Trigger jobs manually
- Pause/resume jobs
- View scheduler status
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import UTC, datetime
from typing import Any

import click

from example_service.cli.utils import coro, error, header, info, section, success, warning


@click.group(name="scheduler")
def scheduler() -> None:
    """Scheduled job management commands."""


@scheduler.command(name="list")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@coro
async def list_jobs(output_format: str) -> None:
    """List all scheduled jobs with their next run times."""
    header("Scheduled Jobs")

    try:
        from example_service.tasks.scheduler import get_job_status
        from example_service.tasks.scheduler import scheduler as apscheduler

        if not apscheduler.running:
            warning("Scheduler is not running")
            info("Jobs are registered but scheduler needs to be started with the application")
            info("The following jobs are configured:")
            click.echo()

        jobs = get_job_status()

        if not jobs:
            info("No scheduled jobs found")
            return

        if output_format == "json":
            import json
            click.echo(json.dumps(jobs, indent=2))
            return

        # Table format
        now = datetime.now(UTC)

        # Calculate column widths
        id_width = max(len(j["id"]) for j in jobs) + 2
        name_width = max(len(j["name"]) for j in jobs) + 2

        click.echo()
        click.echo(
            f"{'ID':<{id_width}} {'Name':<{name_width}} {'Next Run':<25} {'Trigger':<30}"
        )
        click.echo("-" * (id_width + name_width + 55))

        for job in jobs:
            next_run = job["next_run_time"]
            if next_run:
                next_dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
                time_until = next_dt - now
                if time_until.total_seconds() > 0:
                    hours, remainder = divmod(int(time_until.total_seconds()), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    if hours > 24:
                        time_str = f"{hours // 24}d {hours % 24}h"
                    elif hours > 0:
                        time_str = f"{hours}h {minutes}m"
                    else:
                        time_str = f"{minutes}m {seconds}s"
                    next_display = f"{next_run[:19]} ({time_str})"
                else:
                    next_display = f"{next_run[:19]} (overdue)"
            else:
                next_display = click.style("paused", fg="yellow")

            click.echo(
                f"{job['id']:<{id_width}} {job['name']:<{name_width}} {next_display:<25} {job['trigger']:<30}"
            )

        click.echo()
        success(f"Total: {len(jobs)} scheduled jobs")

    except ImportError as e:
        error(f"Failed to import scheduler: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to list jobs: {e}")
        sys.exit(1)


async def _wait_for_task_result(result: Any) -> Any | None:
    """Best-effort wait for Taskiq AsyncResult objects."""
    wait_callable = getattr(result, "wait_result", None)
    if callable(wait_callable):
        waited = wait_callable()
        if inspect.isawaitable(waited):
            return await waited
        return waited
    return None


@scheduler.command(name="run")
@click.argument("job_id")
@click.option(
    "--wait/--no-wait",
    default=False,
    help="Wait for task completion (when job triggers Taskiq task)",
)
@coro
async def run_job(job_id: str, wait: bool) -> None:
    """Manually trigger a scheduled job immediately.

    JOB_ID is the ID of the scheduled job (e.g., cleanup_sessions, hourly_metrics).

    This will execute the job's function immediately, regardless of its schedule.

    Examples:

    \b
      example-service scheduler run cleanup_sessions
      example-service scheduler run database_backup --wait
    """
    info(f"Triggering job: {job_id}")

    try:
        from example_service.tasks.scheduler import scheduler as apscheduler

        job = apscheduler.get_job(job_id)

        if job is None:
            error(f"Job '{job_id}' not found")
            info("Use 'example-service scheduler list' to see available jobs")
            sys.exit(1)

        info(f"Job found: {job.name}")
        info(f"Trigger: {job.trigger}")

        # Get the job's function
        job_func = job.func

        # Execute the job function
        click.echo()
        info("Executing job function...")

        try:
            # Initialize broker if needed for Taskiq tasks
            from example_service.tasks.broker import broker
            if broker is not None:
                await broker.startup()

            try:
                # Call the job function (which may enqueue a Taskiq task)
                if asyncio.iscoroutinefunction(job_func):
                    result = await job_func()
                else:
                    result = job_func()

                success("Job triggered successfully!")

                awaited_payload = None
                if wait:
                    awaited_payload = await _wait_for_task_result(result)

                if result is not None:
                    click.echo(f"  Result: {result}")
                if awaited_payload is not None:
                    click.echo(f"  Wait Result: {awaited_payload}")

            finally:
                if broker is not None:
                    await broker.shutdown()

        except Exception as e:
            error(f"Job execution failed: {e}")
            sys.exit(1)

    except ImportError as e:
        error(f"Failed to import scheduler: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to trigger job: {e}")
        sys.exit(1)


@scheduler.command(name="pause")
@click.argument("job_id")
@coro
async def pause_job(job_id: str) -> None:
    """Pause a scheduled job.

    JOB_ID is the ID of the scheduled job to pause.

    The job will not run until it is resumed.
    """
    try:
        from example_service.tasks.scheduler import pause_job as do_pause
        from example_service.tasks.scheduler import scheduler as apscheduler

        job = apscheduler.get_job(job_id)
        if job is None:
            error(f"Job '{job_id}' not found")
            sys.exit(1)

        if job.next_run_time is None:
            warning(f"Job '{job_id}' is already paused")
            return

        do_pause(job_id)
        success(f"Job '{job_id}' has been paused")
        info("Use 'example-service scheduler resume' to resume the job")

    except Exception as e:
        error(f"Failed to pause job: {e}")
        sys.exit(1)


@scheduler.command(name="resume")
@click.argument("job_id")
@coro
async def resume_job(job_id: str) -> None:
    """Resume a paused scheduled job.

    JOB_ID is the ID of the scheduled job to resume.
    """
    try:
        from example_service.tasks.scheduler import resume_job as do_resume
        from example_service.tasks.scheduler import scheduler as apscheduler

        job = apscheduler.get_job(job_id)
        if job is None:
            error(f"Job '{job_id}' not found")
            sys.exit(1)

        if job.next_run_time is not None:
            warning(f"Job '{job_id}' is not paused")
            return

        do_resume(job_id)
        success(f"Job '{job_id}' has been resumed")

        # Show next run time
        job = apscheduler.get_job(job_id)
        if job and job.next_run_time:
            info(f"Next run: {job.next_run_time.isoformat()}")

    except Exception as e:
        error(f"Failed to resume job: {e}")
        sys.exit(1)


@scheduler.command(name="status")
@coro
async def scheduler_status() -> None:
    """Show scheduler status and statistics."""
    header("Scheduler Status")

    try:
        from example_service.tasks.scheduler import scheduler as apscheduler

        click.echo()
        click.echo(f"  Running:    {'Yes' if apscheduler.running else 'No'}")
        click.echo(f"  Timezone:   {apscheduler.timezone}")

        jobs = apscheduler.get_jobs()
        paused_jobs = [j for j in jobs if j.next_run_time is None]
        active_jobs = [j for j in jobs if j.next_run_time is not None]

        click.echo(f"  Total Jobs: {len(jobs)}")
        click.echo(f"  Active:     {len(active_jobs)}")
        click.echo(f"  Paused:     {len(paused_jobs)}")

        if not apscheduler.running:
            click.echo()
            warning("Scheduler is not running!")
            info("Start the application to run scheduled jobs")
            info("Or use 'example-service scheduler run <job_id>' to manually trigger jobs")

        # Show next 5 upcoming jobs
        if active_jobs:
            click.echo()
            section("Upcoming Jobs (next 5)")

            # Sort by next run time
            upcoming = sorted(active_jobs, key=lambda j: j.next_run_time)[:5]

            for job in upcoming:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z")
                click.echo(f"  {job.id}: {next_run}")

    except ImportError as e:
        error(f"Failed to import scheduler: {e}")
        sys.exit(1)
    except Exception as e:
        error(f"Failed to get scheduler status: {e}")
        sys.exit(1)


@scheduler.command(name="jobs")
@click.argument("category", required=False)
@coro
async def show_jobs_by_category(category: str | None) -> None:
    """Show detailed information about scheduled jobs.

    Optionally filter by CATEGORY (cleanup, backup, metrics, notifications).
    """
    header("Scheduled Jobs Detail")

    job_categories = {
        "cleanup": ["cleanup_sessions", "temp_cleanup", "backup_cleanup", "export_cleanup", "data_cleanup"],
        "backup": ["database_backup"],
        "metrics": ["hourly_metrics"],
        "sync": ["sync_external"],
        "notifications": ["daily_digest", "check_reminders"],
        "monitoring": ["heartbeat", "cache_warming"],
    }

    try:
        from example_service.tasks.scheduler import scheduler as apscheduler

        jobs = apscheduler.get_jobs()

        if category:
            if category not in job_categories:
                error(f"Unknown category: {category}")
                info(f"Available categories: {', '.join(job_categories.keys())}")
                sys.exit(1)

            job_ids = job_categories[category]
            jobs = [j for j in jobs if j.id in job_ids]

            if not jobs:
                info(f"No jobs found in category: {category}")
                return

        click.echo()

        for job in jobs:
            # Determine category
            job_category = "other"
            for cat, ids in job_categories.items():
                if job.id in ids:
                    job_category = cat
                    break

            status = "active" if job.next_run_time else "paused"
            status_color = "green" if status == "active" else "yellow"

            click.secho(f"Job: {job.id}", bold=True)
            click.echo(f"  Name:       {job.name}")
            click.echo(f"  Category:   {job_category}")
            click.echo("  Status:     ", nl=False)
            click.secho(status, fg=status_color)
            click.echo(f"  Trigger:    {job.trigger}")

            if job.next_run_time:
                click.echo(f"  Next Run:   {job.next_run_time.isoformat()}")
            else:
                click.echo("  Next Run:   N/A (paused)")

            click.echo()

    except Exception as e:
        error(f"Failed to show jobs: {e}")
        sys.exit(1)
