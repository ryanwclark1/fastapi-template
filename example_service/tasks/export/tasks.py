"""Data export task definitions.

This module provides:
- CSV and JSON export of database records
- Flexible filtering and field selection
- Optional S3 upload of exports
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from example_service.core.settings import get_backup_settings
from example_service.infra.database.session import get_async_session
from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)

# Export directory
EXPORT_DIR = Path("/tmp/exports")


def ensure_export_dir() -> Path:
    """Ensure export directory exists."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR


if broker is not None:

    @broker.task()
    async def export_data_csv(
        model_name: str,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        upload_to_s3: bool = False,
    ) -> dict:
        """Export data to CSV file.

        Args:
            model_name: Name of model to export ("reminders", "users", etc.).
            filters: Optional query filters.
            fields: Optional list of fields to include (all if not specified).
            upload_to_s3: Whether to upload to S3 after export.

        Returns:
            Export result with file path and record count.

        Example:
                    from example_service.tasks.export import export_data_csv

            # Export all reminders
            task = await export_data_csv.kiq(model_name="reminders")

            # Export with filters
            task = await export_data_csv.kiq(
                model_name="reminders",
                filters={"is_completed": False},
            )
            result = await task.wait_result()
            print(result["filepath"])
        """
        export_dir = ensure_export_dir()

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{model_name}_{timestamp}.csv"
        filepath = export_dir / filename

        records = []
        fieldnames = []

        async with get_async_session() as session:
            if model_name == "reminders":
                from example_service.features.reminders.models import Reminder

                stmt = select(Reminder)

                # Apply filters if provided
                if filters:
                    if "is_completed" in filters:
                        stmt = stmt.where(Reminder.is_completed == filters["is_completed"])

                result = await session.execute(stmt)
                db_records = result.scalars().all()

                # Define fields for reminders
                default_fields = [
                    "id",
                    "title",
                    "description",
                    "remind_at",
                    "is_completed",
                    "notification_sent",
                    "created_at",
                    "updated_at",
                ]
                fieldnames = fields or default_fields

                for record in db_records:
                    row = {}
                    for field in fieldnames:
                        value = getattr(record, field, None)
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        elif hasattr(value, "__str__"):
                            value = str(value)
                        row[field] = value
                    records.append(row)

            else:
                return {
                    "status": "error",
                    "reason": f"Unknown model: {model_name}",
                }

        # Write CSV
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

        file_size = filepath.stat().st_size

        result = {
            "status": "success",
            "format": "csv",
            "model": model_name,
            "filepath": str(filepath),
            "filename": filename,
            "record_count": len(records),
            "size_bytes": file_size,
            "size_kb": round(file_size / 1024, 2),
            "timestamp": timestamp,
        }

        # Upload to S3 if requested
        if upload_to_s3:
            backup_settings = get_backup_settings()
            if backup_settings.is_s3_configured:
                try:
                    from example_service.infra.storage.s3 import S3Client

                    s3_client = S3Client(backup_settings)
                    s3_key = f"exports/{model_name}/{filename}"
                    s3_uri = await s3_client.upload_file(filepath, s3_key)
                    result["s3_uri"] = s3_uri
                except Exception as e:
                    logger.warning(f"Failed to upload export to S3: {e}")
                    result["s3_error"] = str(e)
            else:
                result["s3_skipped"] = "S3 not configured"

        logger.info("CSV export completed", extra=result)

        return result

    @broker.task()
    async def export_data_json(
        model_name: str,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        upload_to_s3: bool = False,
    ) -> dict:
        """Export data to JSON file.

        Args:
            model_name: Name of model to export.
            filters: Optional query filters.
            fields: Optional list of fields to include.
            upload_to_s3: Whether to upload to S3 after export.

        Returns:
            Export result with file path and record count.
        """
        export_dir = ensure_export_dir()

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{model_name}_{timestamp}.json"
        filepath = export_dir / filename

        records = []

        async with get_async_session() as session:
            if model_name == "reminders":
                from example_service.features.reminders.models import Reminder

                stmt = select(Reminder)

                if filters:
                    if "is_completed" in filters:
                        stmt = stmt.where(Reminder.is_completed == filters["is_completed"])

                result = await session.execute(stmt)
                db_records = result.scalars().all()

                default_fields = [
                    "id",
                    "title",
                    "description",
                    "remind_at",
                    "is_completed",
                    "notification_sent",
                    "created_at",
                    "updated_at",
                ]
                selected_fields = fields or default_fields

                for record in db_records:
                    row = {}
                    for field in selected_fields:
                        value = getattr(record, field, None)
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        elif hasattr(value, "__str__") and not isinstance(
                            value, (str, int, float, bool, type(None))
                        ):
                            value = str(value)
                        row[field] = value
                    records.append(row)

            else:
                return {
                    "status": "error",
                    "reason": f"Unknown model: {model_name}",
                }

        # Write JSON
        export_data = {
            "model": model_name,
            "exported_at": datetime.now(UTC).isoformat(),
            "record_count": len(records),
            "records": records,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        file_size = filepath.stat().st_size

        result = {
            "status": "success",
            "format": "json",
            "model": model_name,
            "filepath": str(filepath),
            "filename": filename,
            "record_count": len(records),
            "size_bytes": file_size,
            "size_kb": round(file_size / 1024, 2),
            "timestamp": timestamp,
        }

        # Upload to S3 if requested
        if upload_to_s3:
            backup_settings = get_backup_settings()
            if backup_settings.is_s3_configured:
                try:
                    from example_service.infra.storage.s3 import S3Client

                    s3_client = S3Client(backup_settings)
                    s3_key = f"exports/{model_name}/{filename}"
                    s3_uri = await s3_client.upload_file(filepath, s3_key)
                    result["s3_uri"] = s3_uri
                except Exception as e:
                    logger.warning(f"Failed to upload export to S3: {e}")
                    result["s3_error"] = str(e)
            else:
                result["s3_skipped"] = "S3 not configured"

        logger.info("JSON export completed", extra=result)

        return result

    @broker.task()
    async def list_exports() -> dict:
        """List available export files.

        Returns:
            Dictionary with list of export files.
        """
        export_dir = ensure_export_dir()

        exports = []
        for export_file in sorted(export_dir.glob("*.*"), reverse=True):
            if export_file.is_file():
                stat = export_file.stat()
                exports.append(
                    {
                        "filename": export_file.name,
                        "path": str(export_file),
                        "size_bytes": stat.st_size,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    }
                )

        return {
            "status": "success",
            "export_dir": str(export_dir),
            "count": len(exports),
            "exports": exports,
        }
