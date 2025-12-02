"""Background task definitions.

This module contains the actual background tasks that can be scheduled
and executed asynchronously using Taskiq.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import ProgressTracker  # noqa: TC002

from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)


if broker is not None:

    @broker.task()
    async def example_task(data: dict[str, Any]) -> dict[str, Any]:
        """Example background task.

        This task demonstrates how to define and execute background tasks
        using Taskiq. Tasks are executed asynchronously and their results
        can be retrieved later using the task ID.

        Args:
            data: Input data for the task.

        Returns:
            Processed result data.

        Example:
                # Schedule the task
            task = await example_task.kiq(data={"key": "value"})

            # Get the task ID
            task_id = task.task_id

            # Later, retrieve the result
            result = await task.wait_result()
        """
        logger.info("Executing example_task", extra={"data": data})

        try:
            # TODO: Implement your task logic here
            # For example:
            # - Process large datasets
            # - Send emails
            # - Generate reports
            # - Call external APIs
            # - Perform data transformations

            result = {"status": "completed", "processed_data": data}

            logger.info("Example task completed successfully", extra={"result": result})
            return result
        except Exception as e:
            logger.exception("Example task failed", extra={"error": str(e)})
            raise

    @broker.task(retry_on_error=True, max_retries=3)
    async def example_retry_task(data: dict[str, Any]) -> dict[str, Any]:
        """Example task with automatic retry on failure.

        This task will automatically retry up to 3 times if it fails.

        Args:
            data: Input data for the task.

        Returns:
            Processed result data.
        """
        logger.info("Executing example_retry_task", extra={"data": data})

        try:
            # TODO: Implement your task logic here
            result = {"status": "completed", "data": data}

            logger.info("Retry task completed successfully", extra={"result": result})
            return result
        except Exception as e:
            logger.exception("Retry task failed", extra={"error": str(e)})
            raise

    @broker.task()
    async def send_email_task(
        to: str,
        subject: str,
        body: str,
    ) -> dict[str, str]:
        """Send email asynchronously.

        Example task for sending emails in the background without
        blocking the main request.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body content.

        Returns:
            Send status.
        """
        logger.info(
            "Sending email",
            extra={"to": to, "subject": subject, "body_length": len(body)},
        )

        try:
            # TODO: Implement email sending logic
            # For example, using an email service like SendGrid, AWS SES, etc.

            logger.info("Email sent successfully", extra={"to": to})
            return {"status": "sent", "to": to}
        except Exception as e:
            logger.exception("Failed to send email", extra={"to": to, "error": str(e)})
            raise

    @broker.task()
    async def process_uploaded_file_task(
        file_path: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Process uploaded file asynchronously.

        Example task for processing large file uploads in the background.

        Args:
            file_path: Path to the uploaded file.
            user_id: ID of the user who uploaded the file.

        Returns:
            Processing result.
        """
        logger.info(
            "Processing uploaded file",
            extra={"file_path": file_path, "user_id": user_id},
        )

        try:
            # TODO: Implement file processing logic
            # For example:
            # - Parse CSV/Excel files
            # - Process images
            # - Extract text from PDFs
            # - Run data validation

            logger.info("File processed successfully", extra={"file_path": file_path})
            return {
                "status": "processed",
                "file_path": file_path,
                "records_processed": 0,  # TODO: Replace with actual count
            }
        except Exception as e:
            logger.exception(
                "Failed to process file",
                extra={"file_path": file_path, "error": str(e)},
            )
            raise

    @broker.task()
    async def batch_process_task(
        items: list[dict[str, Any]],
        delay_per_item: float = 0.1,
        progress: ProgressTracker[dict[str, Any]] = TaskiqDepends(),  # noqa: B008
    ) -> dict[str, Any]:
        """Example task demonstrating progress tracking.

        This task processes items in a batch and reports progress after
        each item is processed. Progress can be monitored via:

        - REST API: GET /api/v1/tasks/{task_id}
        - Result backend: await result.get_progress()

        The progress tracker stores:
        - state: Current state (STARTED, SUCCESS, FAILURE, RETRY, or custom string)
        - meta: Custom metadata dict with progress details

        Args:
            items: List of items to process.
            delay_per_item: Simulated processing delay per item (seconds).
            progress: TaskIQ progress tracker (injected automatically).

        Returns:
            Processing summary with counts and status.

        Example:
                # Schedule the task with progress tracking
            task = await batch_process_task.kiq(
                items=[{"id": 1}, {"id": 2}, {"id": 3}],
                delay_per_item=0.5,
            )

            # Poll for progress while task is running
            while True:
                progress_data = await task.get_progress()
                if progress_data:
                    print(f"State: {progress_data.state}, Meta: {progress_data.meta}")
                if await task.is_ready():
                    break
                await asyncio.sleep(0.5)

            # Get final result
            result = await task.wait_result()
        """
        total = len(items)
        processed = 0
        failed = 0

        logger.info(
            "Starting batch processing",
            extra={"total_items": total, "delay_per_item": delay_per_item},
        )

        # Report initial progress
        await progress.set_progress(
            state="STARTED",
            meta={
                "current": 0,
                "total": total,
                "status": "initializing",
            },
        )

        for item in items:
            item_id = item.get("id", "unknown")

            try:
                # Simulate processing work
                await asyncio.sleep(delay_per_item)

                processed += 1

                # Report progress to result backend
                # State can be a TaskState enum or custom string
                await progress.set_progress(
                    state="processing",
                    meta={
                        "current": processed,
                        "total": total,
                        "last_item_id": item_id,
                        "failed_count": failed,
                    },
                )

                logger.debug(
                    "Item processed",
                    extra={"item_id": item_id, "progress": f"{processed}/{total}"},
                )

            except Exception as e:
                failed += 1
                logger.warning(
                    "Item processing failed",
                    extra={"item_id": item_id, "error": str(e)},
                )
                # Continue processing other items

        logger.info(
            "Batch processing completed",
            extra={"processed": processed, "failed": failed, "total": total},
        )

        return {
            "status": "completed",
            "processed": processed,
            "failed": failed,
            "total": total,
        }
