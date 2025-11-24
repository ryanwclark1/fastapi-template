"""Background task definitions.

This module contains the actual background tasks that can be scheduled
and executed asynchronously using Taskiq.
"""
from __future__ import annotations

import logging
from typing import Any

from taskiq import TaskiqDepends

from example_service.core.tasks.broker import broker

logger = logging.getLogger(__name__)


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
        ```python
        # Schedule the task
        task = await example_task.kiq(data={"key": "value"})

        # Get the task ID
        task_id = task.task_id

        # Later, retrieve the result
        result = await task.wait_result()
        ```
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
    logger.info("Sending email", extra={"to": to, "subject": subject})

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
