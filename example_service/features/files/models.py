"""SQLAlchemy models for the files feature."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from example_service.core.database import TenantMixin, TimestampedBase
from example_service.core.database.enums import FileStatus as FileStatusEnum


class FileStatus(str, enum.Enum):
    """File processing status."""

    PENDING = "pending"  # Upload initiated but not confirmed
    PROCESSING = "processing"  # File being processed (thumbnails, validation)
    READY = "ready"  # File ready for use
    FAILED = "failed"  # Processing failed
    DELETED = "deleted"  # Soft deleted


class File(TimestampedBase, TenantMixin):
    """File metadata stored in the database.

    Tracks uploaded files with their storage location, metadata, and processing status.
    Supports multi-tenancy via tenant_id for data isolation.

    Files are initially uploaded to a universal bucket, then relocated to
    tenant-specific buckets. The bucket field tracks the current location.
    """

    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        FileStatusEnum,
        nullable=False,
        default="pending",
        index=True,
    )
    owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship to thumbnails
    thumbnails: Mapped[list["FileThumbnail"]] = relationship(
        "FileThumbnail",
        back_populates="file",
        cascade="all, delete-orphan",
    )


class FileThumbnail(TimestampedBase):
    """Thumbnail generated from an image file.

    Stores metadata for thumbnails at different sizes.
    """

    __tablename__ = "file_thumbnails"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationship to parent file
    file: Mapped["File"] = relationship("File", back_populates="thumbnails")
