"""Data transfer service for export and import operations.

Provides high-level interface for exporting and importing data
with progress tracking, validation, and storage integration.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

from .exporters import get_exporter
from .importers import ParsedRecord, get_importer
from .schemas import (
    ExportRequest,
    ExportResult,
    ExportStatus,
    ImportFormat,
    ImportResult,
    ImportStatus,
    ImportValidationError,
    SupportedEntity,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    pass

logger = logging.getLogger(__name__)

# Export directory (development/testing - use proper temp directory in production)
EXPORT_DIR = Path("/tmp/exports")  # noqa: S108


def ensure_export_dir() -> Path:
    """Ensure export directory exists."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR


# Entity registry - maps entity names to their model, fields, and configuration
ENTITY_REGISTRY: dict[str, dict[str, Any]] = {
    "reminders": {
        "display_name": "Reminders",
        "model_path": "example_service.features.reminders.models.Reminder",
        "fields": [
            "id",
            "title",
            "description",
            "remind_at",
            "is_completed",
            "notification_sent",
            "created_at",
            "updated_at",
        ],
        "required_fields": ["title"],
        "field_types": {
            "is_completed": bool,
            "notification_sent": bool,
        },
        "exportable": True,
        "importable": True,
    },
    "files": {
        "display_name": "Files",
        "model_path": "example_service.features.files.models.File",
        "fields": [
            "id",
            "filename",
            "original_filename",
            "content_type",
            "size",
            "storage_path",
            "created_at",
            "updated_at",
        ],
        "required_fields": ["filename"],
        "exportable": True,
        "importable": False,  # Files need special handling
    },
    "webhooks": {
        "display_name": "Webhooks",
        "model_path": "example_service.features.webhooks.models.Webhook",
        "fields": [
            "id",
            "name",
            "url",
            "events",
            "is_active",
            "secret",
            "created_at",
            "updated_at",
        ],
        "required_fields": ["name", "url"],
        "field_types": {
            "is_active": bool,
        },
        "exportable": True,
        "importable": True,
    },
    "audit_logs": {
        "display_name": "Audit Logs",
        "model_path": "example_service.features.audit.models.AuditLog",
        "fields": [
            "id",
            "timestamp",
            "action",
            "entity_type",
            "entity_id",
            "user_id",
            "tenant_id",
            "old_values",
            "new_values",
            "ip_address",
            "success",
            "duration_ms",
        ],
        "required_fields": [],
        "exportable": True,
        "importable": False,  # Audit logs are read-only
    },
}


class DataTransferService:
    """Service for data export and import operations.

    Provides methods for:
    - Exporting data to CSV, JSON, or Excel
    - Importing data from various formats with validation
    - Progress tracking for long-running operations
    - Storage integration for large exports

    Example:
        service = DataTransferService(session)

        # Export reminders to CSV
        result = await service.export(ExportRequest(
            entity_type="reminders",
            format=ExportFormat.CSV,
        ))

        # Import from file
        result = await service.import_from_file(
            file_path="/path/to/import.csv",
            entity_type="reminders",
            format=ImportFormat.CSV,
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize data transfer service.

        Args:
            session: Async database session.
        """
        self.session = session

    def get_supported_entities(self) -> list[SupportedEntity]:
        """Get list of entities supported for data transfer.

        Returns:
            List of supported entities with their configuration.
        """
        return [
            SupportedEntity(
                name=name,
                display_name=config["display_name"],
                exportable=config.get("exportable", True),
                importable=config.get("importable", True),
                fields=config.get("fields", []),
                required_fields=config.get("required_fields", []),
            )
            for name, config in ENTITY_REGISTRY.items()
        ]

    def _get_entity_config(self, entity_type: str) -> dict[str, Any]:
        """Get configuration for an entity type.

        Args:
            entity_type: Entity type name.

        Returns:
            Entity configuration.

        Raises:
            ValueError: If entity type is not supported.
        """
        if entity_type not in ENTITY_REGISTRY:
            raise ValueError(
                f"Unknown entity type: {entity_type}. "
                f"Supported types: {list(ENTITY_REGISTRY.keys())}"
            )
        return ENTITY_REGISTRY[entity_type]

    def _import_model(self, model_path: str) -> type[Any]:
        """Dynamically import a model class.

        Args:
            model_path: Full module path to model class.

        Returns:
            Model class.
        """
        parts = model_path.rsplit(".", 1)
        module_path, class_name = parts
        import importlib

        module = importlib.import_module(module_path)
        model_class = getattr(module, class_name)
        return cast("type[Any]", model_class)

    async def export(self, request: ExportRequest) -> ExportResult:
        """Export data to a file.

        Args:
            request: Export request with entity type, format, and filters.

        Returns:
            Export result with file path and statistics.
        """
        export_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)

        try:
            # Get entity configuration
            config = self._get_entity_config(request.entity_type)
            if not config.get("exportable", True):
                raise ValueError(f"Entity '{request.entity_type}' is not exportable")

            # Import the model
            model_class = self._import_model(config["model_path"])

            # Build query
            stmt = select(model_class)

            # Apply filters if provided
            if request.filters:
                for field, value in request.filters.items():
                    if hasattr(model_class, field):
                        stmt = stmt.where(getattr(model_class, field) == value)

            # Execute query
            result = await self.session.execute(stmt)
            records = result.scalars().all()

            # Get exporter
            exporter = get_exporter(
                format=request.format.value,
                fields=request.fields or config.get("fields"),
                include_headers=request.include_headers,
            )

            # Generate filename
            export_dir = ensure_export_dir()
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"{request.entity_type}_{timestamp}.{exporter.file_extension}"
            file_path = export_dir / filename

            # Export to file
            record_count = exporter.export(list(records), file_path)
            file_size = file_path.stat().st_size

            # Upload to storage if requested
            storage_uri = None
            if request.upload_to_storage:
                storage_uri = await self._upload_to_storage(file_path, request.entity_type)

            return ExportResult(
                status=ExportStatus.COMPLETED,
                export_id=export_id,
                entity_type=request.entity_type,
                format=request.format,
                file_path=str(file_path),
                file_name=filename,
                record_count=record_count,
                size_bytes=file_size,
                storage_uri=storage_uri,
                download_url=f"/api/v1/data-transfer/exports/{export_id}/download",
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.exception(f"Export failed for {request.entity_type}")
            return ExportResult(
                status=ExportStatus.FAILED,
                export_id=export_id,
                entity_type=request.entity_type,
                format=request.format,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error_message=str(e),
            )

    async def export_to_bytes(self, request: ExportRequest) -> tuple[bytes, str, str]:
        """Export data to bytes for streaming download.

        Args:
            request: Export request.

        Returns:
            Tuple of (data bytes, content_type, filename).
        """
        config = self._get_entity_config(request.entity_type)
        if not config.get("exportable", True):
            raise ValueError(f"Entity '{request.entity_type}' is not exportable")

        # Import the model
        model_class = self._import_model(config["model_path"])

        # Build and execute query
        stmt = select(model_class)
        if request.filters:
            for field, value in request.filters.items():
                if hasattr(model_class, field):
                    stmt = stmt.where(getattr(model_class, field) == value)

        result = await self.session.execute(stmt)
        records = result.scalars().all()

        # Get exporter and export
        exporter = get_exporter(
            format=request.format.value,
            fields=request.fields or config.get("fields"),
            include_headers=request.include_headers,
        )

        data = exporter.export_to_bytes(list(records))
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{request.entity_type}_{timestamp}.{exporter.file_extension}"

        return data, exporter.content_type, filename

    async def import_from_bytes(
        self,
        data: bytes,
        entity_type: str,
        format: ImportFormat,
        validate_only: bool = False,
        skip_errors: bool = False,
        update_existing: bool = False,
    ) -> ImportResult:
        """Import data from bytes.

        Args:
            data: Raw file data.
            entity_type: Type of entity to import.
            format: Import file format.
            validate_only: Only validate, don't import.
            skip_errors: Continue importing even if some records fail.
            update_existing: Update existing records instead of skipping.

        Returns:
            Import result with statistics and validation errors.
        """
        import_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)

        try:
            # Get entity configuration
            config = self._get_entity_config(entity_type)
            if not config.get("importable", True):
                raise ValueError(f"Entity '{entity_type}' is not importable")

            # Get importer
            importer = get_importer(
                format=format.value,
                required_fields=config.get("required_fields", []),
                field_types=config.get("field_types", {}),
            )

            # Parse and validate records
            parsed_records = importer.parse_bytes(data)
            total_rows = len(parsed_records)

            # Collect validation errors
            validation_errors: list[ImportValidationError] = []
            valid_records: list[ParsedRecord] = []

            for record in parsed_records:
                if record.is_valid:
                    valid_records.append(record)
                else:
                    for field, error in record.errors:
                        if len(validation_errors) < 100:  # Limit error reporting
                            validation_errors.append(
                                ImportValidationError(
                                    row=record.row_number,
                                    field=field if field != "_record" else None,
                                    error=error,
                                    value=record.data.get(field) if field != "_record" else None,
                                )
                            )

            # If validation only, return here
            if validate_only:
                return ImportResult(
                    status=ImportStatus.COMPLETED if not validation_errors else ImportStatus.FAILED,
                    import_id=import_id,
                    entity_type=entity_type,
                    format=format,
                    total_rows=total_rows,
                    processed_rows=total_rows,
                    successful_rows=len(valid_records),
                    failed_rows=len(parsed_records) - len(valid_records),
                    validation_errors=validation_errors,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )

            # If we have errors and not skipping, fail
            if validation_errors and not skip_errors:
                return ImportResult(
                    status=ImportStatus.FAILED,
                    import_id=import_id,
                    entity_type=entity_type,
                    format=format,
                    total_rows=total_rows,
                    processed_rows=0,
                    failed_rows=len(parsed_records) - len(valid_records),
                    validation_errors=validation_errors,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    error_message="Validation failed. Fix errors or use skip_errors=true.",
                )

            # Import valid records
            model_class = self._import_model(config["model_path"])
            successful = 0
            skipped = 0
            failed = 0

            for record in valid_records:
                try:
                    # Check for existing record if update_existing is enabled
                    existing = None
                    if update_existing and "id" in record.data:
                        existing = await self.session.get(model_class, record.data["id"])

                    if existing:
                        # Update existing
                        for key, value in record.data.items():
                            if key != "id" and hasattr(existing, key):
                                setattr(existing, key, value)
                        successful += 1
                    elif "id" in record.data:
                        # Skip if exists and not updating
                        existing = await self.session.get(model_class, record.data["id"])
                        if existing:
                            skipped += 1
                            continue

                    if not existing:
                        # Create new record
                        # Remove id if present to let DB generate it
                        create_data = {k: v for k, v in record.data.items() if k != "id"}
                        new_record = model_class(**create_data)
                        self.session.add(new_record)
                        successful += 1

                except Exception as e:
                    failed += 1
                    if len(validation_errors) < 100:
                        validation_errors.append(
                            ImportValidationError(
                                row=record.row_number,
                                field=None,
                                error=f"Database error: {e}",
                            )
                        )
                    if not skip_errors:
                        await self.session.rollback()
                        return ImportResult(
                            status=ImportStatus.FAILED,
                            import_id=import_id,
                            entity_type=entity_type,
                            format=format,
                            total_rows=total_rows,
                            processed_rows=successful + failed + skipped,
                            successful_rows=successful,
                            failed_rows=failed + len(parsed_records) - len(valid_records),
                            skipped_rows=skipped,
                            validation_errors=validation_errors,
                            started_at=started_at,
                            completed_at=datetime.now(UTC),
                            error_message=str(e),
                        )

            # Commit all changes
            await self.session.commit()

            # Determine final status
            total_failed = failed + len(parsed_records) - len(valid_records)
            if total_failed > 0 and successful > 0:
                status = ImportStatus.PARTIALLY_COMPLETED
            elif total_failed > 0:
                status = ImportStatus.FAILED
            else:
                status = ImportStatus.COMPLETED

            return ImportResult(
                status=status,
                import_id=import_id,
                entity_type=entity_type,
                format=format,
                total_rows=total_rows,
                processed_rows=successful + failed + skipped,
                successful_rows=successful,
                failed_rows=total_failed,
                skipped_rows=skipped,
                validation_errors=validation_errors,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.exception(f"Import failed for {entity_type}")
            return ImportResult(
                status=ImportStatus.FAILED,
                import_id=import_id,
                entity_type=entity_type,
                format=format,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error_message=str(e),
            )

    async def _upload_to_storage(self, file_path: Path, entity_type: str) -> str | None:
        """Upload export file to object storage.

        Args:
            file_path: Path to file to upload.
            entity_type: Entity type for storage path.

        Returns:
            Storage URI if successful, None otherwise.
        """
        try:
            from example_service.core.settings import get_backup_settings
            from example_service.infra.storage.s3 import S3Client

            backup_settings = get_backup_settings()
            if not backup_settings.is_s3_configured:
                logger.debug("S3 not configured, skipping upload")
                return None

            s3_client = S3Client(backup_settings)
            s3_key = f"exports/{entity_type}/{file_path.name}"
            return await s3_client.upload_file(file_path, s3_key)

        except Exception as e:
            logger.warning(f"Failed to upload to storage: {e}")
            return None


async def get_data_transfer_service(session: AsyncSession) -> DataTransferService:
    """Get a data transfer service instance.

    Args:
        session: Database session.

    Returns:
        DataTransferService instance.
    """
    return DataTransferService(session)
