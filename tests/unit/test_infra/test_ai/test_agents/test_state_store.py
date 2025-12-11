"""Tests for the AI agent state store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from example_service.infra.ai.agents.state_store import (
    BaseStateStore,
    InMemoryStateStore,
    ScopedStateStore,
    StateEntry,
    StateKey,
    configure_state_store,
    get_state_store,
    reset_state_store,
)


class TestStateKey:
    """Tests for StateKey."""

    def test_create_state_key(self) -> None:
        """Test creating a state key."""
        key = StateKey(
            tenant_id="tenant-123",
            namespace="agent",
            key="cache",
        )

        assert key.tenant_id == "tenant-123"
        assert key.namespace == "agent"
        assert key.key == "cache"
        assert key.version == "v1"

    def test_state_key_str(self) -> None:
        """Test string representation."""
        key = StateKey(
            tenant_id="t1",
            namespace="ns",
            key="k",
            version="v2",
        )

        assert str(key) == "t1:ns:k:v2"

    def test_state_key_to_redis_key(self) -> None:
        """Test Redis key format."""
        key = StateKey(
            tenant_id="t1",
            namespace="ns",
            key="k",
        )

        assert key.to_redis_key() == "ai:state:t1:ns:k:v1"

    def test_state_key_to_dict(self) -> None:
        """Test conversion to dict."""
        key = StateKey(
            tenant_id="t1",
            namespace="ns",
            key="k",
        )

        d = key.to_dict()

        assert d["tenant_id"] == "t1"
        assert d["namespace"] == "ns"
        assert d["key"] == "k"
        assert d["version"] == "v1"

    def test_state_key_from_dict(self) -> None:
        """Test creating from dict."""
        data = {
            "tenant_id": "t1",
            "namespace": "ns",
            "key": "k",
            "version": "v2",
        }

        key = StateKey.from_dict(data)

        assert key.tenant_id == "t1"
        assert key.version == "v2"

    def test_state_key_from_string(self) -> None:
        """Test parsing from string."""
        key = StateKey.from_string("t1:ns:k:v2")

        assert key.tenant_id == "t1"
        assert key.namespace == "ns"
        assert key.key == "k"
        assert key.version == "v2"

    def test_state_key_from_string_default_version(self) -> None:
        """Test parsing with default version."""
        key = StateKey.from_string("t1:ns:k")

        assert key.version == "v1"

    def test_state_key_from_string_invalid(self) -> None:
        """Test invalid string raises error."""
        with pytest.raises(ValueError, match="Invalid state key format"):
            StateKey.from_string("invalid")


class TestStateEntry:
    """Tests for StateEntry."""

    def test_create_entry(self) -> None:
        """Test creating an entry."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        entry = StateEntry(
            key=key,
            value={"data": "test"},
        )

        assert entry.key == key
        assert entry.value == {"data": "test"}
        assert entry.created_at is not None
        assert entry.expires_at is None

    def test_entry_not_expired(self) -> None:
        """Test entry without expiry is not expired."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        entry = StateEntry(key=key, value="test")

        assert entry.is_expired is False

    def test_entry_expired(self) -> None:
        """Test expired entry detection."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        entry = StateEntry(
            key=key,
            value="test",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        assert entry.is_expired is True

    def test_entry_not_yet_expired(self) -> None:
        """Test entry not yet expired."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        entry = StateEntry(
            key=key,
            value="test",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        assert entry.is_expired is False

    def test_entry_to_dict(self) -> None:
        """Test serialization."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        entry = StateEntry(
            key=key,
            value={"data": 123},
            metadata={"source": "test"},
        )

        d = entry.to_dict()

        assert d["value"] == {"data": 123}
        assert d["metadata"]["source"] == "test"
        assert "created_at" in d

    def test_entry_from_dict(self) -> None:
        """Test deserialization."""
        data = {
            "key": {
                "tenant_id": "t1",
                "namespace": "ns",
                "key": "k",
                "version": "v1",
            },
            "value": {"data": 123},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "metadata": {},
        }

        entry = StateEntry.from_dict(data)

        assert entry.key.tenant_id == "t1"
        assert entry.value == {"data": 123}


class TestInMemoryStateStore:
    """Tests for InMemoryStateStore."""

    @pytest.fixture
    def store(self) -> InMemoryStateStore:
        """Create a fresh store for each test."""
        return InMemoryStateStore()

    @pytest.mark.anyio
    async def test_set_and_get(self, store: InMemoryStateStore) -> None:
        """Test basic set and get."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")

        await store.set(key, {"data": "test"})
        value = await store.get(key)

        assert value == {"data": "test"}

    @pytest.mark.anyio
    async def test_get_missing_key(self, store: InMemoryStateStore) -> None:
        """Test getting non-existent key."""
        key = StateKey(tenant_id="t1", namespace="ns", key="missing")

        value = await store.get(key)

        assert value is None

    @pytest.mark.anyio
    async def test_set_with_ttl(self, store: InMemoryStateStore) -> None:
        """Test setting with TTL."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")

        await store.set(key, "value", ttl_seconds=3600)
        value = await store.get(key)

        assert value == "value"

    @pytest.mark.anyio
    async def test_expired_value_not_returned(self, store: InMemoryStateStore) -> None:
        """Test that expired values are not returned."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")

        # Manually create expired entry
        store._store[str(key)] = StateEntry(
            key=key,
            value="expired",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        value = await store.get(key)

        assert value is None
        assert str(key) not in store._store

    @pytest.mark.anyio
    async def test_delete(self, store: InMemoryStateStore) -> None:
        """Test deleting a key."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        await store.set(key, "value")

        deleted = await store.delete(key)

        assert deleted is True
        assert await store.get(key) is None

    @pytest.mark.anyio
    async def test_delete_missing(self, store: InMemoryStateStore) -> None:
        """Test deleting non-existent key."""
        key = StateKey(tenant_id="t1", namespace="ns", key="missing")

        deleted = await store.delete(key)

        assert deleted is False

    @pytest.mark.anyio
    async def test_exists(self, store: InMemoryStateStore) -> None:
        """Test checking if key exists."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")

        assert await store.exists(key) is False

        await store.set(key, "value")

        assert await store.exists(key) is True

    @pytest.mark.anyio
    async def test_exists_expired(self, store: InMemoryStateStore) -> None:
        """Test exists returns False for expired keys."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")

        # Manually create expired entry
        store._store[str(key)] = StateEntry(
            key=key,
            value="expired",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        assert await store.exists(key) is False

    @pytest.mark.anyio
    async def test_list_keys(self, store: InMemoryStateStore) -> None:
        """Test listing keys."""
        await store.set(
            StateKey(tenant_id="t1", namespace="ns1", key="k1"),
            "v1",
        )
        await store.set(
            StateKey(tenant_id="t1", namespace="ns1", key="k2"),
            "v2",
        )
        await store.set(
            StateKey(tenant_id="t1", namespace="ns2", key="k3"),
            "v3",
        )
        await store.set(
            StateKey(tenant_id="t2", namespace="ns1", key="k4"),
            "v4",
        )

        # List by tenant
        keys = await store.list_keys("t1")
        assert len(keys) == 3

        # List by tenant and namespace
        keys = await store.list_keys("t1", namespace="ns1")
        assert len(keys) == 2

        # List by pattern
        keys = await store.list_keys("t1", pattern="k1")
        assert len(keys) == 1

    @pytest.mark.anyio
    async def test_clear_namespace(self, store: InMemoryStateStore) -> None:
        """Test clearing a namespace."""
        await store.set(
            StateKey(tenant_id="t1", namespace="ns1", key="k1"),
            "v1",
        )
        await store.set(
            StateKey(tenant_id="t1", namespace="ns1", key="k2"),
            "v2",
        )
        await store.set(
            StateKey(tenant_id="t1", namespace="ns2", key="k3"),
            "v3",
        )

        count = await store.clear_namespace("t1", "ns1")

        assert count == 2
        assert await store.exists(StateKey(tenant_id="t1", namespace="ns1", key="k1")) is False
        assert await store.exists(StateKey(tenant_id="t1", namespace="ns2", key="k3")) is True

    @pytest.mark.anyio
    async def test_get_or_set(self, store: InMemoryStateStore) -> None:
        """Test get_or_set behavior."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")
        call_count = 0

        def factory() -> str:
            nonlocal call_count
            call_count += 1
            return "computed"

        # First call should compute
        value = await store.get_or_set(key, factory)
        assert value == "computed"
        assert call_count == 1

        # Second call should return cached
        value = await store.get_or_set(key, factory)
        assert value == "computed"
        assert call_count == 1

    @pytest.mark.anyio
    async def test_get_or_set_async_factory(self, store: InMemoryStateStore) -> None:
        """Test get_or_set with async factory."""
        key = StateKey(tenant_id="t1", namespace="ns", key="k")

        async def async_factory() -> str:
            return "async_computed"

        value = await store.get_or_set(key, async_factory)
        assert value == "async_computed"

    @pytest.mark.anyio
    async def test_increment(self, store: InMemoryStateStore) -> None:
        """Test incrementing values."""
        key = StateKey(tenant_id="t1", namespace="ns", key="counter")

        # Increment new key
        value = await store.increment(key)
        assert value == 1

        # Increment existing key
        value = await store.increment(key, amount=5)
        assert value == 6

    def test_clear_all(self, store: InMemoryStateStore) -> None:
        """Test clearing entire store."""
        store._store["test"] = StateEntry(
            key=StateKey(tenant_id="t1", namespace="ns", key="k"),
            value="test",
        )

        store.clear_all()

        assert len(store._store) == 0


class TestScopedStateStore:
    """Tests for ScopedStateStore."""

    @pytest.fixture
    def store(self) -> InMemoryStateStore:
        """Create base store."""
        return InMemoryStateStore()

    @pytest.fixture
    def scoped(self, store: InMemoryStateStore) -> ScopedStateStore:
        """Create scoped store."""
        return ScopedStateStore(
            store=store,
            tenant_id="tenant-123",
            namespace="my_agent",
            default_ttl=3600,
        )

    @pytest.mark.anyio
    async def test_set_and_get(self, scoped: ScopedStateStore) -> None:
        """Test basic set and get with scoped store."""
        await scoped.set("cache", {"results": [1, 2, 3]})
        value = await scoped.get("cache")

        assert value == {"results": [1, 2, 3]}

    @pytest.mark.anyio
    async def test_uses_default_ttl(
        self, store: InMemoryStateStore, scoped: ScopedStateStore,
    ) -> None:
        """Test that default TTL is used."""
        await scoped.set("key", "value")

        # Check the underlying entry has TTL
        key = StateKey(
            tenant_id="tenant-123",
            namespace="my_agent",
            key="key",
        )
        entry = store._store[str(key)]
        assert entry.expires_at is not None

    @pytest.mark.anyio
    async def test_custom_ttl_overrides_default(
        self, store: InMemoryStateStore, scoped: ScopedStateStore,
    ) -> None:
        """Test custom TTL overrides default."""
        await scoped.set("key", "value", ttl_seconds=60)

        key = StateKey(
            tenant_id="tenant-123",
            namespace="my_agent",
            key="key",
        )
        entry = store._store[str(key)]
        # Should expire much sooner than default 3600
        assert entry.expires_at is not None
        delta = entry.expires_at - datetime.now(UTC)
        assert delta.total_seconds() <= 60

    @pytest.mark.anyio
    async def test_delete(self, scoped: ScopedStateStore) -> None:
        """Test deleting with scoped store."""
        await scoped.set("key", "value")
        deleted = await scoped.delete("key")

        assert deleted is True
        assert await scoped.get("key") is None

    @pytest.mark.anyio
    async def test_exists(self, scoped: ScopedStateStore) -> None:
        """Test exists with scoped store."""
        assert await scoped.exists("key") is False

        await scoped.set("key", "value")

        assert await scoped.exists("key") is True

    @pytest.mark.anyio
    async def test_list_keys(self, scoped: ScopedStateStore) -> None:
        """Test listing keys in scope."""
        await scoped.set("key1", "v1")
        await scoped.set("key2", "v2")

        keys = await scoped.list_keys()

        assert len(keys) == 2
        assert "key1" in keys
        assert "key2" in keys

    @pytest.mark.anyio
    async def test_list_keys_with_pattern(self, scoped: ScopedStateStore) -> None:
        """Test listing keys with pattern."""
        await scoped.set("cache_1", "v1")
        await scoped.set("cache_2", "v2")
        await scoped.set("other", "v3")

        keys = await scoped.list_keys(pattern="cache")

        assert len(keys) == 2

    @pytest.mark.anyio
    async def test_clear(self, scoped: ScopedStateStore) -> None:
        """Test clearing scope."""
        await scoped.set("key1", "v1")
        await scoped.set("key2", "v2")

        count = await scoped.clear()

        assert count == 2
        assert await scoped.list_keys() == []

    @pytest.mark.anyio
    async def test_versioned_keys(self, scoped: ScopedStateStore) -> None:
        """Test versioned keys."""
        await scoped.set("key", "v1_value", version="v1")
        await scoped.set("key", "v2_value", version="v2")

        v1 = await scoped.get("key", version="v1")
        v2 = await scoped.get("key", version="v2")

        assert v1 == "v1_value"
        assert v2 == "v2_value"


class TestGlobalStateStore:
    """Tests for global state store management."""

    def setup_method(self) -> None:
        """Reset global store before each test."""
        reset_state_store()

    def test_get_default_store(self) -> None:
        """Test getting default in-memory store."""
        store = get_state_store()

        assert isinstance(store, InMemoryStateStore)

    def test_get_same_store(self) -> None:
        """Test getting same store instance."""
        store1 = get_state_store()
        store2 = get_state_store()

        assert store1 is store2

    def test_configure_store(self) -> None:
        """Test configuring custom store."""
        custom_store = InMemoryStateStore()
        configure_state_store(custom_store)

        store = get_state_store()

        assert store is custom_store

    def test_reset_store(self) -> None:
        """Test resetting to default."""
        custom_store = InMemoryStateStore()
        configure_state_store(custom_store)

        reset_state_store()

        store = get_state_store()
        assert store is not custom_store
