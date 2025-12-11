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
            sys.exit(1)
        except Exception:
            sys.exit(1)

    async def _show_stats(self, args: Namespace) -> None:
        """Fetch and display statistics from the tracking backend.

        Args:
            args: Parsed command-line arguments.
        """
        from example_service.infra.tasks.tracking import (
            get_tracker,
            start_tracker,
            stop_tracker,
        )

        # Initialize tracking backend
        await start_tracker()
        tracker = get_tracker()

        if tracker is None or not tracker.is_connected:
            return

        try:
            if args.running:
                # Show running tasks
                running = await tracker.get_running_tasks()
                if args.json:
                    pass
                else:
                    self._print_running_tasks(running)
            else:
                # Show statistics
                stats = await tracker.get_stats(hours=args.hours)
                if args.json:
                    pass
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
        stats.get("total_count", 0)
        stats.get("success_count", 0)
        stats.get("failure_count", 0)
        stats.get("running_count", 0)
        stats.get("cancelled_count", 0)


        avg_duration = stats.get("avg_duration_ms")
        if avg_duration is not None:
            pass

        by_task = stats.get("by_task_name", {})
        if by_task:
            for _task_name, _count in sorted(by_task.items(), key=lambda x: -x[1]):
                pass


    def _print_running_tasks(self, tasks: list[dict]) -> None:
        """Print running tasks in a human-readable format.

        Args:
            tasks: List of running task records.
        """
        if not tasks:
            return

        for task in tasks:
            task.get("task_id", "unknown")[:12]
            task.get("task_name", "unknown")
            running_for = task.get("running_for_ms", 0)
            task.get("worker_id", "unknown")

            running_for / 1000


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
