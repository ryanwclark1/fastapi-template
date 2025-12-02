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
    ExcelImporter,
    JSONImporter,
    ParsedRecord,
    get_importer,
)
from .router import router
from .schemas import (
    ExportFormat,
    ExportRequest,
    ExportResult,
    ExportStatus,
    ImportFormat,
    ImportRequest,
    ImportResult,
    ImportStatus,
    ImportValidationError,
    SupportedEntitiesResponse,
    SupportedEntity,
)
from .service import DataTransferService, get_data_transfer_service

__all__ = [
    # Service
    "DataTransferService",
    "get_data_transfer_service",
    # Exporters
    "BaseExporter",
    "CSVExporter",
    "JSONExporter",
    "ExcelExporter",
    "get_exporter",
    # Importers
    "BaseImporter",
    "CSVImporter",
    "JSONImporter",
    "ExcelImporter",
    "ParsedRecord",
    "get_importer",
    # Schemas
    "ExportFormat",
    "ExportRequest",
    "ExportResult",
    "ExportStatus",
    "ImportFormat",
    "ImportRequest",
    "ImportResult",
    "ImportStatus",
    "ImportValidationError",
    "SupportedEntity",
    "SupportedEntitiesResponse",
    # Router
    "router",
]
