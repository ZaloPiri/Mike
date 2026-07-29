import uuid
from datetime import timedelta

import pytest

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.event import Event
from mike_app.runtime.episode_store import InMemoryEpisodeStore


def test_add_and_retrieve_by_id() -> None:
    store = InMemoryEpisodeStore()
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))

    store.add(episode)

    assert store.get_by_id("tenant-1", episode.episode_id) is episode


def test_listing_preserves_insertion_order() -> None:
    store = InMemoryEpisodeStore()
    first = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    second = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.two"))

    store.add(first)
    store.add(second)

    assert store.list_for_tenant("tenant-1") == (first, second)


def test_tenant_isolation_by_id() -> None:
    store = InMemoryEpisodeStore()
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))

    store.add(episode)

    assert store.get_by_id("tenant-2", episode.episode_id) is None


def test_tenant_isolation_in_listing() -> None:
    store = InMemoryEpisodeStore()
    tenant_one_episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    tenant_two_episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-2", event_type="test.event.two"))

    store.add(tenant_one_episode)
    store.add(tenant_two_episode)

    assert store.list_for_tenant("tenant-1") == (tenant_one_episode,)
    assert store.list_for_tenant("tenant-2") == (tenant_two_episode,)


def test_tenant_count_and_total_count() -> None:
    store = InMemoryEpisodeStore()
    first = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    second = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.two"))
    third = CognitiveEpisode.create(Event.create(tenant_id="tenant-2", event_type="test.event.three"))

    store.add(first)
    store.add(second)
    store.add(third)

    assert store.count_for_tenant("tenant-1") == 2
    assert store.count_for_tenant("tenant-2") == 1
    assert store.total_count() == 3


def test_duplicate_add_rejected() -> None:
    store = InMemoryEpisodeStore()
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))

    store.add(episode)

    with pytest.raises(ValueError, match="already exists"):
        store.add(episode)


def test_non_episode_add_rejected() -> None:
    store = InMemoryEpisodeStore()

    with pytest.raises(TypeError, match="CognitiveEpisode"):
        store.add(object())


def test_non_episode_update_rejected() -> None:
    store = InMemoryEpisodeStore()

    with pytest.raises(TypeError, match="CognitiveEpisode"):
        store.update(object())


def test_update_replaces_stored_episode() -> None:
    store = InMemoryEpisodeStore()
    original = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    store.add(original)

    updated = CognitiveEpisode(
        episode_id=original.episode_id,
        tenant_id=original.tenant_id,
        created_at=original.created_at,
        updated_at=original.updated_at + timedelta(minutes=1),
        event_ids=original.event_ids + (uuid.uuid4(),),
        correlation_id=original.correlation_id,
        schema_version=original.schema_version,
    )
    store.update(updated)

    assert store.get_by_id("tenant-1", original.episode_id) is updated


def test_update_accepts_equal_updated_at_timestamp() -> None:
    store = InMemoryEpisodeStore()
    original = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    store.add(original)

    updated = CognitiveEpisode(
        episode_id=original.episode_id,
        tenant_id=original.tenant_id,
        created_at=original.created_at,
        updated_at=original.updated_at,
        event_ids=original.event_ids,
        correlation_id=original.correlation_id,
        schema_version=original.schema_version,
    )
    store.update(updated)

    assert store.get_by_id("tenant-1", original.episode_id) is updated


def test_update_preserves_insertion_order() -> None:
    store = InMemoryEpisodeStore()
    first = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    second = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.two"))
    store.add(first)
    store.add(second)

    updated_second = CognitiveEpisode(
        episode_id=second.episode_id,
        tenant_id=second.tenant_id,
        created_at=second.created_at,
        updated_at=second.updated_at + timedelta(minutes=1),
        event_ids=second.event_ids,
        correlation_id=second.correlation_id,
        schema_version=second.schema_version,
    )
    store.update(updated_second)

    assert store.list_for_tenant("tenant-1") == (first, updated_second)


def test_update_unknown_episode_rejected() -> None:
    store = InMemoryEpisodeStore()
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))

    with pytest.raises(ValueError, match="does not exist"):
        store.update(episode)


def test_update_with_changed_tenant_rejected() -> None:
    store = InMemoryEpisodeStore()
    original = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))
    store.add(original)
    updated = CognitiveEpisode(
        episode_id=original.episode_id,
        tenant_id="tenant-2",
        created_at=original.created_at,
        updated_at=original.updated_at + timedelta(minutes=1),
        event_ids=original.event_ids,
        correlation_id=original.correlation_id,
        schema_version=original.schema_version,
    )

    with pytest.raises(ValueError, match="tenant"):
        store.update(updated)


def test_update_with_changed_created_at_rejected() -> None:
    store = InMemoryEpisodeStore()
    original = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))
    store.add(original)
    updated = CognitiveEpisode(
        episode_id=original.episode_id,
        tenant_id=original.tenant_id,
        created_at=original.created_at + timedelta(minutes=1),
        updated_at=original.updated_at + timedelta(minutes=1),
        event_ids=original.event_ids,
        correlation_id=original.correlation_id,
        schema_version=original.schema_version,
    )

    with pytest.raises(ValueError, match="created_at"):
        store.update(updated)


def test_update_with_earlier_updated_at_rejected() -> None:
    store = InMemoryEpisodeStore()
    original = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))
    store.add(original)

    invalid_updated = object.__new__(CognitiveEpisode)
    object.__setattr__(invalid_updated, "episode_id", original.episode_id)
    object.__setattr__(invalid_updated, "tenant_id", original.tenant_id)
    object.__setattr__(invalid_updated, "created_at", original.created_at)
    object.__setattr__(invalid_updated, "updated_at", original.updated_at - timedelta(minutes=1))
    object.__setattr__(invalid_updated, "event_ids", original.event_ids)
    object.__setattr__(invalid_updated, "correlation_id", original.correlation_id)
    object.__setattr__(invalid_updated, "schema_version", original.schema_version)

    with pytest.raises(ValueError, match="updated_at"):
        store.update(invalid_updated)


def test_empty_tenant_id_rejected() -> None:
    store = InMemoryEpisodeStore()

    with pytest.raises(ValueError, match="tenant_id"):
        store.get_by_id("", uuid.uuid4())


def test_whitespace_only_tenant_id_rejected() -> None:
    store = InMemoryEpisodeStore()

    with pytest.raises(ValueError, match="tenant_id"):
        store.list_for_tenant("   ")


def test_non_uuid_episode_id_rejected() -> None:
    store = InMemoryEpisodeStore()

    with pytest.raises(TypeError, match="uuid.UUID"):
        store.get_by_id("tenant-1", "not-a-uuid")


def test_unknown_episode_returns_none() -> None:
    store = InMemoryEpisodeStore()

    assert store.get_by_id("tenant-1", uuid.uuid4()) is None


def test_empty_tenant_returns_empty_tuple() -> None:
    store = InMemoryEpisodeStore()

    assert store.list_for_tenant("tenant-9") == ()


def test_returned_collection_cannot_mutate_store_state() -> None:
    store = InMemoryEpisodeStore()
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))
    store.add(episode)

    result = store.list_for_tenant("tenant-1")

    assert isinstance(result, tuple)
    with pytest.raises(AttributeError):
        result.append(CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event")))


def test_updating_one_tenant_does_not_affect_another_tenant() -> None:
    store = InMemoryEpisodeStore()
    tenant_one_episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    tenant_two_episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-2", event_type="test.event.two"))
    store.add(tenant_one_episode)
    store.add(tenant_two_episode)

    updated_tenant_one = CognitiveEpisode(
        episode_id=tenant_one_episode.episode_id,
        tenant_id=tenant_one_episode.tenant_id,
        created_at=tenant_one_episode.created_at,
        updated_at=tenant_one_episode.updated_at + timedelta(minutes=1),
        event_ids=tenant_one_episode.event_ids,
        correlation_id=tenant_one_episode.correlation_id,
        schema_version=tenant_one_episode.schema_version,
    )
    store.update(updated_tenant_one)

    assert store.list_for_tenant("tenant-1") == (updated_tenant_one,)
    assert store.list_for_tenant("tenant-2") == (tenant_two_episode,)
