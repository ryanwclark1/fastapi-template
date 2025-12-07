"""Feature flag service.

Provides flag management and evaluation with caching support.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from .models import FeatureFlag, FlagOverride, FlagStatus
from .schemas import (
    FeatureFlagCreate,
    FeatureFlagListResponse,
    FeatureFlagResponse,
    FeatureFlagUpdate,
    FlagEvaluationRequest,
    FlagEvaluationResponse,
    FlagEvaluationResult,
    FlagOverrideCreate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class FeatureFlagService:
    """Service for managing and evaluating feature flags.

    Provides:
    - CRUD operations for feature flags
    - Flag evaluation with targeting rules
    - Percentage-based rollout
    - User/tenant overrides
    - Time-based activation

    Example:
        service = FeatureFlagService(session)

        # Create a flag
        flag = await service.create(FeatureFlagCreate(
            key="new_feature",
            name="New Feature",
            status=FlagStatus.PERCENTAGE,
            percentage=25,
        ))

        # Evaluate for a user
        result = await service.evaluate(
            FlagEvaluationRequest(user_id="user-123")
        )
        if result.flags.get("new_feature"):
            # Show new feature
            ...
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize feature flag service.

        Args:
            session: Database session.
        """
        self.session = session

    async def create(self, data: FeatureFlagCreate) -> FeatureFlag:
        """Create a new feature flag.

        Args:
            data: Flag creation data.

        Returns:
            Created feature flag.
        """
        flag = FeatureFlag(
            key=data.key,
            name=data.name,
            description=data.description,
            status=data.status.value,
            enabled=data.enabled,
            percentage=data.percentage,
            targeting_rules=[r.model_dump() for r in data.targeting_rules]
            if data.targeting_rules
            else None,
            context_data=data.metadata,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
        )

        self.session.add(flag)
        await self.session.commit()
        await self.session.refresh(flag)

        logger.info("Created feature flag: %s", flag.key)
        return flag

    async def get_by_key(self, key: str) -> FeatureFlag | None:
        """Get a feature flag by key.

        Args:
            key: Flag key.

        Returns:
            Feature flag if found.
        """
        stmt = select(FeatureFlag).where(FeatureFlag.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, flag_id: UUID) -> FeatureFlag | None:
        """Get a feature flag by ID.

        Args:
            flag_id: Flag UUID.

        Returns:
            Feature flag if found.
        """
        stmt = select(FeatureFlag).where(FeatureFlag.id == flag_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_flags(
        self,
        status: FlagStatus | None = None,
        enabled: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> FeatureFlagListResponse:
        """List feature flags with optional filters.

        Args:
            status: Filter by status.
            enabled: Filter by enabled state.
            limit: Maximum flags to return.
            offset: Number to skip.

        Returns:
            Paginated list of flags.
        """
        stmt = select(FeatureFlag)

        if status:
            stmt = stmt.where(FeatureFlag.status == status.value)
        if enabled is not None:
            stmt = stmt.where(FeatureFlag.enabled == enabled)

        # Get total count
        count_stmt = select(FeatureFlag.id)
        if status:
            count_stmt = count_stmt.where(FeatureFlag.status == status.value)
        if enabled is not None:
            count_stmt = count_stmt.where(FeatureFlag.enabled == enabled)
        count_result = await self.session.execute(count_stmt)
        total = len(count_result.all())

        # Get paginated results
        stmt = stmt.order_by(FeatureFlag.key).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        flags = result.scalars().all()

        return FeatureFlagListResponse(
            items=[FeatureFlagResponse.model_validate(f) for f in flags],
            total=total,
        )

    async def update(self, key: str, data: FeatureFlagUpdate) -> FeatureFlag | None:
        """Update a feature flag.

        Args:
            key: Flag key.
            data: Update data.

        Returns:
            Updated flag or None if not found.
        """
        flag = await self.get_by_key(key)
        if not flag:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # Handle targeting rules specially
        if update_data.get("targeting_rules"):
            update_data["targeting_rules"] = [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in update_data["targeting_rules"]
            ]

        for field, value in update_data.items():
            if field == "status" and value:
                value = value.value if hasattr(value, "value") else value
            setattr(flag, field, value)

        await self.session.commit()
        await self.session.refresh(flag)

        logger.info("Updated feature flag: %s", flag.key)
        return flag

    async def delete(self, key: str) -> bool:
        """Delete a feature flag.

        Args:
            key: Flag key.

        Returns:
            True if deleted.
        """
        flag = await self.get_by_key(key)
        if not flag:
            return False

        # Delete associated overrides
        await self.session.execute(
            delete(FlagOverride).where(FlagOverride.flag_key == key)
        )

        await self.session.delete(flag)
        await self.session.commit()

        logger.info("Deleted feature flag: %s", key)
        return True

    async def create_override(self, data: FlagOverrideCreate) -> FlagOverride:
        """Create a flag override for a user or tenant.

        Args:
            data: Override creation data.

        Returns:
            Created override.
        """
        # Check if override already exists
        stmt = select(FlagOverride).where(
            FlagOverride.flag_key == data.flag_key,
            FlagOverride.entity_type == data.entity_type,
            FlagOverride.entity_id == data.entity_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing override
            existing.enabled = data.enabled
            existing.reason = data.reason
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        override = FlagOverride(
            flag_key=data.flag_key,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            enabled=data.enabled,
            reason=data.reason,
        )

        self.session.add(override)
        await self.session.commit()
        await self.session.refresh(override)

        logger.info(
            "Created flag override: %s for %s:%s",
            data.flag_key,
            data.entity_type,
            data.entity_id,
        )
        return override

    async def delete_override(
        self,
        flag_key: str,
        entity_type: str,
        entity_id: str,
    ) -> bool:
        """Delete a flag override.

        Args:
            flag_key: Flag key.
            entity_type: Entity type.
            entity_id: Entity ID.

        Returns:
            True if deleted.
        """
        stmt = delete(FlagOverride).where(
            FlagOverride.flag_key == flag_key,
            FlagOverride.entity_type == entity_type,
            FlagOverride.entity_id == entity_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()

        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def get_overrides(
        self,
        flag_key: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[FlagOverride]:
        """Get flag overrides with optional filters.

        Args:
            flag_key: Filter by flag key.
            entity_type: Filter by entity type.
            entity_id: Filter by entity ID.

        Returns:
            List of matching overrides.
        """
        stmt = select(FlagOverride)

        if flag_key:
            stmt = stmt.where(FlagOverride.flag_key == flag_key)
        if entity_type:
            stmt = stmt.where(FlagOverride.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(FlagOverride.entity_id == entity_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def evaluate(
        self,
        context: FlagEvaluationRequest,
        flag_keys: list[str] | None = None,
        include_details: bool = False,
    ) -> FlagEvaluationResponse:
        """Evaluate feature flags for a given context.

        Args:
            context: Evaluation context (user, tenant, attributes).
            flag_keys: Specific flags to evaluate (all if None).
            include_details: Include detailed evaluation reasons.

        Returns:
            Evaluated flag values.
        """
        # Get all flags or specific ones
        stmt = select(FeatureFlag)
        if flag_keys:
            stmt = stmt.where(FeatureFlag.key.in_(flag_keys))
        result = await self.session.execute(stmt)
        flags = result.scalars().all()

        # Get applicable overrides
        overrides: dict[str, bool] = {}
        if context.user_id or context.tenant_id:
            override_stmt = select(FlagOverride)
            conditions = []
            if context.user_id:
                conditions.append(
                    (FlagOverride.entity_type == "user")
                    & (FlagOverride.entity_id == context.user_id)
                )
            if context.tenant_id:
                conditions.append(
                    (FlagOverride.entity_type == "tenant")
                    & (FlagOverride.entity_id == context.tenant_id)
                )

            if conditions:
                from sqlalchemy import or_

                override_stmt = override_stmt.where(or_(*conditions))
                override_result = await self.session.execute(override_stmt)
                for override in override_result.scalars():
                    overrides[override.flag_key] = override.enabled

        # Evaluate each flag
        evaluated: dict[str, bool] = {}
        details: list[FlagEvaluationResult] = []
        now = datetime.now(UTC)

        for flag in flags:
            enabled, reason = self._evaluate_flag(flag, context, overrides, now)
            evaluated[flag.key] = enabled

            if include_details:
                details.append(
                    FlagEvaluationResult(key=flag.key, enabled=enabled, reason=reason)
                )

        return FlagEvaluationResponse(
            flags=evaluated,
            details=details if include_details else None,
        )

    async def is_enabled(
        self,
        key: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        default: bool = False,
    ) -> bool:
        """Check if a specific flag is enabled.

        Convenience method for checking a single flag.

        Args:
            key: Flag key.
            user_id: User ID for context.
            tenant_id: Tenant ID for context.
            attributes: Additional attributes.
            default: Default value if flag not found.

        Returns:
            True if flag is enabled.
        """
        context = FlagEvaluationRequest(
            user_id=user_id,
            tenant_id=tenant_id,
            attributes=attributes,
        )

        result = await self.evaluate(context, flag_keys=[key])
        return result.flags.get(key, default)

    def _evaluate_flag(
        self,
        flag: FeatureFlag,
        context: FlagEvaluationRequest,
        overrides: dict[str, bool],
        now: datetime,
    ) -> tuple[bool, str]:
        """Evaluate a single flag.

        Args:
            flag: Feature flag to evaluate.
            context: Evaluation context.
            overrides: Override values.
            now: Current time.

        Returns:
            Tuple of (enabled, reason).
        """
        # Check for override first
        if flag.key in overrides:
            return overrides[flag.key], "override"

        # Check time constraints
        if not flag.is_active(now):
            return False, "time_constraint"

        # Check status
        if flag.status == FlagStatus.DISABLED.value:
            return False, "disabled"

        if flag.status == FlagStatus.ENABLED.value:
            return flag.enabled, "global"

        if flag.status == FlagStatus.PERCENTAGE.value:
            # Percentage-based rollout using consistent hashing
            if not context.user_id and not context.tenant_id:
                # No identity, use random-ish behavior based on request
                return False, "no_identity_for_percentage"

            identity = context.user_id or context.tenant_id
            bucket = self._get_percentage_bucket(flag.key, identity)  # type: ignore
            enabled = bucket < flag.percentage
            return enabled, f"percentage_{flag.percentage}"

        if flag.status == FlagStatus.TARGETED.value:
            # Evaluate targeting rules
            if flag.targeting_rules:
                for rule in flag.targeting_rules:
                    if self._matches_rule(rule, context):  # type: ignore
                        return True, f"targeting_rule_{rule.get('type')}"  # type: ignore
            return False, "no_matching_rule"

        return False, "unknown_status"

    def _get_percentage_bucket(self, flag_key: str, identity: str) -> int:
        """Get a consistent bucket (0-99) for percentage rollout.

        Uses consistent hashing so the same user always gets the same result.

        Args:
            flag_key: Flag key.
            identity: User or tenant ID.

        Returns:
            Bucket number 0-99.
        """
        hash_input = f"{flag_key}:{identity}".encode()
        # MD5 used for non-cryptographic consistent hashing (bucketing)
        hash_value = hashlib.md5(hash_input).hexdigest()  # noqa: S324
        return int(hash_value[:8], 16) % 100

    def _matches_rule(
        self,
        rule: dict[str, Any],
        context: FlagEvaluationRequest,
    ) -> bool:
        """Check if a targeting rule matches the context.

        Args:
            rule: Targeting rule configuration.
            context: Evaluation context.

        Returns:
            True if rule matches.
        """
        rule_type = rule.get("type")
        operator = rule.get("operator", "eq")
        value = rule.get("value")

        if rule_type == "user_id":
            return self._compare(context.user_id, operator, value)

        if rule_type == "tenant_id":
            return self._compare(context.tenant_id, operator, value)

        if rule_type == "attribute":
            attribute = rule.get("attribute")
            if attribute and context.attributes:
                attr_value = context.attributes.get(attribute)
                return self._compare(attr_value, operator, value)

        return False

    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        """Compare values using the specified operator.

        Args:
            actual: Actual value.
            operator: Comparison operator.
            expected: Expected value.

        Returns:
            True if comparison matches.
        """
        if actual is None:
            return False

        if operator == "eq":
            return actual == expected  # type: ignore[no-any-return]
        if operator == "neq":
            return actual != expected  # type: ignore[no-any-return]
        if operator == "in":
            return actual in (expected if isinstance(expected, list) else [expected])
        if operator == "not_in":
            return actual not in (
                expected if isinstance(expected, list) else [expected]
            )
        if operator == "contains":
            return expected in str(actual)
        if operator == "starts_with":
            return str(actual).startswith(str(expected))
        if operator == "ends_with":
            return str(actual).endswith(str(expected))
        if operator == "gt":
            return actual > expected  # type: ignore[no-any-return]
        if operator == "gte":
            return actual >= expected  # type: ignore[no-any-return]
        if operator == "lt":
            return actual < expected  # type: ignore[no-any-return]
        if operator == "lte":
            return actual <= expected  # type: ignore[no-any-return]

        return False


async def get_feature_flag_service(session: AsyncSession) -> FeatureFlagService:
    """Get a feature flag service instance.

    Args:
        session: Database session.

    Returns:
        FeatureFlagService instance.
    """
    return FeatureFlagService(session)
