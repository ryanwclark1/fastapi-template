"""Storage management commands for S3-compatible object storage.

This module provides CLI commands for managing S3-compatible storage including:
- Configuration and status information
- File listing and searching
- Health checks and connectivity tests
- Batch file operations (upload, download, copy, move, delete)
"""

import fnmatch
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from example_service.cli.utils import coro, error, info, success, warning
from example_service.core.settings import get_storage_settings


def _format_bytes(size_bytes: int) -> str:
    """Format bytes to human-readable size.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Human-readable string (e.g., "1.5 MB").
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{int(size_bytes)} {unit}"
        size_bytes = int(size_bytes / 1024.0)
    return f"{size_bytes:.2f} PB"


@click.group(name="storage")
def storage() -> None:
    """Storage management commands.

    Manage S3-compatible object storage operations including
    configuration, file listing, and health checks.
    """


@storage.command(name="info")
def info_cmd() -> None:
    """Show storage configuration and status.

    Displays storage endpoint, bucket, region, and connection status.
    Tests connectivity if storage is enabled.
    """
    info("Fetching storage configuration...")

    try:
        settings = get_storage_settings()

        click.echo("\n" + "=" * 60)
        click.secho("Storage Configuration", fg="cyan", bold=True)
        click.echo("=" * 60)

        # Basic configuration
        click.echo(f"\nEnabled: {settings.enabled}")
        click.echo(f"Configured: {settings.is_configured}")

        if settings.endpoint:
            click.echo(f"Endpoint: {settings.endpoint}")
            click.echo("Type: S3-compatible (MinIO/LocalStack)")
        else:
            click.echo("Endpoint: AWS S3 (default)")
            click.echo("Type: AWS S3")

        click.echo(f"Bucket: {settings.bucket}")
        click.echo(f"Region: {settings.region}")
        click.echo(f"Use SSL: {settings.use_ssl}")

        # Upload configuration
        click.echo(
            f"\nMax File Size: {settings.max_file_size_mb} MB ({_format_bytes(settings.max_file_size_bytes)})"
        )
        click.echo(f"Presigned URL Expiry: {settings.presigned_url_expiry_seconds}s")
        click.echo(f"Upload Prefix: {settings.upload_prefix}")

        # Processing
        click.echo(f"\nThumbnails Enabled: {settings.enable_thumbnails}")
        if settings.enable_thumbnails:
            click.echo(f"Thumbnail Sizes: {', '.join(map(str, settings.thumbnail_sizes))}px")
            click.echo(f"Thumbnail Prefix: {settings.thumbnail_prefix}")

        # Health check configuration
        click.echo(f"\nHealth Check Enabled: {settings.health_check_enabled}")
        if settings.health_check_enabled:
            click.echo(f"Health Check Timeout: {settings.health_check_timeout}s")

        # Credentials status (don't show actual values)
        if settings.access_key and settings.secret_key:
            success("\nCredentials: Configured")
        else:
            warning("\nCredentials: Not configured")

        click.echo("\n" + "=" * 60)

        if not settings.is_configured:
            warning("\nStorage is not fully configured.")
            info("Set STORAGE_ENABLED=true, STORAGE_ACCESS_KEY, and STORAGE_SECRET_KEY")
        else:
            success("\nStorage is properly configured")

    except Exception as e:
        error(f"Failed to get storage configuration: {e}")
        sys.exit(1)


@storage.command(name="list")
@click.argument("prefix", default="")
@click.option(
    "--limit",
    type=int,
    default=100,
    help="Maximum number of files to list (default: 100)",
)
@coro
async def list_files(prefix: str, limit: int) -> None:
    """List files in storage bucket with optional prefix filter.

    Args:
        prefix: Optional prefix to filter files (e.g., 'uploads/', 'images/2024/')
        limit: Maximum number of files to display

    Examples:
        example-service storage list
        example-service storage list uploads/
        example-service storage list --limit 50 images/
    """
    info(f"Listing files from storage (prefix: '{prefix or 'root'}', limit: {limit})...")

    try:
        settings = get_storage_settings()

        if not settings.is_configured:
            error("Storage is not configured. Run 'example-service storage info' for details.")
            sys.exit(1)

        # Import here to avoid dependency issues
        from example_service.core.settings import get_backup_settings
        from example_service.infra.storage.s3 import S3Client

        # Note: Using S3Client for listing as StorageClient doesn't have list method
        # You may want to extend StorageClient with list_objects method
        backup_settings = get_backup_settings()

        # Configure backup settings to use storage settings
        # This is a workaround - ideally StorageClient should have list_objects
        if backup_settings.is_s3_configured:
            client = S3Client(backup_settings)

            objects = await client.list_objects(prefix=prefix, max_keys=limit)

            if not objects:
                warning(f"No files found with prefix: '{prefix}'")
                return

            click.echo(f"\n{'=' * 100}")
            click.secho(
                f"Storage Objects (showing {len(objects)} of max {limit})", fg="cyan", bold=True
            )
            click.echo(f"{'=' * 100}")

            # Header
            click.echo(f"\n{'Key':<50} {'Size':<12} {'Last Modified':<25}")
            click.echo("-" * 100)

            # Files
            total_size = 0
            for obj in objects:
                key = obj["Key"]
                size = obj["Size"]
                modified = obj["LastModified"]

                # Truncate long keys
                display_key = key if len(key) <= 48 else "..." + key[-45:]

                # Format datetime
                if isinstance(modified, datetime):
                    modified_str = modified.strftime("%Y-%m-%d %H:%M:%S %Z")
                else:
                    modified_str = str(modified)

                click.echo(f"{display_key:<50} {_format_bytes(size):<12} {modified_str:<25}")
                total_size += size

            click.echo("-" * 100)
            click.echo(f"Total: {len(objects)} files, {_format_bytes(total_size)}")
            click.echo()

            success(f"Successfully listed {len(objects)} files")
        else:
            error("S3 backup settings not configured. Cannot list files.")
            info("Configure BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY, and BACKUP_S3_SECRET_KEY")
            sys.exit(1)

    except Exception as e:
        error(f"Failed to list storage files: {e}")
        sys.exit(1)


@storage.command()
@coro
async def check() -> None:
    """Run health check on storage.

    Verifies:
    - Storage configuration is valid
    - Credentials are set
    - Bucket is accessible (if configured)
    - Read/write permissions work
    - Connection latency
    """
    info("Running storage health check...")

    try:
        settings = get_storage_settings()

        click.echo("\n" + "=" * 60)
        click.secho("Storage Health Check", fg="cyan", bold=True)
        click.echo("=" * 60)

        # Check 1: Enabled status
        click.echo("\n1. Configuration Check:")
        if settings.enabled:
            success("   Storage is enabled")
        else:
            warning("   Storage is disabled (STORAGE_ENABLED=false)")
            info("   Set STORAGE_ENABLED=true to enable storage")

        # Check 2: Credentials
        click.echo("\n2. Credentials Check:")
        if settings.is_configured:
            success("   Credentials are configured")
        else:
            error("   Credentials are missing")
            info("   Set STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY")
            click.echo("\n" + "=" * 60)
            sys.exit(1)

        # Check 3: Bucket accessibility
        click.echo("\n3. Bucket Accessibility:")
        try:
            from example_service.core.settings import get_backup_settings
            from example_service.infra.storage.s3 import S3Client

            backup_settings = get_backup_settings()

            if not backup_settings.is_s3_configured:
                warning("   S3 backup settings not configured")
                info(
                    "   Configure BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY, and BACKUP_S3_SECRET_KEY"
                )
                click.echo("\n" + "=" * 60)
                return

            client = S3Client(backup_settings)

            # Test listing (this will fail if bucket doesn't exist or is inaccessible)
            start_time = time.time()
            await client.list_objects(prefix="", max_keys=1)
            latency = (time.time() - start_time) * 1000  # Convert to ms

            success(f"   Bucket '{backup_settings.s3_bucket}' is accessible")
            info(f"   Response time: {latency:.2f}ms")

        except Exception as e:
            error(f"   Failed to access bucket: {e}")
            click.echo("\n" + "=" * 60)
            sys.exit(1)

        # Check 4: Permissions (optional test file)
        click.echo("\n4. Read/Write Permissions:")
        try:
            import tempfile
            from pathlib import Path

            # Create a small test file
            test_key = f"_healthcheck_test_{int(time.time())}.txt"
            test_content = b"Storage health check test file"

            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(test_content)
                tmp_path = Path(tmp_file.name)

            try:
                # Test write
                info("   Testing write permissions...")
                await client.upload_file(
                    local_path=tmp_path,
                    s3_key=test_key,
                    content_type="text/plain",
                    metadata={"purpose": "healthcheck"},
                )
                success("   Write permission: OK")

                # Test read
                info("   Testing read permissions...")
                exists = await client.object_exists(test_key)
                if exists:
                    success("   Read permission: OK")
                else:
                    warning("   Read verification failed")

                # Test delete
                info("   Testing delete permissions...")
                await client.delete_object(test_key)
                success("   Delete permission: OK")

            finally:
                # Clean up temp file
                tmp_path.unlink(missing_ok=True)

        except Exception as e:
            error(f"   Permission check failed: {e}")
            warning("   Some operations may not be available")

        click.echo("\n" + "=" * 60)
        success("\nStorage health check completed successfully!")

    except Exception as e:
        error(f"\nHealth check failed: {e}")
        click.echo("\n" + "=" * 60)
        sys.exit(1)


@storage.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--key",
    type=str,
    help="S3 key for single file upload (required if uploading one file)",
)
@click.option(
    "--prefix",
    type=str,
    default="uploads/",
    help="S3 key prefix for batch uploads (default: uploads/)",
)
@click.option(
    "--recursive",
    is_flag=True,
    help="Recursively upload directories",
)
@click.option(
    "--bucket",
    type=str,
    help="Override default bucket",
)
@coro
async def upload(
    files: tuple[str, ...],
    key: str | None,
    prefix: str,
    recursive: bool,
    bucket: str | None,
) -> None:
    """Upload file(s) to storage.

    Examples:
        Single file:
            example-service storage upload local_file.pdf --key uploads/file.pdf

        Multiple files:
            example-service storage upload file1.pdf file2.pdf --prefix uploads/

        Folder upload:
            example-service storage upload ./my_folder/ --prefix uploads/ --recursive
    """
    info("Preparing to upload files to storage...")

    try:
        settings = get_storage_settings()

        if not settings.is_configured:
            error("Storage is not configured. Run 'example-service storage info' for details.")
            sys.exit(1)

        from example_service.infra.storage import get_storage_service

        # Validate arguments
        if len(files) == 1 and not Path(files[0]).is_dir() and not key:
            # Single file upload - require --key
            error("Single file upload requires --key parameter")
            info("Usage: example-service storage upload file.pdf --key uploads/file.pdf")
            sys.exit(1)

        # Collect all files to upload
        upload_tasks = []
        for file_path_str in files:
            file_path = Path(file_path_str)

            if file_path.is_file():
                # Single file
                s3_key = key if key else f"{prefix.rstrip('/')}/{file_path.name}"
                upload_tasks.append((file_path, s3_key))
            elif file_path.is_dir() and recursive:
                # Directory - collect all files
                for sub_file in file_path.rglob("*"):
                    if sub_file.is_file():
                        # Preserve directory structure
                        rel_path = sub_file.relative_to(file_path.parent)
                        s3_key = f"{prefix.rstrip('/')}/{rel_path}"
                        upload_tasks.append((sub_file, s3_key))
            elif file_path.is_dir():
                warning(f"Skipping directory {file_path} (use --recursive to upload directories)")

        if not upload_tasks:
            warning("No files to upload")
            return

        click.echo(f"\n{'=' * 80}")
        click.secho(f"Uploading {len(upload_tasks)} file(s)", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}\n")

        # Upload files
        total_size = 0
        success_count = 0
        failed_count = 0

        service = get_storage_service()
        await service.startup()
        try:
            for local_path, s3_key in upload_tasks:
                try:
                    file_size = local_path.stat().st_size
                    info(f"Uploading {local_path.name} -> {s3_key} ({_format_bytes(file_size)})")

                    with open(local_path, "rb") as f:
                        await service.upload_file(
                            file_obj=f,
                            key=s3_key,
                            bucket=bucket,
                        )

                    success(f"  Uploaded {s3_key}")
                    total_size += file_size
                    success_count += 1

                except Exception as e:
                    error(f"  Failed to upload {local_path.name}: {e}")
                    failed_count += 1
        finally:
            await service.shutdown()

        click.echo(f"\n{'=' * 80}")
        click.secho("Upload Summary", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}")
        click.echo(f"Successful: {success_count}")
        click.echo(f"Failed: {failed_count}")
        click.echo(f"Total Size: {_format_bytes(total_size)}")
        click.echo()

        if success_count > 0:
            success(f"Successfully uploaded {success_count} file(s)")
        if failed_count > 0:
            error(f"Failed to upload {failed_count} file(s)")
            sys.exit(1)

    except Exception as e:
        error(f"Upload operation failed: {e}")
        sys.exit(1)


@storage.command()
@click.argument("key", required=False)
@click.option(
    "--prefix",
    type=str,
    help="Download all files with this prefix",
)
@click.option(
    "--pattern",
    type=str,
    help="Filter files by pattern (e.g., '*.pdf')",
)
@click.option(
    "--output",
    type=click.Path(),
    default="./downloads",
    help="Output directory for downloads (default: ./downloads)",
)
@click.option(
    "--bucket",
    type=str,
    help="Override default bucket",
)
@coro
async def download(
    key: str | None,
    prefix: str | None,
    pattern: str | None,
    output: str,
    bucket: str | None,
) -> None:
    """Download file(s) from storage.

    Examples:
        Single file:
            example-service storage download uploads/file.pdf --output ./downloaded.pdf

        Multiple files by prefix:
            example-service storage download --prefix uploads/2024/ --output ./downloads/

        With pattern filtering:
            example-service storage download --prefix uploads/ --pattern "*.pdf" --output ./pdfs/
    """
    info("Preparing to download files from storage...")

    try:
        settings = get_storage_settings()

        if not settings.is_configured:
            error("Storage is not configured. Run 'example-service storage info' for details.")
            sys.exit(1)

        # Validate arguments
        if not key and not prefix:
            error("Either KEY argument or --prefix option is required")
            info("Usage: example-service storage download KEY --output file.pdf")
            info("   or: example-service storage download --prefix uploads/ --output ./dir/")
            sys.exit(1)

        from example_service.core.settings import get_backup_settings
        from example_service.infra.storage import get_storage_service
        from example_service.infra.storage.s3 import S3Client

        output_path = Path(output)

        # Get list of files to download
        download_tasks = []

        if key:
            # Single file download
            download_tasks.append(key)
        else:
            # List files with prefix
            backup_settings = get_backup_settings()
            if not backup_settings.is_s3_configured:
                error("S3 backup settings not configured. Cannot list files.")
                sys.exit(1)

            s3_client = S3Client(backup_settings)
            objects = await s3_client.list_objects(prefix=prefix, max_keys=1000)

            for obj in objects:
                file_key = obj["Key"]
                # Apply pattern filter if specified
                if pattern:
                    if fnmatch.fnmatch(file_key, pattern) or fnmatch.fnmatch(
                        Path(file_key).name, pattern
                    ):
                        download_tasks.append(file_key)
                else:
                    download_tasks.append(file_key)

        if not download_tasks:
            warning("No files to download")
            return

        click.echo(f"\n{'=' * 80}")
        click.secho(f"Downloading {len(download_tasks)} file(s)", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}\n")

        # Download files
        total_size = 0
        success_count = 0
        failed_count = 0

        service = get_storage_service()
        await service.startup()
        try:
            for s3_key in download_tasks:
                try:
                    info(f"Downloading {s3_key}")

                    # Determine output file path
                    if len(download_tasks) == 1 and output_path.suffix:
                        # Single file with specific output path
                        local_path = output_path
                    else:
                        # Multiple files or directory output
                        local_path = output_path / Path(s3_key).name

                    # Ensure parent directory exists
                    local_path.parent.mkdir(parents=True, exist_ok=True)

                    # Download file
                    file_data = await service.download_file(key=s3_key, bucket=bucket)

                    # Write to local file
                    with open(local_path, "wb") as f:
                        f.write(file_data)

                    file_size = len(file_data)
                    success(f"  Downloaded to {local_path} ({_format_bytes(file_size)})")
                    total_size += file_size
                    success_count += 1

                except Exception as e:
                    error(f"  Failed to download {s3_key}: {e}")
                    failed_count += 1
        finally:
            await service.shutdown()

        click.echo(f"\n{'=' * 80}")
        click.secho("Download Summary", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}")
        click.echo(f"Successful: {success_count}")
        click.echo(f"Failed: {failed_count}")
        click.echo(f"Total Size: {_format_bytes(total_size)}")
        click.echo()

        if success_count > 0:
            success(f"Successfully downloaded {success_count} file(s)")
        if failed_count > 0:
            error(f"Failed to download {failed_count} file(s)")
            sys.exit(1)

    except Exception as e:
        error(f"Download operation failed: {e}")
        sys.exit(1)


@storage.command()
@click.argument("keys", nargs=-1, required=False)
@click.option(
    "--prefix",
    type=str,
    help="Delete all files with this prefix",
)
@click.option(
    "--pattern",
    type=str,
    help="Filter files by pattern (e.g., '*.tmp')",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=True,
    help="Preview files to be deleted without actually deleting (default)",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Actually delete files (required for deletion)",
)
@click.option(
    "--bucket",
    type=str,
    help="Override default bucket",
)
@coro
async def delete(
    keys: tuple[str, ...],
    prefix: str | None,
    pattern: str | None,
    dry_run: bool,
    confirm: bool,
    bucket: str | None,
) -> None:
    """Delete file(s) from storage with dry-run protection.

    By default, performs a dry-run to preview files that would be deleted.
    Use --confirm to actually delete files.

    Examples:
        Dry run (preview):
            example-service storage delete uploads/old/

        Actually delete:
            example-service storage delete uploads/old/ --prefix --confirm

        Delete specific files:
            example-service storage delete uploads/file1.pdf uploads/file2.pdf --confirm
    """
    # Override dry_run if confirm is explicitly set
    if confirm:
        dry_run = False

    mode_str = "DRY RUN - Preview" if dry_run else "DELETE - Confirmed"
    warning(f"Delete mode: {mode_str}")

    try:
        settings = get_storage_settings()

        if not settings.is_configured:
            error("Storage is not configured. Run 'example-service storage info' for details.")
            sys.exit(1)

        # Validate arguments
        if not keys and not prefix:
            error("Either KEY arguments or --prefix option is required")
            info("Usage: example-service storage delete KEY1 KEY2 --confirm")
            info("   or: example-service storage delete --prefix uploads/old/ --confirm")
            sys.exit(1)

        from example_service.core.settings import get_backup_settings
        from example_service.infra.storage import get_storage_service
        from example_service.infra.storage.s3 import S3Client

        # Get list of files to delete
        delete_tasks: list[str | tuple[str, int]] = []

        if keys:
            # Specific files
            delete_tasks.extend(keys)
        else:
            # List files with prefix
            backup_settings = get_backup_settings()
            if not backup_settings.is_s3_configured:
                error("S3 backup settings not configured. Cannot list files.")
                sys.exit(1)

            s3_client = S3Client(backup_settings)
            objects = await s3_client.list_objects(prefix=prefix, max_keys=1000)

            for obj in objects:
                file_key = obj["Key"]
                # Apply pattern filter if specified
                if pattern:
                    if fnmatch.fnmatch(file_key, pattern) or fnmatch.fnmatch(
                        Path(file_key).name, pattern
                    ):
                        delete_tasks.append((file_key, obj["Size"]))
                else:
                    delete_tasks.append((file_key, obj["Size"]))

        if not delete_tasks:
            warning("No files to delete")
            return

        # Calculate total size
        total_size = sum(item[1] for item in delete_tasks if isinstance(item, tuple))

        click.echo(f"\n{'=' * 80}")
        if dry_run:
            click.secho(
                f"DRY RUN: Would delete {len(delete_tasks)} file(s)", fg="yellow", bold=True
            )
        else:
            click.secho(f"DELETING {len(delete_tasks)} file(s)", fg="red", bold=True)
        click.echo(f"{'=' * 80}\n")

        # List files
        for item in delete_tasks:
            if isinstance(item, tuple):
                file_key, file_size = item
                click.echo(f"  {file_key} ({_format_bytes(file_size)})")
            else:
                click.echo(f"  {item}")

        if dry_run:
            click.echo(f"\n{'=' * 80}")
            warning("DRY RUN MODE - No files were deleted")
            info("Add --confirm flag to actually delete these files:")
            info("  example-service storage delete <args> --confirm")
            click.echo(f"{'=' * 80}\n")
            return

        # Confirm deletion
        click.echo(f"\n{'=' * 80}")
        warning(f"You are about to DELETE {len(delete_tasks)} file(s)")
        if total_size > 0:
            warning(f"Total size: {_format_bytes(total_size)}")
        click.echo(f"{'=' * 80}\n")

        # Delete files
        success_count = 0
        failed_count = 0

        service = get_storage_service()
        await service.startup()
        try:
            for item in delete_tasks:
                file_key = item[0] if isinstance(item, tuple) else item
                try:
                    info(f"Deleting {file_key}")
                    await service.delete_file(key=file_key, bucket=bucket)
                    success(f"  Deleted {file_key}")
                    success_count += 1

                except Exception as e:
                    error(f"  Failed to delete {file_key}: {e}")
                    failed_count += 1
        finally:
            await service.shutdown()

        click.echo(f"\n{'=' * 80}")
        click.secho("Delete Summary", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}")
        click.echo(f"Successful: {success_count}")
        click.echo(f"Failed: {failed_count}")
        click.echo()

        if success_count > 0:
            success(f"Successfully deleted {success_count} file(s)")
        if failed_count > 0:
            error(f"Failed to delete {failed_count} file(s)")
            sys.exit(1)

    except Exception as e:
        error(f"Delete operation failed: {e}")
        sys.exit(1)


@storage.command()
@click.argument("source_key", required=True)
@click.argument("dest_key", required=False)
@click.option(
    "--to-bucket",
    type=str,
    help="Destination bucket (defaults to same bucket)",
)
@click.option(
    "--to-key",
    type=str,
    help="Destination key (use this or DEST_KEY argument)",
)
@click.option(
    "--bucket",
    type=str,
    help="Source bucket (overrides default)",
)
@coro
async def copy(
    source_key: str,
    dest_key: str | None,
    to_bucket: str | None,
    to_key: str | None,
    bucket: str | None,
) -> None:
    """Copy file within storage or to another bucket.

    Examples:
        Copy within same bucket:
            example-service storage copy uploads/source.pdf uploads/dest.pdf

        Copy to different bucket:
            example-service storage copy uploads/file.pdf --to-bucket archive --to-key archives/file.pdf
    """
    info("Preparing to copy file in storage...")

    try:
        settings = get_storage_settings()

        if not settings.is_configured:
            error("Storage is not configured. Run 'example-service storage info' for details.")
            sys.exit(1)

        # Validate arguments
        destination_key = dest_key or to_key
        if not destination_key:
            error("Destination key is required")
            info("Usage: example-service storage copy SOURCE_KEY DEST_KEY")
            info("   or: example-service storage copy SOURCE_KEY --to-key DEST_KEY")
            sys.exit(1)

        from example_service.infra.storage import get_storage_service

        source_bucket = bucket or settings.bucket
        dest_bucket = to_bucket or source_bucket

        click.echo(f"\n{'=' * 80}")
        click.secho("Copying File", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}")
        click.echo(f"Source: s3://{source_bucket}/{source_key}")
        click.echo(f"Destination: s3://{dest_bucket}/{destination_key}")
        click.echo(f"{'=' * 80}\n")

        service = get_storage_service()
        await service.startup()
        try:
            # Check if source exists
            info(f"Checking source file: {source_key}")
            exists = await service.file_exists(key=source_key, bucket=source_bucket)
            if not exists:
                error(f"Source file not found: {source_key}")
                sys.exit(1)

            # Get file info
            file_info = await service.get_file_info(key=source_key, bucket=source_bucket)
            if file_info:
                info(f"Source file size: {_format_bytes(file_info['size_bytes'])}")

            # Download and re-upload (S3 copy_object requires same region)
            info("Downloading source file...")
            file_data = await service.download_file(key=source_key, bucket=source_bucket)

            info(f"Uploading to destination: {destination_key}")
            from io import BytesIO

            result = await service.upload_file(
                file_obj=BytesIO(file_data),
                key=destination_key,
                bucket=dest_bucket,
                content_type=file_info.get("content_type") if file_info else None,
            )

            success(f"Successfully copied {source_key} -> {destination_key}")
            click.echo(f"\nDestination: s3://{result['bucket']}/{result['key']}")
            click.echo(f"Size: {_format_bytes(result['size_bytes'])}")
            click.echo(f"ETag: {result['etag']}")
        finally:
            await service.shutdown()

    except Exception as e:
        error(f"Copy operation failed: {e}")
        sys.exit(1)


@storage.command()
@click.argument("source_key", required=True)
@click.argument("dest_key", required=True)
@click.option(
    "--bucket",
    type=str,
    help="Override default bucket",
)
@coro
async def move(
    source_key: str,
    dest_key: str,
    bucket: str | None,
) -> None:
    """Move/rename file in storage.

    This operation copies the file to the new location and then deletes the source.

    Examples:
        Rename file:
            example-service storage move uploads/old_name.pdf uploads/new_name.pdf

        Move to different prefix:
            example-service storage move uploads/temp/file.pdf uploads/permanent/file.pdf
    """
    info("Preparing to move file in storage...")

    try:
        settings = get_storage_settings()

        if not settings.is_configured:
            error("Storage is not configured. Run 'example-service storage info' for details.")
            sys.exit(1)

        from example_service.infra.storage import get_storage_service

        target_bucket = bucket or settings.bucket

        click.echo(f"\n{'=' * 80}")
        click.secho("Moving File", fg="cyan", bold=True)
        click.echo(f"{'=' * 80}")
        click.echo(f"Source: s3://{target_bucket}/{source_key}")
        click.echo(f"Destination: s3://{target_bucket}/{dest_key}")
        click.echo(f"{'=' * 80}\n")

        service = get_storage_service()
        await service.startup()
        try:
            # Check if source exists
            info(f"Checking source file: {source_key}")
            exists = await service.file_exists(key=source_key, bucket=target_bucket)
            if not exists:
                error(f"Source file not found: {source_key}")
                sys.exit(1)

            # Get file info
            file_info = await service.get_file_info(key=source_key, bucket=target_bucket)
            if file_info:
                info(f"Source file size: {_format_bytes(file_info['size_bytes'])}")

            # Download source
            info("Downloading source file...")
            file_data = await service.download_file(key=source_key, bucket=target_bucket)

            # Upload to destination
            info(f"Uploading to destination: {dest_key}")
            from io import BytesIO

            result = await service.upload_file(
                file_obj=BytesIO(file_data),
                key=dest_key,
                bucket=target_bucket,
                content_type=file_info.get("content_type") if file_info else None,
            )

            success(f"Uploaded to {dest_key}")

            # Delete source
            info(f"Deleting source file: {source_key}")
            await service.delete_file(key=source_key, bucket=target_bucket)
            success("Deleted source file")

            click.echo(f"\n{'=' * 80}")
            success(f"Successfully moved {source_key} -> {dest_key}")
            click.echo(f"{'=' * 80}")
            click.echo(f"Destination: s3://{result['bucket']}/{result['key']}")
            click.echo(f"Size: {_format_bytes(result['size_bytes'])}")
            click.echo(f"ETag: {result['etag']}")
        finally:
            await service.shutdown()

    except Exception as e:
        error(f"Move operation failed: {e}")
        sys.exit(1)
