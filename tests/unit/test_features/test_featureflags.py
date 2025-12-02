"""Unit tests for feature flag dependencies and service helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status
from starlette.requests import Request
from starlette.types import Scope

from example_service.features.featureflags import dependencies as deps
from example_service.features.featureflags.models import FlagStatus
from example_service.features.featureflags.schemas import (
    FlagEvaluationRequest,
    FlagEvaluationResponse,
)
from example_service.features.featureflags.service import FeatureFlagService


class DummyFlag:
    def __init__(
        self,
        *,
        key: str = "flag",
        status: str = FlagStatus.ENABLED.value,
        enabled: bool = True,
        percentage: int = 0,
        targeting_rules=None,
        active: bool = True,
    ):
        self.key = key
        self.status = status
        self.enabled = enabled
        self.percentage = percentage
        self.targeting_rules = targeting_rules
        self._active = active

    def is_active(self, now: datetime) -> bool:  # pragma: no cover - trivial
        return self._active


def _build_service() -> FeatureFlagService:
    return FeatureFlagService(session=MagicMock())


@pytest.mark.asyncio
async def test_feature_flags_is_enabled_and_get_all_uses_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    class StubService:
        def __init__(self, *_):
            pass

        async def is_enabled(self, *, key: str, **kwargs):
            calls.append((key, kwargs))
            return True

        async def evaluate(self, context: FlagEvaluationRequest, flag_keys=None):
            return FlagEvaluationResponse(flags={"a": True, "b": False})

    ff = deps.FeatureFlags(service=StubService(None))
    assert await ff.is_enabled("cool_feature", default=False) is True
    assert await ff.get_all() == {"a": True, "b": False}
    assert calls == [
        (
            "cool_feature",
            {"user_id": None, "tenant_id": None, "attributes": {}, "default": False},
        )
    ]


@pytest.mark.asyncio
async def test_get_feature_flags_builds_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_attrs: list[dict] = []

    class StubFeatureFlags(deps.FeatureFlags):
        def __init__(self, **kwargs):
            captured_attrs.append(kwargs)
            super().__init__(**kwargs)

    class StubService:
        def __init__(self, session):
            self.session = session

    monkeypatch.setattr(deps, "FeatureFlagService", StubService)
    monkeypatch.setattr(deps, "FeatureFlags", StubFeatureFlags)

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/resource",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    }
    request = Request(scope)
    request.state.user_id = "user-1"
    request.state.tenant_uuid = "tenant-9"
    request.state.user = SimpleNamespace(roles=["admin"], plan="pro")

    flags = await deps.get_feature_flags(request=request, session=MagicMock())

    assert flags.user_id == "user-1"
    assert flags.tenant_id == "tenant-9"
    assert flags.attributes["path"] == "/api/resource"
    assert flags.attributes["roles"] == ["admin"]
    assert captured_attrs[0]["service"].session  # session is passed through


@pytest.mark.asyncio
async def test_require_feature_blocks_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def disabled(*_, **__):
        return False

    flags = deps.FeatureFlags(service=MagicMock(is_enabled=disabled))
    dependency = deps.require_feature("beta-ui")

    with pytest.raises(HTTPException, match="beta-ui") as exc:
        await dependency(flags)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert "beta-ui" in str(exc.value.detail)


def test_compare_operator_variations() -> None:
    service = _build_service()
    assert service._compare("a", "eq", "a")
    assert service._compare("a", "neq", "b")
    assert service._compare("a", "in", ["a", "b"])
    assert not service._compare("a", "not_in", ["a"])
    assert service._compare("hello", "contains", "ell")
    assert service._compare("start", "starts_with", "st")
    assert service._compare("end", "ends_with", "nd")
    assert service._compare(5, "gt", 3)
    assert service._compare(5, "gte", 5)
    assert not service._compare(2, "lt", 1)


def test_matches_rule_handles_user_tenant_and_attributes() -> None:
    service = _build_service()
    context = FlagEvaluationRequest(user_id="u1", tenant_id="t1", attributes={"plan": "pro"})

    assert service._matches_rule({"type": "user_id", "operator": "eq", "value": "u1"}, context)
    assert service._matches_rule({"type": "tenant_id", "operator": "eq", "value": "t1"}, context)
    assert service._matches_rule(
        {"type": "attribute", "attribute": "plan", "operator": "eq", "value": "pro"}, context
    )
    assert not service._matches_rule({"type": "unknown"}, context)


def test_evaluate_flag_paths_cover_override_and_time_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service()
    context = FlagEvaluationRequest(user_id="user", tenant_id=None, attributes=None)

    flag = DummyFlag(status=FlagStatus.ENABLED.value, enabled=True)
    enabled, reason = service._evaluate_flag(flag, context, {"flag": False}, datetime.now(UTC))
    assert enabled is False
    assert reason == "override"

    flag = DummyFlag(status=FlagStatus.ENABLED.value, enabled=True, active=False)
    enabled, reason = service._evaluate_flag(flag, context, {}, datetime.now(UTC))
    assert (enabled, reason) == (False, "time_constraint")

    flag = DummyFlag(status=FlagStatus.DISABLED.value, enabled=True)
    enabled, reason = service._evaluate_flag(flag, context, {}, datetime.now(UTC))
    assert (enabled, reason) == (False, "disabled")


def test_percentage_based_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _build_service()
    context = FlagEvaluationRequest(user_id="user-9", tenant_id=None, attributes=None)
    flag = DummyFlag(status=FlagStatus.PERCENTAGE.value, percentage=30)

    monkeypatch.setattr(service, "_get_percentage_bucket", lambda *_: 10)
    assert service._evaluate_flag(flag, context, {}, datetime.now(UTC)) == (True, "percentage_30")

    monkeypatch.setattr(service, "_get_percentage_bucket", lambda *_: 90)
    assert service._evaluate_flag(flag, context, {}, datetime.now(UTC)) == (False, "percentage_30")


def test_targeted_rule_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _build_service()
    context = FlagEvaluationRequest(
        user_id=None, tenant_id=None, attributes={"role": "admin", "plan": "pro"}
    )
    flag = DummyFlag(
        status=FlagStatus.TARGETED.value,
        targeting_rules=[
            {"type": "attribute", "attribute": "role", "operator": "eq", "value": "admin"}
        ],
    )

    monkeypatch.setattr(service, "_matches_rule", lambda rule, ctx: rule["attribute"] == "role")
    assert service._evaluate_flag(flag, context, {}, datetime.now(UTC))[0] is True

    monkeypatch.setattr(service, "_matches_rule", lambda *_: False)
    assert service._evaluate_flag(flag, context, {}, datetime.now(UTC)) == (
        False,
        "no_matching_rule",
    )


def test_get_percentage_bucket_is_consistent() -> None:
    service = _build_service()
    bucket1 = service._get_percentage_bucket("flag", "identity")
    bucket2 = service._get_percentage_bucket("flag", "identity")
    assert 0 <= bucket1 < 100
    assert bucket1 == bucket2  # consistent hashing
