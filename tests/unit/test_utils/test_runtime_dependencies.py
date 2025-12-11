"""Tests for runtime dependency helper."""

from types import SimpleNamespace

from example_service.utils.runtime_dependencies import require_runtime_dependency


def test_require_runtime_dependency_tracks_objects():
    obj_a = SimpleNamespace(name="a")
    obj_b = SimpleNamespace(name="b")

    require_runtime_dependency(obj_a, None, obj_b)

    from example_service.utils import runtime_dependencies as module

    assert obj_a in module._RUNTIME_DEPENDENCIES  # type: ignore[attr-defined]
    assert obj_b in module._RUNTIME_DEPENDENCIES  # type: ignore[attr-defined]
