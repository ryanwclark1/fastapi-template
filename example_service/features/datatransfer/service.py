"""Data transfer service for export and import operations.

Provides high-level interface for exporting and importing data
with progress tracking, validation, and storage integration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import gzip
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
import uuid

from sqlalchemy import func, select

from example_service.core.settings import get_datatransfer_settings

from .exporters import get_exporter
from .importers import ParsedRecord, get_importer
from .schemas import (
    ExportRequest,
    ExportResult,
    ExportStatus,
    FilterCondition,
    FilterOperator,
    ImportFormat,
    ImportResult,
    ImportStatus,
    ImportValidationError,
    SupportedEntity,
)
from .validators import get_validator_registry, validate_entity

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

# Default export directory that can be overridden in tests
EXPORT_DIR: Path | None = None


def ensure_export_dir() -> Path:
    """Ensure the export directory exists and return it.

    This helper mirrors the legacy module-level function that tests expect
    while delegating to settings by default.
    """
    global EXPORT_DIR

    if EXPORT_DIR is None:
        EXPORT_DIR = get_datatransfer_settings().export_path

    export_path = Path(EXPORT_DIR)
    export_path.mkdir(parents=True, exist_ok=True)
    return export_path


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

    def _compress_data(self, data: bytes) -> bytes:
        """Compress data using gzip.

        Args:
            data: Data to compress.

        Returns:
            Compressed data.
        """
        settings = get_datatransfer_settings()
        return gzip.compress(data, compresslevel=settings.compression_level)

    def _apply_filter_condition(
        self,
        stmt: Any,
        model_class: type[Any],
        condition: FilterCondition,
    ) -> Any:
        """Apply a single filter condition to a query statement.

        Args:
            stmt: SQLAlchemy select statement.
            model_class: Model class to filter on.
            condition: Filter condition to apply.

        Returns:
            Updated statement with the filter applied.
        """
        if not hasattr(model_class, condition.field):
            logger.warning(
                "Ignoring filter on unknown field: %s", condition.field
            )
            return stmt

        column = getattr(model_class, condition.field)
        op = condition.operator
        value = condition.value

        if op == FilterOperator.EQ:
            stmt = stmt.where(column == value)
        elif op == FilterOperator.NE:
            stmt = stmt.where(column != value)
        elif op == FilterOperator.GT:
            stmt = stmt.where(column > value)
        elif op == FilterOperator.GTE:
            stmt = stmt.where(column >= value)
        elif op == FilterOperator.LT:
            stmt = stmt.where(column < value)
        elif op == FilterOperator.LTE:
            stmt = stmt.where(column <= value)
        elif op == FilterOperator.CONTAINS:
            # Case-insensitive contains
            stmt = stmt.where(column.ilike(f"%{value}%"))
        elif op == FilterOperator.IN:
            if isinstance(value, list):
                stmt = stmt.where(column.in_(value))
            else:
                logger.warning("IN operator requires a list value, got: %s", type(value))
        elif op == FilterOperator.NOT_IN:
            if isinstance(value, list):
                stmt = stmt.where(column.notin_(value))
            else:
                logger.warning("NOT_IN operator requires a list value, got: %s", type(value))
        elif op == FilterOperator.IS_NULL:
            stmt = stmt.where(column.is_(None))
        elif op == FilterOperator.IS_NOT_NULL:
            stmt = stmt.where(column.isnot(None))

        return stmt

    async def _fetch_export_records(
        self,
        entity_type: str,
        filters: dict[str, Any] | None = None,
        filter_conditions: list[FilterCondition] | None = None,
        tenant_id: str | None = None,
    ) -> tuple[list[Any], dict[str, Any]]:
        """Fetch records for export.

        Shared helper for export and export_to_bytes to avoid code duplication.

        Args:
            entity_type: Type of entity to export.
            filters: Optional simple equality filters (legacy, deprecated).
            filter_conditions: Optional advanced filter conditions.
            tenant_id: Optional tenant ID for filtering in multi-tenant scenarios.

        Returns:
            Tuple of (records list, entity config dict).

        Raises:
            ValueError: If entity type is not exportable.
        """
        # Get entity configuration
        config = self._get_entity_config(entity_type)
        if not config.get("exportable", True):
            raise ValueError(f"Entity '{entity_type}' is not exportable")

        # Import the model
        model_class = self._import_model(config["model_path"])

        # Build query
        stmt = select(model_class)

        # Apply tenant filter if tenant isolation is enabled and tenant_id is provided
        settings = get_datatransfer_settings()
        if settings.enable_tenant_isolation and tenant_id:
            if hasattr(model_class, "tenant_id"):
                stmt = stmt.where(model_class.tenant_id == tenant_id)
                logger.debug(
                    "Applied tenant filter for export",
                    extra={"entity_type": entity_type, "tenant_id": tenant_id},
                )
            else:
                logger.warning(
                    "Tenant isolation enabled but model has no tenant_id field",
                    extra={"entity_type": entity_type, "model": model_class.__name__},
                )

        # Apply legacy simple filters if provided (deprecated)
        if filters:
            for field, value in filters.items():
                if hasattr(model_class, field):
                    stmt = stmt.where(getattr(model_class, field) == value)

        # Apply advanced filter conditions
        if filter_conditions:
            for condition in filter_conditions:
                stmt = self._apply_filter_condition(stmt, model_class, condition)

        # Execute query
        result = await self.session.execute(stmt)
        records = result.scalars().all()

        return list(records), config

    async def export(
        self,
        request: ExportRequest,
        tenant_id: str | None = None,
    ) -> ExportResult:
        """Export data to a file.

        Args:
            request: Export request with entity type, format, and filters.
            tenant_id: Optional tenant ID for multi-tenant filtering.

        Returns:
            Export result with file path and statistics.
        """
        export_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)

        try:
            # Fetch records using shared helper
            records, config = await self._fetch_export_records(
                request.entity_type,
                request.filters,
                request.filter_conditions,
                tenant_id,
            )

            # Get exporter
            exporter = get_exporter(
                format=request.format.value,
                fields=request.fields or config.get("fields"),
                include_headers=request.include_headers,
            )

            # Generate filename using settings
            settings = get_datatransfer_settings()
            export_dir = settings.ensure_export_dir()
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"{request.entity_type}_{timestamp}.{exporter.file_extension}"
            file_path = export_dir / filename

            # Export to file
            record_count = exporter.export(list(records), file_path)
            file_size = file_path.stat().st_size

            # Upload to storage if requested
            storage_uri = None
            if request.upload_to_storage:
                storage_uri = await self._upload_to_storage(
                    file_path, request.entity_type
                )

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
            logger.exception("Export failed for %s", request.entity_type)
            return ExportResult(
                status=ExportStatus.FAILED,
                export_id=export_id,
                entity_type=request.entity_type,
                format=request.format,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error_message=str(e),
            )

    async def export_to_bytes(
        self,
        request: ExportRequest,
        tenant_id: str | None = None,
        compress: bool | None = None,
    ) -> tuple[bytes, str, str]:
        """Export data to bytes for streaming download.

        Args:
            request: Export request.
            tenant_id: Optional tenant ID for multi-tenant filtering.
            compress: Override compression setting (None = use settings default).

        Returns:
            Tuple of (data bytes, content_type, filename).
        """
        settings = get_datatransfer_settings()

        # Fetch records using shared helper
        records, config = await self._fetch_export_records(
            request.entity_type,
            request.filters,
            request.filter_conditions,
            tenant_id,
        )

        # Get exporter and export
        exporter = get_exporter(
            format=request.format.value,
            fields=request.fields or config.get("fields"),
            include_headers=request.include_headers,
        )

        data = exporter.export_to_bytes(records)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{request.entity_type}_{timestamp}.{exporter.file_extension}"

        # Apply compression if enabled
        should_compress = compress if compress is not None else settings.enable_compression
        if should_compress:
            data = self._compress_data(data)
            filename = f"{filename}.gz"
            content_type = "application/gzip"
            logger.debug(
                "Compressed export data",
                extra={
                    "entity_type": request.entity_type,
                    "original_size": len(data),
                    "compressed_size": len(data),
                },
            )
            return data, content_type, filename

        return data, exporter.content_type, filename

    async def get_export_count(
        self,
        entity_type: str,
        filters: dict[str, Any] | None = None,
        filter_conditions: list[FilterCondition] | None = None,
        tenant_id: str | None = None,
    ) -> int:
        """Get count of records to export.

        Args:
            entity_type: Type of entity.
            filters: Optional simple filters.
            filter_conditions: Optional advanced filter conditions.
            tenant_id: Optional tenant ID.

        Returns:
            Number of records matching the criteria.
        """
        config = self._get_entity_config(entity_type)
        model_class = self._import_model(config["model_path"])

        stmt = select(func.count()).select_from(model_class)

        # Apply tenant filter
        settings = get_datatransfer_settings()
        if settings.enable_tenant_isolation and tenant_id:
            if hasattr(model_class, "tenant_id"):
                stmt = stmt.where(model_class.tenant_id == tenant_id)

        # Apply filters
        if filters:
            for field, value in filters.items():
                if hasattr(model_class, field):
                    stmt = stmt.where(getattr(model_class, field) == value)

        if filter_conditions:
            for condition in filter_conditions:
                stmt = self._apply_filter_condition(stmt, model_class, condition)

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def stream_export(
        self,
        request: ExportRequest,
        tenant_id: str | None = None,
        chunk_size: int = 1000,
    ) -> AsyncIterator[bytes]:
        """Stream export data in chunks for large datasets.

        Uses server-side cursors and pagination to efficiently handle
        large datasets without loading everything into memory.

        Args:
            request: Export request.
            tenant_id: Optional tenant ID.
            chunk_size: Number of records per chunk.

        Yields:
            Bytes chunks of exported data.
        """
        config = self._get_entity_config(entity_type=request.entity_type)
        if not config.get("exportable", True):
            raise ValueError(f"Entity '{request.entity_type}' is not exportable")

        model_class = self._import_model(config["model_path"])

        # Build base query
        stmt = select(model_class)

        # Apply tenant filter
        settings = get_datatransfer_settings()
        if settings.enable_tenant_isolation and tenant_id:
            if hasattr(model_class, "tenant_id"):
                stmt = stmt.where(model_class.tenant_id == tenant_id)

        # Apply filters
        if request.filters:
            for field, value in request.filters.items():
                if hasattr(model_class, field):
                    stmt = stmt.where(getattr(model_class, field) == value)

        if request.filter_conditions:
            for condition in request.filter_conditions:
                stmt = self._apply_filter_condition(stmt, model_class, condition)

        # Order by primary key for consistent pagination
        if hasattr(model_class, "id"):
            stmt = stmt.order_by(model_class.id)

        # Get exporter
        exporter = get_exporter(
            format=request.format.value,
            fields=request.fields or config.get("fields"),
            include_headers=request.include_headers,
        )

        # Stream in chunks with offset-based pagination
        offset = 0
        first_chunk = True

        while True:
            # Execute paginated query
            paginated_stmt = stmt.offset(offset).limit(chunk_size)
            result = await self.session.execute(paginated_stmt)
            records = list(result.scalars().all())

            if not records:
                break

            # For CSV/JSON, we need to handle headers specially
            if request.format.value == "csv":
                if first_chunk:
                    # Include headers in first chunk
                    chunk_data = exporter.export_to_bytes(records)
                else:
                    # Skip headers for subsequent chunks
                    temp_exporter = get_exporter(
                        format=request.format.value,
                        fields=request.fields or config.get("fields"),
                        include_headers=False,
                    )
                    chunk_data = temp_exporter.export_to_bytes(records)
            elif request.format.value == "json":
                # For JSON, yield each record as a JSON line (JSONL format for streaming)
                import json
                lines = []
                for record in records:
                    record_dict = {
                        field: getattr(record, field, None)
                        for field in (request.fields or config.get("fields", []))
                    }
                    # Handle datetime serialization
                    for key, value in record_dict.items():
                        if isinstance(value, datetime):
                            record_dict[key] = value.isoformat()
                    lines.append(json.dumps(record_dict))
                chunk_data = ("\n".join(lines) + "\n").encode("utf-8")
            else:
                # For Excel and other formats, export the chunk directly
                chunk_data = exporter.export_to_bytes(records)

            yield chunk_data
            first_chunk = False
            offset += chunk_size

            # Check if we got fewer records than requested (last chunk)
            if len(records) < chunk_size:
                break

        logger.info(
            "Streaming export completed",
            extra={
                "entity_type": request.entity_type,
                "total_chunks": (offset // chunk_size) + 1,
                "total_records": offset + len(records) if records else offset,
            },
        )

    async def import_from_bytes(
        self,
        data: bytes,
        entity_type: str,
        format: ImportFormat,
        validate_only: bool = False,
        skip_errors: bool = False,
        update_existing: bool = False,
        batch_size: int = 100,
    ) -> ImportResult:
        """Import data from bytes.

        Args:
            data: Raw file data.
            entity_type: Type of entity to import.
            format: Import file format.
            validate_only: Only validate, don't import.
            skip_errors: Continue importing even if some records fail.
            update_existing: Update existing records instead of skipping.
            batch_size: Number of records to process per batch (1-1000).

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
            settings = get_datatransfer_settings()
            max_errors = settings.max_validation_errors

            # Check if entity-specific validator exists
            validator_registry = get_validator_registry()
            has_entity_validator = validator_registry.has_validator(entity_type)

            for record in parsed_records:
                if not record.is_valid:
                    # Basic type validation failed
                    for field, error in record.errors:
                        if len(validation_errors) < max_errors:
                            validation_errors.append(
                                ImportValidationError(
                                    row=record.row_number,
                                    field=field if field != "_record" else None,
                                    error=error,
                                    value=record.data.get(field)
                                    if field != "_record"
                                    else None,
                                )
                            )
                    continue

                # Run entity-specific validation if available
                if has_entity_validator:
                    entity_result = validate_entity(entity_type, record.data)
                    if not entity_result.is_valid:
                        for err in entity_result.errors:
                            if len(validation_errors) < max_errors:
                                validation_errors.append(
                                    ImportValidationError(
                                        row=record.row_number,
                                        field=err.field,
                                        error=err.message,
                                        value=err.value,
                                    )
                                )
                        continue

                    # Use transformed data if available
                    if entity_result.transformed_data:
                        record.data = entity_result.transformed_data

                valid_records.append(record)

            # If validation only, return here
            if validate_only:
                return ImportResult(
                    status=ImportStatus.COMPLETED
                    if not validation_errors
                    else ImportStatus.FAILED,
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

            # Import valid records in batches
            model_class = self._import_model(config["model_path"])
            successful = 0
            skipped = 0
            failed = 0

            # Ensure batch_size is within valid range
            batch_size = max(1, min(batch_size, 1000))

            # Process records in batches
            for batch_start in range(0, len(valid_records), batch_size):
                batch_end = min(batch_start + batch_size, len(valid_records))
                batch = valid_records[batch_start:batch_end]

                for record in batch:
                    try:
                        # Check for existing record if update_existing is enabled
                        existing = None
                        if update_existing and "id" in record.data:
                            existing = await self.session.get(
                                model_class, record.data["id"]
                            )

                        if existing:
                            # Update existing
                            for key, value in record.data.items():
                                if key != "id" and hasattr(existing, key):
                                    setattr(existing, key, value)
                            successful += 1
                        elif "id" in record.data:
                            # Skip if exists and not updating
                            existing = await self.session.get(
                                model_class, record.data["id"]
                            )
                            if existing:
                                skipped += 1
                                continue

                        if not existing:
                            # Create new record
                            # Remove id if present to let DB generate it
                            create_data = {
                                k: v for k, v in record.data.items() if k != "id"
                            }
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
                                failed_rows=failed
                                + len(parsed_records)
                                - len(valid_records),
                                skipped_rows=skipped,
                                validation_errors=validation_errors,
                                started_at=started_at,
                                completed_at=datetime.now(UTC),
                                error_message=str(e),
                            )

                # Flush the batch to the database
                await self.session.flush()
                logger.debug(
                    "Processed batch %d-%d of %d records",
                    batch_start + 1,
                    batch_end,
                    len(valid_records),
                )

            # Commit all changes after all batches
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
            logger.exception("Import failed for %s", entity_type)
            return ImportResult(
                status=ImportStatus.FAILED,
                import_id=import_id,
                entity_type=entity_type,
                format=format,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error_message=str(e),
            )

    def generate_import_template(
        self,
        entity_type: str,
        format: ImportFormat,
    ) -> tuple[bytes, str, str]:
        """Generate a sample import template for an entity type.

        Creates a template file with column headers and sample data
        showing the expected format for importing.

        Args:
            entity_type: Type of entity to generate template for.
            format: Output format (csv, json, xlsx).

        Returns:
            Tuple of (data bytes, content_type, filename).

        Raises:
            ValueError: If entity type is not importable.
        """
        # Get entity configuration
        config = self._get_entity_config(entity_type)
        if not config.get("importable", True):
            raise ValueError(f"Entity '{entity_type}' is not importable")

        fields = config.get("fields", [])
        required_fields = config.get("required_fields", [])

        # Filter out auto-generated fields that shouldn't be in import template
        template_fields = [
            f for f in fields
            if f not in ("id", "created_at", "updated_at")
        ]

        # Generate sample data row
        sample_data = {}
        for field in template_fields:
            if field in required_fields:
                sample_data[field] = f"<required: {field}>"
            else:
                sample_data[field] = f"<optional: {field}>"

        # Get exporter for the format
        exporter = get_exporter(
            format=format.value,
            fields=template_fields,
            include_headers=True,
        )

        # Create a fake record class to export
        class TemplateRecord:
            def __init__(self, data: dict) -> None:
                for key, value in data.items():
                    setattr(self, key, value)

        template_record = TemplateRecord(sample_data)
        data = exporter.export_to_bytes([template_record])

        filename = f"{entity_type}_template.{exporter.file_extension}"
        return data, exporter.content_type, filename

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
            logger.warning("Failed to upload to storage: %s", e)
            return None


async def get_data_transfer_service(session: AsyncSession) -> DataTransferService:
    """Get a data transfer service instance.

    Args:
        session: Database session.

    Returns:
        DataTransferService instance.
    """
    return DataTransferService(session)
