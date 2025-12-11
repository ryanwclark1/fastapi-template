"""Tests for auth client dependency factory."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from example_service.core.dependencies import auth_client as module


@pytest.fixture(autouse=True)
def _clear_cache():
    module.get_auth_client.cache_clear()
    yield
    module.get_auth_client.cache_clear()


def test_is_running_internally_true(monkeypatch: pytest.MonkeyPatch):
    settings = SimpleNamespace(service_name="accent-auth")
    monkeypatch.setattr("example_service.core.dependencies.auth_client.get_app_settings", lambda: settings)

    assert module._is_running_internally() is True


def test_is_running_internally_handles_error(monkeypatch: pytest.MonkeyPatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr("example_service.core.dependencies.auth_client.get_app_settings", _boom)

    assert module._is_running_internally() is False


def test_internal_client_created(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(module, "_is_running_internally", lambda: True)
    mock_client = object()
    monkeypatch.setattr("example_service.infra.auth.db_client.DatabaseAuthClient", lambda: mock_client)

    assert module.get_auth_client() is mock_client


def test_external_client_missing_library(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(module, "_is_running_internally", lambda: False)
    monkeypatch.setattr("example_service.infra.auth.http_client.ACCENT_AUTH_CLIENT_AVAILABLE", False)

    with pytest.raises(RuntimeError):
        module.get_auth_client()


def test_external_client_requires_service_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(module, "_is_running_internally", lambda: False)
    monkeypatch.setattr("example_service.infra.auth.http_client.ACCENT_AUTH_CLIENT_AVAILABLE", True)
    monkeypatch.setattr("example_service.infra.auth.http_client.HttpAuthClient", lambda **_: object())
    settings = SimpleNamespace(service_url=None, request_timeout=5.0, verify_ssl=True)
    monkeypatch.setattr(module, "get_auth_settings", lambda: settings)

    with pytest.raises(ValueError):
        module.get_auth_client()


def test_external_client_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(module, "_is_running_internally", lambda: False)
    monkeypatch.setattr("example_service.infra.auth.http_client.ACCENT_AUTH_CLIENT_AVAILABLE", True)
    created_clients: list[dict] = []

    def _mock_http_client(**kwargs):
        created_clients.append(kwargs)
        return SimpleNamespace(mode="http")

    monkeypatch.setattr("example_service.infra.auth.http_client.HttpAuthClient", _mock_http_client)
    settings = SimpleNamespace(service_url="https://auth", request_timeout=3.5, verify_ssl=False)
    monkeypatch.setattr(module, "get_auth_settings", lambda: settings)

    client = module.get_auth_client()
    assert client.mode == "http"
    assert created_clients[0] == {"timeout": 3.5, "verify_certificate": False}
