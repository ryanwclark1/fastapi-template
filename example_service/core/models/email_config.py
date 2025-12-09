"""Email configuration models - DEPRECATED LOCATION.

These models have been moved to the email feature module for better organization.
This file re-exports from the new location for backwards compatibility.

New location: example_service.features.email.models
"""

from example_service.features.email.models import (
    EmailAuditLog,
    EmailConfig,
    EmailProviderType,
    EmailUsageLog,
)

__all__ = [
    "EmailAuditLog",
    "EmailConfig",
    "EmailProviderType",
    "EmailUsageLog",
]
