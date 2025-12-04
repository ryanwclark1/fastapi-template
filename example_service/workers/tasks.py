"""Background task definitions.

This module contains the actual background tasks that can be scheduled
and executed asynchronously using Taskiq.

These are example implementations demonstrating common patterns:
- Data transformation tasks
- Email sending (delegates to notification tasks)
- File processing with progress tracking
- Retry patterns for transient failures
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from taskiq import TaskiqDepends
from taskiq.depends.progress_tracker import ProgressTracker  # noqa: TC002

from example_service.infra.tasks.broker import broker

logger = logging.getLogger(__name__)


if broker is not None:

    @broker.task()
    async def example_task(data: dict[str, Any]) -> dict[str, Any]:
        """Example background task for data transformation.

        This task demonstrates how to define and execute background tasks
        using Taskiq. Tasks are executed asynchronously and their results
        can be retrieved later using the task ID.

        Args:
            data: Input data for the task. Expected structure:
                - action: str - The action to perform (transform, validate, enrich)
                - payload: dict - The data to process
                - options: dict - Optional processing options

        Returns:
            Processed result data with status and transformed payload.

        Example:
            # Schedule the task
            task = await example_task.kiq(data={
                "action": "transform",
                "payload": {"name": "John", "age": 30},
                "options": {"uppercase_name": True}
            })

            # Get the task ID
            task_id = task.task_id

            # Later, retrieve the result
            result = await task.wait_result()
        """
        logger.info("Executing example_task", extra={"data": data})

        try:
            action = data.get("action", "transform")
            payload = data.get("payload", {})
            options = data.get("options", {})

            # Perform action based on type
            result_payload: dict[str, Any]
            if action == "transform":
                # Example: Transform data (uppercase names, format dates, etc.)
                transformed = {}
                for key, value in payload.items():
                    if isinstance(value, str) and options.get("uppercase_name") and key == "name":
                        transformed[key] = value.upper()
                    else:
                        transformed[key] = value
                result_payload = transformed

            elif action == "validate":
                # Example: Validate data structure
                required_fields = options.get("required_fields", [])
                missing = [f for f in required_fields if f not in payload]
                result_payload = {
                    "valid": len(missing) == 0,
                    "missing_fields": missing,
                    "validated_data": payload,
                }

            elif action == "enrich":
                # Example: Enrich data with computed fields
                enriched = dict(payload)
                if "created_at" not in enriched:
                    from datetime import UTC, datetime
                    enriched["created_at"] = datetime.now(UTC).isoformat()
                if "id" not in enriched:
                    from uuid import uuid4
                    enriched["id"] = str(uuid4())
                result_payload = enriched

            else:
                # Unknown action - return data as-is
                result_payload = payload

            result = {
                "status": "completed",
                "action": action,
                "processed_data": result_payload,
                "options_applied": list(options.keys()),
            }

            logger.info("Example task completed successfully", extra={"action": action})
            return result

        except Exception as e:
            logger.exception("Example task failed", extra={"error": str(e)})
            raise

    @broker.task(retry_on_error=True, max_retries=3)
    async def example_retry_task(data: dict[str, Any]) -> dict[str, Any]:
        """Example task with automatic retry on failure.

        This task demonstrates retry patterns for transient failures.
        It will automatically retry up to 3 times if it fails.

        Use this pattern for:
        - External API calls that may timeout
        - Database operations during high load
        - Network operations with intermittent failures

        Args:
            data: Input data for the task. Expected structure:
                - operation: str - Operation to perform
                - retry_test: bool - If True, simulates a failure for testing
                - payload: dict - Data to process

        Returns:
            Processed result data.
        """
        logger.info("Executing example_retry_task", extra={"data": data})

        try:
            operation = data.get("operation", "default")
            payload = data.get("payload", {})

            # Simulate transient failure for testing (first 2 attempts fail)
            if data.get("retry_test"):
                attempt = data.get("_attempt", 1)
                if attempt < 3:
                    data["_attempt"] = attempt + 1
                    raise ConnectionError(f"Simulated transient failure (attempt {attempt})")

            # Perform the actual operation
            result = {
                "status": "completed",
                "operation": operation,
                "data": payload,
                "message": f"Successfully processed {operation}",
            }

            logger.info("Retry task completed successfully", extra={"operation": operation})
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

        This is a simple wrapper that delegates to the notification tasks
        for actual email delivery. For full-featured email sending with
        templates and multi-tenant support, use the tasks in
        example_service.workers.notifications.tasks.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body content.

        Returns:
            Send status with task reference.
        """
        from example_service.workers.notifications.tasks import (
            send_email_task as notification_send_email,
        )

        logger.info(
            "Delegating email to notification task",
            extra={"to": to, "subject": subject, "body_length": len(body)},
        )

        try:
            # Delegate to the notification tasks which have full email service integration
            task = await notification_send_email.kiq(
                to=[to],
                subject=subject,
                body=body,
            )

            logger.info(
                "Email task delegated successfully",
                extra={"to": to, "delegate_task_id": task.task_id},
            )

            return {
                "status": "delegated",
                "to": to,
                "delegate_task_id": task.task_id,
            }
        except Exception as e:
            logger.exception("Failed to delegate email task", extra={"to": to, "error": str(e)})
            raise

    @broker.task()
    async def process_uploaded_file_task(
        file_path: str,
        user_id: str,
        processing_type: str = "auto",
    ) -> dict[str, Any]:
        """Process uploaded file asynchronously.

        Processes various file types in the background:
        - CSV/Excel: Parse and validate data
        - Images: Generate thumbnails, extract metadata
        - PDFs: Extract text content
        - JSON: Validate structure

        Args:
            file_path: Path to the uploaded file.
            user_id: ID of the user who uploaded the file.
            processing_type: Type of processing (auto, csv, image, pdf, json).
                           'auto' will detect based on file extension.

        Returns:
            Processing result with file info and extracted data.
        """
        logger.info(
            "Processing uploaded file",
            extra={"file_path": file_path, "user_id": user_id, "type": processing_type},
        )

        try:
            path = Path(file_path)

            # Verify file exists
            if not path.exists():
                return {
                    "status": "error",
                    "error": "file_not_found",
                    "file_path": file_path,
                    "records_processed": 0,
                }

            # Get file info
            file_info = {
                "name": path.name,
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
            }

            # Determine processing type
            if processing_type == "auto":
                ext = path.suffix.lower()
                type_map = {
                    ".csv": "csv",
                    ".xlsx": "csv",
                    ".xls": "csv",
                    ".json": "json",
                    ".pdf": "pdf",
                    ".png": "image",
                    ".jpg": "image",
                    ".jpeg": "image",
                    ".gif": "image",
                }
                processing_type = type_map.get(ext, "unknown")

            records_processed = 0
            extracted_data: dict[str, Any] = {}

            if processing_type == "csv":
                # Process CSV/Excel files
                try:
                    import csv
                    with open(path, newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                        records_processed = len(rows)
                        extracted_data = {
                            "headers": reader.fieldnames or [],
                            "row_count": records_processed,
                            "sample_rows": rows[:5] if rows else [],
                        }
                except Exception as e:
                    extracted_data = {"parse_error": str(e)}

            elif processing_type == "json":
                # Validate JSON structure
                try:
                    import json
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            records_processed = len(data)
                            extracted_data = {
                                "type": "array",
                                "count": records_processed,
                                "sample": data[:5] if data else [],
                            }
                        elif isinstance(data, dict):
                            records_processed = 1
                            extracted_data = {
                                "type": "object",
                                "keys": list(data.keys())[:20],
                            }
                except json.JSONDecodeError as e:
                    extracted_data = {"parse_error": str(e)}

            elif processing_type == "image":
                # Extract image metadata
                records_processed = 1
                extracted_data = {
                    "type": "image",
                    "size_bytes": file_info["size_bytes"],
                    # In production, you'd use PIL/Pillow to get dimensions, EXIF, etc.
                    "note": "Image processing available with PIL/Pillow",
                }

            elif processing_type == "pdf":
                # PDF text extraction placeholder
                records_processed = 1
                extracted_data = {
                    "type": "pdf",
                    "size_bytes": file_info["size_bytes"],
                    # In production, you'd use PyPDF2 or pdfplumber
                    "note": "PDF processing available with PyPDF2/pdfplumber",
                }

            else:
                # Unknown file type - just return file info
                extracted_data = {"note": f"Unknown file type: {processing_type}"}

            logger.info(
                "File processed successfully",
                extra={
                    "file_path": file_path,
                    "processing_type": processing_type,
                    "records": records_processed,
                },
            )

            return {
                "status": "processed",
                "file_path": file_path,
                "user_id": user_id,
                "file_info": file_info,
                "processing_type": processing_type,
                "records_processed": records_processed,
                "extracted_data": extracted_data,
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
