"""Repository layer for email feature.

Provides data access operations for:
- EmailConfig: Tenant-specific email provider configuration
- EmailUsageLog: Usage and cost tracking
- EmailAuditLog: Privacy-compliant audit trail
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Integer, func, select

from example_service.core.database.repository import SearchResult, TenantAwareRepository
from example_service.features.email.models import (
    EmailAuditLog,
    EmailConfig,
    EmailUsageLog,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class EmailConfigRepository(TenantAwareRepository[EmailConfig]):
    """Repository for EmailConfig model with tenant-aware operations.

    Inherits from TenantAwareRepository:
        - get(session, id) -> EmailConfig | None
        - get_or_raise(session, id) -> EmailConfig
        - get_by(session, attr, value) -> EmailConfig | None
        - list(session, limit, offset) -> Sequence[EmailConfig]
        - search(session, statement, limit, offset) -> SearchResult[EmailConfig]
        - create(session, instance) -> EmailConfig
        - delete(session, instance) -> None

    Tenant-aware methods:
        - get_for_tenant(session, id, tenant_id) -> EmailConfig | None
        - list_for_tenant(session, tenant_id, limit, offset) -> Sequence[EmailConfig]
    """

    def __init__(self) -> None:
        """Initialize with EmailConfig model."""
        super().__init__(EmailConfig)

    async def get_by_tenant_id(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> EmailConfig | None:
        """Get email configuration for a specific tenant.

        Args:
            session: Database session
            tenant_id: Tenant identifier

        Returns:
            EmailConfig if found, None otherwise
        """
        result = await self.get_by(session, EmailConfig.tenant_id, tenant_id)
        self._lazy.debug(
            lambda: f"db.get_by_tenant_id({tenant_id}) -> {'found' if result else 'not found'}"
        )
        return result

    async def get_active_by_tenant_id(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> EmailConfig | None:
        """Get active email configuration for a tenant.

        Args:
            session: Database session
            tenant_id: Tenant identifier

        Returns:
            Active EmailConfig if found, None otherwise
        """
        stmt = select(EmailConfig).where(
            EmailConfig.tenant_id == tenant_id,
            EmailConfig.is_active == True,  # noqa: E712
        )
        result = await session.execute(stmt)
        config = result.scalar_one_or_none()

        self._lazy.debug(
            lambda: f"db.get_active_by_tenant_id({tenant_id}) -> {'found' if config else 'not found'}"
        )
        return config

    async def list_active_configs(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[EmailConfig]:
        """List all active email configurations.

        Args:
            session: Database session
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of active EmailConfig instances
        """
        stmt = (
            select(EmailConfig)
            .where(EmailConfig.is_active == True)  # noqa: E712
            .order_by(EmailConfig.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_active_configs(limit={limit}, offset={offset}) -> {len(items)} items"
        )
        return items

    async def list_by_provider_type(
        self,
        session: AsyncSession,
        provider_type: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[EmailConfig]:
        """List configurations by provider type.

        Args:
            session: Database session
            provider_type: Provider type to filter by
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of EmailConfig instances for the provider
        """
        stmt = (
            select(EmailConfig)
            .where(EmailConfig.provider_type == provider_type)
            .order_by(EmailConfig.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.list_by_provider_type({provider_type}) -> {len(items)} items"
        )
        return items

    async def update_config(
        self,
        session: AsyncSession,
        config: EmailConfig,
        update_data: dict,
    ) -> EmailConfig:
        """Update email configuration fields.

        Args:
            session: Database session
            config: EmailConfig instance to update
            update_data: Dictionary of fields to update

        Returns:
            Updated EmailConfig instance
        """
        for field, value in update_data.items():
            if value is not None and hasattr(config, field):
                setattr(config, field, value)

        await session.flush()
        await session.refresh(config)

        self._lazy.debug(
            lambda: f"db.update_config({config.tenant_id}) -> updated {len(update_data)} fields"
        )
        return config


class EmailUsageLogRepository(TenantAwareRepository[EmailUsageLog]):
    """Repository for EmailUsageLog model.

    Provides methods for querying email usage statistics and logs.
    """

    def __init__(self) -> None:
        """Initialize with EmailUsageLog model."""
        super().__init__(EmailUsageLog)

    async def get_usage_logs(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[EmailUsageLog]:
        """Get usage logs for a tenant within a date range.

        Args:
            session: Database session
            tenant_id: Tenant identifier
            start_date: Start of date range (default: 30 days ago)
            end_date: End of date range (default: now)
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of EmailUsageLog instances
        """
        if end_date is None:
            end_date = datetime.now(UTC)
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        stmt = (
            select(EmailUsageLog)
            .where(
                EmailUsageLog.tenant_id == tenant_id,
                EmailUsageLog.created_at >= start_date,
                EmailUsageLog.created_at <= end_date,
            )
            .order_by(EmailUsageLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.get_usage_logs({tenant_id}, {start_date} to {end_date}) -> {len(items)} items"
        )
        return items

    async def get_usage_stats(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict:
        """Get aggregated usage statistics for a tenant.

        Args:
            session: Database session
            tenant_id: Tenant identifier
            start_date: Start of date range (default: 30 days ago)
            end_date: End of date range (default: now)

        Returns:
            Dictionary with aggregated statistics
        """
        if end_date is None:
            end_date = datetime.now(UTC)
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        # Query for aggregated stats
        stmt = (
            select(
                func.count().label("total_emails"),
                func.sum(func.cast(EmailUsageLog.success, Integer)).label("successful_emails"),
                func.sum(EmailUsageLog.recipients_count).label("total_recipients"),
                func.sum(EmailUsageLog.cost_usd).label("total_cost"),
            )
            .where(
                EmailUsageLog.tenant_id == tenant_id,
                EmailUsageLog.created_at >= start_date,
                EmailUsageLog.created_at <= end_date,
            )
        )
        result = await session.execute(stmt)
        row = result.one()

        total_emails = row.total_emails or 0
        successful_emails = row.successful_emails or 0
        failed_emails = total_emails - successful_emails

        return {
            "total_emails": total_emails,
            "successful_emails": successful_emails,
            "failed_emails": failed_emails,
            "success_rate": (successful_emails / total_emails * 100) if total_emails > 0 else 0.0,
            "total_recipients": row.total_recipients or 0,
            "total_cost_usd": float(row.total_cost) if row.total_cost else None,
        }

    async def get_usage_by_provider(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, dict]:
        """Get usage statistics grouped by provider.

        Args:
            session: Database session
            tenant_id: Tenant identifier
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dictionary mapping provider names to their stats
        """
        if end_date is None:
            end_date = datetime.now(UTC)
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        stmt = (
            select(
                EmailUsageLog.provider,
                func.count().label("count"),
                func.sum(EmailUsageLog.cost_usd).label("cost"),
            )
            .where(
                EmailUsageLog.tenant_id == tenant_id,
                EmailUsageLog.created_at >= start_date,
                EmailUsageLog.created_at <= end_date,
            )
            .group_by(EmailUsageLog.provider)
        )
        result = await session.execute(stmt)
        rows = result.all()

        provider_stats = {}
        for row in rows:
            provider_stats[row.provider] = {
                "count": row.count,
                "cost": float(row.cost) if row.cost else 0.0,
            }

        return provider_stats


class EmailAuditLogRepository(TenantAwareRepository[EmailAuditLog]):
    """Repository for EmailAuditLog model.

    Provides methods for querying privacy-compliant email audit logs.
    """

    def __init__(self) -> None:
        """Initialize with EmailAuditLog model."""
        super().__init__(EmailAuditLog)

    async def get_audit_logs(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResult[EmailAuditLog]:
        """Get paginated audit logs for a tenant.

        Args:
            session: Database session
            tenant_id: Tenant identifier
            limit: Page size
            offset: Results to skip

        Returns:
            SearchResult with audit logs and pagination info
        """
        stmt = (
            select(EmailAuditLog)
            .where(EmailAuditLog.tenant_id == tenant_id)
            .order_by(EmailAuditLog.created_at.desc())
        )
        return await self.search(session, stmt, limit=limit, offset=offset)

    async def get_by_recipient_hash(
        self,
        session: AsyncSession,
        recipient_hash: str,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EmailAuditLog]:
        """Find audit logs by recipient hash.

        Used for compliance queries ("was email sent to X").

        Args:
            session: Database session
            recipient_hash: SHA256 hash of recipient email
            tenant_id: Optional tenant filter
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of matching audit logs
        """
        stmt = (
            select(EmailAuditLog)
            .where(EmailAuditLog.recipient_hash == recipient_hash)
            .order_by(EmailAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = self._apply_tenant_filter(stmt, tenant_id)

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.get_by_recipient_hash({recipient_hash[:8]}...) -> {len(items)} items"
        )
        return items

    async def get_by_status(
        self,
        session: AsyncSession,
        status: str,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EmailAuditLog]:
        """Find audit logs by status.

        Args:
            session: Database session
            status: Status to filter by (queued, sent, failed, bounced)
            tenant_id: Optional tenant filter
            limit: Maximum results
            offset: Results to skip

        Returns:
            Sequence of matching audit logs
        """
        stmt = (
            select(EmailAuditLog)
            .where(EmailAuditLog.status == status)
            .order_by(EmailAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        stmt = self._apply_tenant_filter(stmt, tenant_id)

        result = await session.execute(stmt)
        items = result.scalars().all()

        self._lazy.debug(
            lambda: f"db.get_by_status({status}, tenant={tenant_id}) -> {len(items)} items"
        )
        return items

    async def count_by_status(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, int]:
        """Get count of audit logs grouped by status.

        Args:
            session: Database session
            tenant_id: Tenant identifier
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dictionary mapping status to count
        """
        if end_date is None:
            end_date = datetime.now(UTC)
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        stmt = (
            select(
                EmailAuditLog.status,
                func.count().label("count"),
            )
            .where(
                EmailAuditLog.tenant_id == tenant_id,
                EmailAuditLog.created_at >= start_date,
                EmailAuditLog.created_at <= end_date,
            )
            .group_by(EmailAuditLog.status)
        )
        result = await session.execute(stmt)
        rows = result.all()

        return {row.status: row.count for row in rows}


# Factory functions for dependency injection
_email_config_repository: EmailConfigRepository | None = None
_email_usage_log_repository: EmailUsageLogRepository | None = None
_email_audit_log_repository: EmailAuditLogRepository | None = None


def get_email_config_repository() -> EmailConfigRepository:
    """Get EmailConfigRepository singleton instance.

    Usage in FastAPI routes:
        from example_service.features.email.repository import (
            EmailConfigRepository,
            get_email_config_repository,
        )

        @router.get("/configs/{tenant_id}")
        async def get_config(
            tenant_id: str,
            session: AsyncSession = Depends(get_db_session),
            repo: EmailConfigRepository = Depends(get_email_config_repository),
        ):
            return await repo.get_by_tenant_id(session, tenant_id)
    """
    global _email_config_repository
    if _email_config_repository is None:
        _email_config_repository = EmailConfigRepository()
    return _email_config_repository


def get_email_usage_log_repository() -> EmailUsageLogRepository:
    """Get EmailUsageLogRepository singleton instance."""
    global _email_usage_log_repository
    if _email_usage_log_repository is None:
        _email_usage_log_repository = EmailUsageLogRepository()
    return _email_usage_log_repository


def get_email_audit_log_repository() -> EmailAuditLogRepository:
    """Get EmailAuditLogRepository singleton instance."""
    global _email_audit_log_repository
    if _email_audit_log_repository is None:
        _email_audit_log_repository = EmailAuditLogRepository()
    return _email_audit_log_repository


__all__ = [
    "EmailAuditLogRepository",
    "EmailConfigRepository",
    "EmailUsageLogRepository",
    "get_email_audit_log_repository",
    "get_email_config_repository",
    "get_email_usage_log_repository",
]
