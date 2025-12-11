"""Tests for ACL utility helpers."""

from types import SimpleNamespace

from fastapi import HTTPException, status
import pytest

from example_service.core.utils.acl import (
    require_any_permission,
    require_owner_or_admin,
    require_permission,
)


class FakeUser(SimpleNamespace):
    """Simple helper object mimicking AuthUser interface."""

    permissions: list[str]
    user_id: str

    def has_acl(self, acl: str) -> bool:  # pragma: no cover - exercised via wrapper methods
        return acl in self.permissions

    def has_any_acl(self, *acls: str) -> bool:
        return any(self.has_acl(acl) for acl in acls)


class TestRequirePermission:
    """Tests for require_permission."""

    def test_allows_user_with_permission(self) -> None:
        user = FakeUser(permissions=["reports.read"], user_id="user-1")
        require_permission(user, "reports.read", "/reports")

    def test_raises_when_missing_permission(self) -> None:
        user = FakeUser(permissions=["reports.read"], user_id="user-1")

        with pytest.raises(HTTPException) as exc:
            require_permission(user, "reports.delete", "/reports/1")

        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc.value.detail["required_acl"] == "reports.delete"
        assert exc.value.detail["instance"] == "/reports/1"


class TestRequireAnyPermission:
    """Tests for require_any_permission."""

    def test_allows_when_any_match(self) -> None:
        user = FakeUser(permissions=["reports.read"], user_id="user-2")
        require_any_permission(user, ["reports.read", "admin.#"], "/reports")

    def test_raises_when_none_match(self) -> None:
        user = FakeUser(permissions=["reports.read"], user_id="user-2")
        with pytest.raises(HTTPException) as exc:
            require_any_permission(user, ["reports.write", "admin.#"], "/reports")

        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc.value.detail["required_acls"] == ["reports.write", "admin.#"]


class TestRequireOwnerOrAdmin:
    """Tests for require_owner_or_admin."""

    def test_allows_owner(self) -> None:
        user = FakeUser(permissions=[], user_id="user-3")
        require_owner_or_admin(user, resource_owner_id="user-3", admin_acl="admin.#", request_path="/users/3")

    def test_allows_admin(self) -> None:
        user = FakeUser(permissions=["admin.#"], user_id="user-4")
        require_owner_or_admin(user, resource_owner_id="user-5", admin_acl="admin.#", request_path="/users/5")

    def test_raises_when_neither_owner_nor_admin(self) -> None:
        user = FakeUser(permissions=["reports.read"], user_id="user-6")
        with pytest.raises(HTTPException) as exc:
            require_owner_or_admin(user, resource_owner_id="user-7", admin_acl="admin.#", request_path="/users/7")

        detail = exc.value.detail
        assert detail["resource_owner_id"] == "user-7"
        assert detail["user_id"] == "user-6"
        assert detail["admin_acl"] == "admin.#"
