"""Storage management API endpoints."""

from io import BytesIO
import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from example_service.infra.storage.exceptions import (
    StorageError,
    StorageFileNotFoundError,
    StorageNotConfiguredError,
)

from .dependencies import AdminUser, StorageServiceDep, TenantContextDep
from .schemas import (
    ACLResponse,
    ACLSetRequest,
    BucketCreate,
    BucketListResponse,
    BucketResponse,
    ObjectDeleteResponse,
    ObjectListResponse,
    ObjectMetadataResponse,
    ObjectUploadResponse,
    SuccessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])


# ============================================================================
# Bucket Management Endpoints
# ============================================================================


@router.post(
    "/buckets",
    response_model=BucketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a storage bucket",
    description="Create a new storage bucket with optional region and ACL settings. Admin only.",
)
async def create_bucket(
    request: BucketCreate,
    storage: StorageServiceDep,
    _user: AdminUser,
) -> BucketResponse:
    """Create a new storage bucket.

    Requires admin role.
    """
    try:
        await storage.create_bucket(
            bucket=request.name,
            region=request.region,
            acl=request.acl,
        )

        # Return bucket info
        return BucketResponse(
            name=request.name,
            region=request.region,
            creation_date=None,  # Will be populated on next list
            versioning_enabled=False,
            tenant_uuid=request.tenant_uuid,
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to create bucket: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.delete(
    "/buckets/{bucket_name}",
    response_model=SuccessResponse,
    summary="Delete a storage bucket",
    description="Delete a storage bucket. Use force=true to delete non-empty buckets. Admin only.",
)
async def delete_bucket(
    bucket_name: str,
    storage: StorageServiceDep,
    _user: AdminUser,
    force: Annotated[bool, Query(description="Force delete even if not empty")] = False,
) -> SuccessResponse:
    """Delete a storage bucket.

    Requires admin role.
    """
    try:
        await storage.delete_bucket(bucket=bucket_name, force=force)

        return SuccessResponse(
            success=True,
            message=f"Bucket '{bucket_name}' deleted successfully",
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to delete bucket: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.get(
    "/buckets",
    response_model=BucketListResponse,
    summary="List all buckets",
    description="List all accessible storage buckets. Admin only.",
)
async def list_buckets(
    storage: StorageServiceDep,
    _user: AdminUser,
) -> BucketListResponse:
    """List all accessible storage buckets.

    Requires admin role.
    """
    try:
        buckets = await storage.list_buckets()

        bucket_responses = [
            BucketResponse(
                name=b["name"],
                region=b.get("region"),
                creation_date=b.get("creation_date"),
                versioning_enabled=b.get("versioning_enabled", False),
                tenant_uuid=None,  # Could be enhanced to track tenant ownership
            )
            for b in buckets
        ]

        return BucketListResponse(
            buckets=bucket_responses,
            total=len(bucket_responses),
        )

    except StorageError as e:
        logger.error(f"Failed to list buckets: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.get(
    "/buckets/{bucket_name}",
    response_model=BucketResponse,
    summary="Get bucket information",
    description="Get information about a specific bucket. Admin only.",
)
async def get_bucket_info(
    bucket_name: str,
    storage: StorageServiceDep,
    _user: AdminUser,
) -> BucketResponse:
    """Get bucket information.

    Requires admin role.
    """
    try:
        exists = await storage.bucket_exists(bucket_name)

        if not exists:
            raise StorageFileNotFoundError(
                f"Bucket '{bucket_name}' not found",
                metadata={"bucket": bucket_name},
            )

        # Get all buckets and find the one we want
        # (More efficient would be a dedicated get_bucket_info method)
        buckets = await storage.list_buckets()
        bucket = next((b for b in buckets if b["name"] == bucket_name), None)

        if not bucket:
            raise StorageFileNotFoundError(
                f"Bucket '{bucket_name}' not found",
                metadata={"bucket": bucket_name},
            )

        return BucketResponse(
            name=bucket["name"],
            region=bucket.get("region"),
            creation_date=bucket.get("creation_date"),
            versioning_enabled=bucket.get("versioning_enabled", False),
            tenant_uuid=None,
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to get bucket info: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


# ============================================================================
# Object Management Endpoints
# ============================================================================


@router.get(
    "/objects",
    response_model=ObjectListResponse,
    summary="List objects in a bucket",
    description="List objects with optional prefix filtering and pagination. Admin only.",
)
async def list_objects(
    storage: StorageServiceDep,
    _user: AdminUser,
    _tenant: TenantContextDep,
    prefix: Annotated[str, Query(description="Filter by key prefix")] = "",
    bucket: Annotated[
        str | None, Query(description="Bucket name (uses default if not specified)")
    ] = None,
    max_keys: Annotated[int, Query(ge=1, le=10000, description="Maximum keys to return")] = 1000,
    continuation_token: Annotated[str | None, Query(description="Token for next page")] = None,
) -> ObjectListResponse:
    """List objects in a bucket.

    Supports pagination via continuation_token.
    Requires admin role.
    """
    try:
        # Get backend directly to use list_objects method
        backend = storage._backend
        if not backend:
            raise StorageNotConfiguredError("Storage backend not initialized")

        # Resolve bucket with tenant context
        resolved_bucket = storage._resolve_bucket(_tenant, bucket)

        objects, next_token = await backend.list_objects(
            prefix=prefix or "",
            bucket=resolved_bucket,
            max_keys=max_keys,
            continuation_token=continuation_token,
        )

        object_responses = [
            ObjectMetadataResponse(
                key=obj.key,
                size_bytes=obj.size_bytes,
                content_type=obj.content_type,
                last_modified=obj.last_modified,
                etag=obj.etag,
                storage_class=obj.storage_class,
                acl=obj.acl,
            )
            for obj in objects
        ]

        return ObjectListResponse(
            objects=object_responses,
            total=len(object_responses),
            has_more=next_token is not None,
            continuation_token=next_token,
        )

    except StorageError as e:
        logger.error(f"Failed to list objects: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.post(
    "/objects/{key:path}",
    response_model=ObjectUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an object",
    description="Upload an object to storage. Admin only.",
)
async def upload_object(
    key: str,
    storage: StorageServiceDep,
    _user: AdminUser,
    _tenant: TenantContextDep,
    file: Annotated[UploadFile, File(description="File to upload")],
    bucket: Annotated[
        str | None, Query(description="Bucket name (uses default if not specified)")
    ] = None,
    content_type: Annotated[str | None, Query(description="Content type override")] = None,
    acl: Annotated[str | None, Query(description="ACL setting")] = None,
    storage_class: Annotated[str | None, Query(description="Storage class")] = None,
) -> ObjectUploadResponse:
    """Upload an object to storage.

    Requires admin role.
    """
    try:
        # Use file's content type if not overridden
        final_content_type = content_type or file.content_type

        result = await storage.upload_file(
            file_obj=file.file,
            key=key,
            content_type=final_content_type,
            bucket=bucket,
            acl=acl,
            storage_class=storage_class,
            tenant_context=_tenant,
        )

        return ObjectUploadResponse(
            key=result["key"],
            bucket=result["bucket"],
            etag=result.get("etag"),
            size_bytes=result["size_bytes"],
            checksum_sha256=result.get("checksum_sha256"),
            version_id=result.get("version_id"),
        )

    except StorageError as e:
        logger.error(f"Failed to upload object: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


# ============================================================================
# ACL Management Endpoints (must be before /objects/{key:path} route)
# ============================================================================


@router.put(
    "/objects/{key:path}/acl",
    response_model=SuccessResponse,
    summary="Set object ACL",
    description="Set Access Control List on an object. Admin only.",
)
async def set_object_acl(
    key: str,
    request: ACLSetRequest,
    storage: StorageServiceDep,
    _user: AdminUser,
    _tenant: TenantContextDep,
    bucket: Annotated[
        str | None, Query(description="Bucket name (uses default if not specified)")
    ] = None,
) -> SuccessResponse:
    """Set ACL on an object.

    Requires admin role.
    """
    try:
        await storage.set_object_acl(
            key=key,
            acl=request.acl,
            bucket=bucket,
            tenant_context=_tenant,
        )

        return SuccessResponse(
            success=True,
            message=f"ACL set to '{request.acl}' for object '{key}'",
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to set object ACL: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.get(
    "/objects/{key:path}/acl",
    response_model=ACLResponse,
    summary="Get object ACL",
    description="Get Access Control List of an object. Admin only.",
)
async def get_object_acl(
    key: str,
    storage: StorageServiceDep,
    _user: AdminUser,
    _tenant: TenantContextDep,
    bucket: Annotated[
        str | None, Query(description="Bucket name (uses default if not specified)")
    ] = None,
) -> ACLResponse:
    """Get ACL of an object.

    Requires admin role.
    """
    try:
        acl_data = await storage.get_object_acl(
            key=key,
            bucket=bucket,
            tenant_context=_tenant,
        )

        return ACLResponse(
            owner=acl_data.get("owner", {}),
            grants=acl_data.get("grants", []),
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to get object ACL: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.get(
    "/objects/{key:path}",
    summary="Download an object",
    description="Download an object from storage. Admin only.",
)
async def download_object(
    key: str,
    storage: StorageServiceDep,
    _user: AdminUser,
    _tenant: TenantContextDep,
    bucket: Annotated[
        str | None, Query(description="Bucket name (uses default if not specified)")
    ] = None,
) -> StreamingResponse:
    """Download an object from storage.

    Requires admin role.
    """
    try:
        data = await storage.download_file(key=key, bucket=bucket)

        # Get file info for content type
        info = await storage.get_file_info(key=key, bucket=bucket)
        content_type = (
            info.get("content_type", "application/octet-stream")
            if info
            else "application/octet-stream"
        )

        # Ensure data is bytes
        if not isinstance(data, bytes):
            data = bytes(data) if hasattr(data, "__bytes__") else str(data).encode("utf-8")

        return StreamingResponse(
            BytesIO(data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{key.split("/")[-1]}"',
            },
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to download object: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e


@router.delete(
    "/objects/{key:path}",
    response_model=ObjectDeleteResponse,
    summary="Delete an object",
    description="Delete an object from storage. Admin only.",
)
async def delete_object(
    key: str,
    storage: StorageServiceDep,
    _user: AdminUser,
    _tenant: TenantContextDep,
    bucket: Annotated[
        str | None, Query(description="Bucket name (uses default if not specified)")
    ] = None,
) -> ObjectDeleteResponse:
    """Delete an object from storage.

    Requires admin role.
    """
    try:
        deleted = await storage.delete_file(key=key, bucket=bucket)

        return ObjectDeleteResponse(
            deleted=deleted,
            key=key,
        )

    except StorageFileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error(f"Failed to delete object: {e}")
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
        ) from e
