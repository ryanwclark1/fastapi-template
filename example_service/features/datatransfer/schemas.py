"""Data transfer schemas for export and import operations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExportFormat(StrEnum):
    """Supported export formats."""

    CSV = "csv"
    JSON = "json"
    EXCEL = "xlsx"


class ImportFormat(StrEnum):
    """Supported import formats."""

    CSV = "csv"
    JSON = "json"
    EXCEL = "xlsx"


class ExportStatus(StrEnum):
    """Export job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportStatus(StrEnum):
    """Import job status."""

    PENDING = "pending"
    VALIDATING = "validating"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"


class ExportRequest(BaseModel):
    """Request to export data."""

    entity_type: str = Field(description="Type of entity to export (e.g., 'reminders', 'files')")
    format: ExportFormat = Field(default=ExportFormat.CSV, description="Export format")
    filters: dict[str, Any] | None = Field(default=None, description="Query filters to apply")
    fields: list[str] | None = Field(
        default=None, description="Specific fields to export (all if not specified)"
    )
    include_headers: bool = Field(default=True, description="Include column headers (CSV/Excel)")
    upload_to_storage: bool = Field(default=False, description="Upload to object storage after export")

    model_config = {"json_schema_extra": {"example": {"entity_type": "reminders", "format": "csv"}}}


class ExportResult(BaseModel):
    """Result of an export operation."""

    status: ExportStatus
    export_id: str = Field(description="Unique export ID")
    entity_type: str
    format: ExportFormat
    file_path: str | None = Field(default=None, description="Local file path")
    file_name: str | None = Field(default=None, description="Export file name")
    record_count: int = Field(default=0, description="Number of records exported")
    size_bytes: int = Field(default=0, description="File size in bytes")
    storage_uri: str | None = Field(default=None, description="Object storage URI if uploaded")
    download_url: str | None = Field(default=None, description="Download URL")
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class ImportRequest(BaseModel):
    """Request to import data."""

    entity_type: str = Field(description="Type of entity to import")
    format: ImportFormat = Field(description="Import file format")
    validate_only: bool = Field(
        default=False, description="Only validate, don't actually import"
    )
    skip_errors: bool = Field(
        default=False, description="Continue importing even if some records fail"
    )
    update_existing: bool = Field(
        default=False, description="Update existing records instead of skipping"
    )
    batch_size: int = Field(default=100, ge=1, le=1000, description="Records to process per batch")


class ImportValidationError(BaseModel):
    """Validation error for a specific record."""

    row: int = Field(description="Row number (1-indexed)")
    field: str | None = Field(default=None, description="Field with error")
    error: str = Field(description="Error message")
    value: Any | None = Field(default=None, description="Problematic value")


class ImportResult(BaseModel):
    """Result of an import operation."""

    status: ImportStatus
    import_id: str = Field(description="Unique import ID")
    entity_type: str
    format: ImportFormat
    total_rows: int = Field(default=0, description="Total rows in file")
    processed_rows: int = Field(default=0, description="Rows processed")
    successful_rows: int = Field(default=0, description="Rows successfully imported")
    failed_rows: int = Field(default=0, description="Rows that failed")
    skipped_rows: int = Field(default=0, description="Rows skipped (duplicates, etc.)")
    validation_errors: list[ImportValidationError] = Field(
        default_factory=list, description="Validation errors (limited to first 100)"
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class ExportListResponse(BaseModel):
    """List of available exports."""

    exports: list[ExportResult]
    total: int


class SupportedEntity(BaseModel):
    """Information about a supported entity for export/import."""

    name: str = Field(description="Entity name (e.g., 'reminders')")
    display_name: str = Field(description="Human-readable name")
    exportable: bool = Field(default=True, description="Whether entity can be exported")
    importable: bool = Field(default=True, description="Whether entity can be imported")
    fields: list[str] = Field(default_factory=list, description="Available fields")
    required_fields: list[str] = Field(
        default_factory=list, description="Required fields for import"
    )


class SupportedEntitiesResponse(BaseModel):
    """List of entities supported for data transfer."""

    entities: list[SupportedEntity]
