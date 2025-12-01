"""S3-compatible object storage client.

Provides async operations for uploading, downloading, and managing files
in S3-compatible storage (AWS S3, MinIO, LocalStack, etc.).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from example_service.core.settings.backup import BackupSettings

logger = logging.getLogger(__name__)

# Optional aioboto3 dependency
try:
    import aioboto3
    from botocore.exceptions import ClientError

    AIOBOTO3_AVAILABLE = True
except ImportError:
    aioboto3 = None
    ClientError = Exception
    AIOBOTO3_AVAILABLE = False


class S3ClientError(Exception):
    """S3 client operation error."""

    pass


class S3Client:
    """Async S3-compatible storage client.

    Supports AWS S3, MinIO, LocalStack, and other S3-compatible services.

    Example:
            from example_service.core.settings import get_backup_settings

        settings = get_backup_settings()
        client = S3Client(settings)

        # Upload a file
        s3_uri = await client.upload_file(
            local_path=Path("/tmp/backup.sql.gz"),
            s3_key="backups/backup_20240101.sql.gz"
        )

        # List backups
        backups = await client.list_objects(prefix="backups/")

        # Delete old backups
        deleted = await client.delete_old_objects(prefix="backups/", retention_days=30)
    """

    def __init__(self, settings: BackupSettings) -> None:
        """Initialize S3 client with settings.

        Args:
            settings: Backup settings containing S3 configuration.

        Raises:
            S3ClientError: If aioboto3 is not installed or S3 is not configured.
        """
        if not AIOBOTO3_AVAILABLE:
            raise S3ClientError(
                "aioboto3 is required for S3 support. Install with: pip install aioboto3"
            )

        if not settings.is_s3_configured:
            raise S3ClientError(
                "S3 is not configured. Set BACKUP_S3_BUCKET, "
                "BACKUP_S3_ACCESS_KEY, and BACKUP_S3_SECRET_KEY."
            )

        self.settings = settings
        self._session = aioboto3.Session()

    def _get_client_config(self) -> dict:
        """Get boto3 client configuration."""
        config = {
            "aws_access_key_id": self.settings.s3_access_key.get_secret_value(),
            "aws_secret_access_key": self.settings.s3_secret_key.get_secret_value(),
            "region_name": self.settings.s3_region,
        }

        if self.settings.s3_endpoint_url:
            config["endpoint_url"] = self.settings.s3_endpoint_url

        return config

    async def upload_file(
        self,
        local_path: Path,
        s3_key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload a file to S3.

        Args:
            local_path: Path to local file.
            s3_key: S3 object key (path in bucket).
            content_type: Optional content type (auto-detected if not provided).
            metadata: Optional metadata to attach to the object.

        Returns:
            S3 URI (s3://bucket/key).

        Raises:
            S3ClientError: If upload fails.
        """
        if not local_path.exists():
            raise S3ClientError(f"Local file not found: {local_path}")

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        elif local_path.suffix == ".gz":
            extra_args["ContentType"] = "application/gzip"
        elif local_path.suffix == ".sql":
            extra_args["ContentType"] = "application/sql"

        if metadata:
            extra_args["Metadata"] = metadata

        try:
            async with self._session.client("s3", **self._get_client_config()) as s3:
                await s3.upload_file(
                    str(local_path),
                    self.settings.s3_bucket,
                    s3_key,
                    ExtraArgs=extra_args if extra_args else None,
                )

            s3_uri = f"s3://{self.settings.s3_bucket}/{s3_key}"
            logger.info(
                "File uploaded to S3",
                extra={
                    "local_path": str(local_path),
                    "s3_uri": s3_uri,
                    "size_bytes": local_path.stat().st_size,
                },
            )
            return s3_uri

        except ClientError as e:
            logger.exception("Failed to upload file to S3", extra={"error": str(e)})
            raise S3ClientError(f"Failed to upload {local_path} to S3: {e}") from e

    async def download_file(self, s3_key: str, local_path: Path) -> Path:
        """Download a file from S3.

        Args:
            s3_key: S3 object key.
            local_path: Local path to save the file.

        Returns:
            Path to downloaded file.

        Raises:
            S3ClientError: If download fails.
        """
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)

            async with self._session.client("s3", **self._get_client_config()) as s3:
                await s3.download_file(
                    self.settings.s3_bucket,
                    s3_key,
                    str(local_path),
                )

            logger.info(
                "File downloaded from S3",
                extra={"s3_key": s3_key, "local_path": str(local_path)},
            )
            return local_path

        except ClientError as e:
            logger.exception("Failed to download file from S3", extra={"error": str(e)})
            raise S3ClientError(f"Failed to download {s3_key} from S3: {e}") from e

    async def list_objects(
        self,
        prefix: str | None = None,
        max_keys: int = 1000,
    ) -> list[dict]:
        """List objects in S3 bucket.

        Args:
            prefix: Optional prefix to filter objects.
            max_keys: Maximum number of objects to return.

        Returns:
            List of object metadata dictionaries with keys:
            - Key: Object key
            - LastModified: Last modification datetime
            - Size: Object size in bytes
            - ETag: Object ETag
        """
        try:
            async with self._session.client("s3", **self._get_client_config()) as s3:
                params = {
                    "Bucket": self.settings.s3_bucket,
                    "MaxKeys": max_keys,
                }
                if prefix:
                    params["Prefix"] = prefix

                response = await s3.list_objects_v2(**params)

            objects = response.get("Contents", [])
            return [
                {
                    "Key": obj["Key"],
                    "LastModified": obj["LastModified"],
                    "Size": obj["Size"],
                    "ETag": obj.get("ETag", ""),
                }
                for obj in objects
            ]

        except ClientError as e:
            logger.exception("Failed to list S3 objects", extra={"error": str(e)})
            raise S3ClientError(f"Failed to list objects in S3: {e}") from e

    async def delete_object(self, s3_key: str) -> bool:
        """Delete an object from S3.

        Args:
            s3_key: S3 object key.

        Returns:
            True if deleted successfully.

        Raises:
            S3ClientError: If deletion fails.
        """
        try:
            async with self._session.client("s3", **self._get_client_config()) as s3:
                await s3.delete_object(
                    Bucket=self.settings.s3_bucket,
                    Key=s3_key,
                )

            logger.info("Object deleted from S3", extra={"s3_key": s3_key})
            return True

        except ClientError as e:
            logger.exception("Failed to delete S3 object", extra={"error": str(e)})
            raise S3ClientError(f"Failed to delete {s3_key} from S3: {e}") from e

    async def delete_old_objects(
        self,
        prefix: str,
        retention_days: int | None = None,
    ) -> int:
        """Delete objects older than retention period.

        Args:
            prefix: Prefix to filter objects.
            retention_days: Days to keep objects. Uses settings default if not provided.

        Returns:
            Number of objects deleted.
        """
        if retention_days is None:
            retention_days = self.settings.s3_retention_days

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        objects = await self.list_objects(prefix=prefix)

        deleted_count = 0
        for obj in objects:
            last_modified = obj["LastModified"]
            # Ensure timezone aware comparison
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=UTC)

            if last_modified < cutoff:
                try:
                    await self.delete_object(obj["Key"])
                    deleted_count += 1
                except S3ClientError:
                    logger.warning(
                        "Failed to delete old S3 object",
                        extra={"s3_key": obj["Key"]},
                    )

        logger.info(
            "Old S3 objects cleanup completed",
            extra={
                "prefix": prefix,
                "retention_days": retention_days,
                "deleted_count": deleted_count,
            },
        )
        return deleted_count

    async def object_exists(self, s3_key: str) -> bool:
        """Check if an object exists in S3.

        Args:
            s3_key: S3 object key.

        Returns:
            True if object exists.
        """
        try:
            async with self._session.client("s3", **self._get_client_config()) as s3:
                await s3.head_object(
                    Bucket=self.settings.s3_bucket,
                    Key=s3_key,
                )
            return True
        except ClientError:
            return False

    async def get_object_info(self, s3_key: str) -> dict | None:
        """Get object metadata.

        Args:
            s3_key: S3 object key.

        Returns:
            Object metadata or None if not found.
        """
        try:
            async with self._session.client("s3", **self._get_client_config()) as s3:
                response = await s3.head_object(
                    Bucket=self.settings.s3_bucket,
                    Key=s3_key,
                )
            return {
                "Key": s3_key,
                "ContentLength": response.get("ContentLength"),
                "ContentType": response.get("ContentType"),
                "LastModified": response.get("LastModified"),
                "ETag": response.get("ETag"),
                "Metadata": response.get("Metadata", {}),
            }
        except ClientError:
            return None


# Global client instance (initialized lazily)
_s3_client: S3Client | None = None


def get_s3_client() -> S3Client | None:
    """Get the global S3 client instance.

    Returns:
        S3Client if configured and available, None otherwise.
    """
    global _s3_client

    if _s3_client is not None:
        return _s3_client

    from example_service.core.settings import get_backup_settings

    settings = get_backup_settings()

    if not settings.is_s3_configured:
        logger.debug("S3 not configured, skipping client initialization")
        return None

    if not AIOBOTO3_AVAILABLE:
        logger.warning("aioboto3 not installed, S3 client unavailable")
        return None

    try:
        _s3_client = S3Client(settings)
        logger.info("S3 client initialized")
        return _s3_client
    except S3ClientError as e:
        logger.warning(f"Failed to initialize S3 client: {e}")
        return None
