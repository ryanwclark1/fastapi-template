"""Data transfer feature for export and import operations.

Provides comprehensive data import/export capabilities:
- CSV, JSON, and Excel format support
- Validation with detailed error reporting
- Streaming exports for large datasets
- Progress tracking for long operations
- Storage integration for exports

Usage:
    from example_service.features.datatransfer import (
        DataTransferService,
        ExportRequest,
        ExportFormat,
        ImportFormat,
    )

    # Export data
    service = DataTransferService(session)
    result = await service.export(ExportRequest(
        entity_type="reminders",
        format=ExportFormat.CSV,
    ))

    # Import data
    result = await service.import_from_bytes(
        data=file_content,
        entity_type="reminders",
        format=ImportFormat.CSV,
    )
"""

from __future__ import annotations

from .audit import (
    DataTransferAuditLogger,
    get_audit_logger,
    log_export_operation,
    log_import_operation,
)
from .cleanup import cleanup_old_exports, cleanup_old_exports_async, get_export_stats
from .exporters import (
    BaseExporter,
    CSVExporter,
    ExcelExporter,
    JSONExporter,
    get_exporter,
)
from .importers import (
    BaseImporter,
    CSVImporter,
    DataImportError,
    ExcelImporter,
    JSONImporter,
    ParsedRecord,
    get_importer,
)
from .jobs import (
    JobProgress,
    JobStatus,
    JobTracker,
    JobType,
    get_job_tracker,
    run_export_job,
    run_import_job,
)
from .router import router
from .schemas import (
    ExportFormat,
    ExportRequest,
    ExportResult,
    ExportStatus,
    FilterCondition,
    FilterOperator,
    ImportFormat,
    ImportRequest,
    ImportResult,
    ImportStatus,
    ImportValidationError,
    SupportedEntitiesResponse,
    SupportedEntity,
)
from .service import DataTransferService, get_data_transfer_service
from .validators import (
    EntityValidator,
    ValidationError,
    ValidationResult,
    ValidatorRegistry,
    create_validator,
    get_validator_registry,
    register_validator,
    validate_entity,
)
from .webhooks import (
    DataTransferEvent,
    get_supported_events,
    notify_export_complete,
    notify_import_complete,
    notify_streaming_export_complete,
)

__all__ = [
    # Audit
    "DataTransferAuditLogger",
    "get_audit_logger",
    "log_export_operation",
    "log_import_operation",
    # Exporters
    "BaseExporter",
    # Importers
    "BaseImporter",
    "CSVExporter",
    "CSVImporter",
    # Cleanup
    "cleanup_old_exports",
    "cleanup_old_exports_async",
    # Errors
    "DataImportError",
    # Jobs
    "JobProgress",
    "JobStatus",
    "JobTracker",
    "JobType",
    "get_job_tracker",
    "run_export_job",
    "run_import_job",
    # Service
    "DataTransferService",
    "ExcelExporter",
    "ExcelImporter",
    # Schemas
    "ExportFormat",
    "ExportRequest",
    "ExportResult",
    "ExportStatus",
    "FilterCondition",
    "FilterOperator",
    "ImportFormat",
    "ImportRequest",
    "ImportResult",
    "ImportStatus",
    "ImportValidationError",
    "JSONExporter",
    "JSONImporter",
    "ParsedRecord",
    "SupportedEntitiesResponse",
    "SupportedEntity",
    "get_data_transfer_service",
    "get_export_stats",
    "get_exporter",
    "get_importer",
    # Validators
    "EntityValidator",
    "ValidationError",
    "ValidationResult",
    "ValidatorRegistry",
    "create_validator",
    "get_validator_registry",
    "register_validator",
    "validate_entity",
    # Webhooks
    "DataTransferEvent",
    "get_supported_events",
    "notify_export_complete",
    "notify_import_complete",
    "notify_streaming_export_complete",
    # Router
    "router",
]
