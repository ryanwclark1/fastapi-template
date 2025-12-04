"""Custom TaskIQ CLI commands.

This module provides custom CLI commands that integrate with TaskIQ's
command system. Commands registered here can be invoked via:

    taskiq <command-name> [options]

Commands are registered in pyproject.toml via entry points:

    [project.entry-points.taskiq_cli]
    track = "example_service.infra.tasks.cli:TrackingCommand"

Usage:
    taskiq track --hours 24
    taskiq track --help
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import TYPE_CHECKING

from taskiq.abc.cmd import TaskiqCMD

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Sequence


class TrackingCommand(TaskiqCMD):
    """Show task tracking statistics from Redis or PostgreSQL.

    This command connects to the configured tracking backend and
    displays summary statistics for recent task executions.

    Usage:
        taskiq track              # Show stats for last 24 hours
        taskiq track --hours 48   # Show stats for last 48 hours
        taskiq track --json       # Output as JSON
    """

    short_help = "Show task tracking statistics"

    def exec(self, args: Sequence[str]) -> None:
        """Execute the tracking command.

        Args:
            args: Command-line arguments passed to the command.
        """
        parser = argparse.ArgumentParser(
            prog="taskiq track",
            description="Display task execution statistics from the tracking backend.",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Number of hours to include in statistics (default: 24)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output as JSON instead of formatted text",
        )
        parser.add_argument(
            "--running",
            action="store_true",
            help="Show currently running tasks",
        )

        parsed_args = parser.parse_args(args)

        try:
            asyncio.run(self._show_stats(parsed_args))
        except KeyboardInterrupt:
            print("\nInterrupted")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    async def _show_stats(self, args: Namespace) -> None:
        """Fetch and display statistics from the tracking backend.

        Args:
            args: Parsed command-line arguments.
        """
        from example_service.infra.tasks.tracking import get_tracker, start_tracker, stop_tracker

        # Initialize tracking backend
        await start_tracker()
        tracker = get_tracker()

        if tracker is None or not tracker.is_connected:
            print("Task tracking is not configured or unavailable.", file=sys.stderr)
            print(
                "Ensure TASK_TRACKING_ENABLED=true and a result backend is configured.",
                file=sys.stderr,
            )
            return

        try:
            if args.running:
                # Show running tasks
                running = await tracker.get_running_tasks()
                if args.json:
                    print(json.dumps(running, indent=2, default=str))
                else:
                    self._print_running_tasks(running)
            else:
                # Show statistics
                stats = await tracker.get_stats(hours=args.hours)
                if args.json:
                    print(json.dumps(stats, indent=2, default=str))
                else:
                    self._print_stats(stats, args.hours)
        finally:
            await stop_tracker()

    def _print_stats(self, stats: dict, hours: int) -> None:
        """Print statistics in a human-readable format.

        Args:
            stats: Statistics dictionary from the tracker.
            hours: Number of hours covered by the statistics.
        """
        print(f"\n{'='*50}")
        print(f"  Task Execution Statistics (Last {hours} hours)")
        print(f"{'='*50}\n")

        total = stats.get("total_count", 0)
        success = stats.get("success_count", 0)
        failure = stats.get("failure_count", 0)
        running = stats.get("running_count", 0)
        cancelled = stats.get("cancelled_count", 0)

        print(f"  Total Tasks:     {total:>8}")
        print(f"  Successful:      {success:>8}  ({self._pct(success, total)})")
        print(f"  Failed:          {failure:>8}  ({self._pct(failure, total)})")
        print(f"  Running:         {running:>8}")
        print(f"  Cancelled:       {cancelled:>8}")

        avg_duration = stats.get("avg_duration_ms")
        if avg_duration is not None:
            print(f"\n  Avg Duration:    {avg_duration:>8.1f}ms")

        by_task = stats.get("by_task_name", {})
        if by_task:
            print("\n  By Task Name:")
            print(f"  {'-'*40}")
            for task_name, count in sorted(by_task.items(), key=lambda x: -x[1]):
                print(f"    {task_name:<30} {count:>6}")

        print(f"\n{'='*50}\n")

    def _print_running_tasks(self, tasks: list[dict]) -> None:
        """Print running tasks in a human-readable format.

        Args:
            tasks: List of running task records.
        """
        print(f"\n{'='*60}")
        print("  Currently Running Tasks")
        print(f"{'='*60}\n")

        if not tasks:
            print("  No tasks currently running.\n")
            return

        for task in tasks:
            task_id = task.get("task_id", "unknown")[:12]
            task_name = task.get("task_name", "unknown")
            running_for = task.get("running_for_ms", 0)
            worker_id = task.get("worker_id", "unknown")

            running_sec = running_for / 1000
            print(f"  Task: {task_name}")
            print(f"    ID:          {task_id}...")
            print(f"    Running for: {running_sec:.1f}s")
            print(f"    Worker:      {worker_id}")
            print()

        print(f"{'='*60}\n")

    def _pct(self, part: int, total: int) -> str:
        """Calculate percentage string.

        Args:
            part: Part value.
            total: Total value.

        Returns:
            Formatted percentage string.
        """
        if total == 0:
            return "0.0%"
        return f"{(part / total * 100):.1f}%"
