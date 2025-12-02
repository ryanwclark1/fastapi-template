"""Pydantic schemas for storage management API."""

from datetime import datetime

from pydantic import BaseModel, Field

# ============================================================================
# Bucket Schemas
# ============================================================================


class BucketCreate(BaseModel):
    """Request schema for creating a bucket."""

    name: str = Field(
        ...,
        min_length=3,
        max_length=63,
        description="Bucket name (DNS-compliant)",
        examples=["my-bucket", "acme-uploads"],
    )
    region: str | None = Field(
        None,
        description="Geographic region (uses default if not specified)",
        examples=["us-west-2", "eu-central-1"],
    )
    acl: str | None = Field(
        None,
        description="Bucket-level ACL (private, public-read, etc.)",
        examples=["private", "public-read"],
    )
    tenant_uuid: str | None = Field(
        None,
        description="Associate bucket with tenant UUID for tracking",
    )


class BucketDelete(BaseModel):
    """Request schema for deleting a bucket."""

    force: bool = Field(
        False,
        description="Force delete even if bucket is not empty (use with caution!)",
    )


class BucketResponse(BaseModel):
    """Response schema for bucket information."""

    name: str = Field(..., description="Bucket name")
    region: str | None = Field(None, description="Bucket region")
    creation_date: datetime | None = Field(None, description="When bucket was created")
    versioning_enabled: bool = Field(False, description="Whether versioning is enabled")
    tenant_uuid: str | None = Field(None, description="Associated tenant UUID")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "acme-uploads",
                    "region": "us-west-2",
                    "creation_date": "2024-01-15T10:30:00Z",
                    "versioning_enabled": False,
                    "tenant_uuid": "tenant-abc-123",
                }
            ]
        }
    }


class BucketListResponse(BaseModel):
    """Response schema for listing buckets."""

    buckets: list[BucketResponse] = Field(..., description="List of buckets")
    total: int = Field(..., description="Total number of buckets")


# ============================================================================
# Object Schemas
# ============================================================================


class ObjectMetadataResponse(BaseModel):
    """Response schema for object metadata."""

    key: str = Field(..., description="Object key/path")
    size_bytes: int = Field(..., description="Object size in bytes")
    content_type: str | None = Field(None, description="MIME type")
    last_modified: datetime = Field(..., description="Last modification timestamp")
    etag: str | None = Field(None, description="Entity tag")
    storage_class: str | None = Field(None, description="Storage class")
    acl: str | None = Field(None, description="ACL setting")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "key": "documents/report.pdf",
                    "size_bytes": 1048576,
                    "content_type": "application/pdf",
                    "last_modified": "2024-01-15T10:30:00Z",
                    "etag": "abc123",
                    "storage_class": "STANDARD",
                    "acl": "private",
                }
            ]
        }
    }


class ObjectListResponse(BaseModel):
    """Response schema for listing objects."""

    objects: list[ObjectMetadataResponse] = Field(..., description="List of objects")
    total: int = Field(..., description="Total number of objects returned")
    has_more: bool = Field(..., description="Whether there are more results")
    continuation_token: str | None = Field(
        None,
        description="Token for fetching next page",
    )


class ObjectUploadRequest(BaseModel):
    """Request schema for object upload metadata."""

    content_type: str | None = Field(None, description="MIME type")
    metadata: dict[str, str] | None = Field(None, description="Custom metadata")
    acl: str | None = Field(None, description="ACL setting")
    storage_class: str | None = Field(None, description="Storage class")


class ObjectUploadResponse(BaseModel):
    """Response schema for object upload."""

    key: str = Field(..., description="Object key")
    bucket: str = Field(..., description="Bucket name")
    etag: str | None = Field(None, description="Entity tag")
    size_bytes: int = Field(..., description="Size in bytes")
    checksum_sha256: str | None = Field(None, description="SHA256 checksum")
    version_id: str | None = Field(None, description="Version ID if versioning enabled")


class ObjectDeleteResponse(BaseModel):
    """Response schema for object deletion."""

    deleted: bool = Field(..., description="Whether deletion was successful")
    key: str = Field(..., description="Deleted object key")


# ============================================================================
# ACL Schemas
# ============================================================================


class ACLSetRequest(BaseModel):
    """Request schema for setting ACL."""

    acl: str = Field(
        ...,
        description="Canned ACL to set",
        examples=["private", "public-read", "public-read-write", "authenticated-read"],
    )


class ACLResponse(BaseModel):
    """Response schema for ACL information."""

    owner: dict[str, str] = Field(..., description="Owner information")
    grants: list[dict[str, str]] = Field(..., description="Access grants")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "owner": {"ID": "owner-id", "DisplayName": "owner-name"},
                    "grants": [
                        {
                            "Grantee": {"Type": "CanonicalUser", "ID": "user-id"},
                            "Permission": "FULL_CONTROL",
                        }
                    ],
                }
            ]
        }
    }


# ============================================================================
# Common Response Schemas
# ============================================================================


class SuccessResponse(BaseModel):
    """Generic success response."""

    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Success message")


class ErrorDetail(BaseModel):
    """Error detail schema."""

    type: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: dict[str, str] | None = Field(None, description="Additional error details")
