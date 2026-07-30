import uuid
from datetime import timedelta

import pytest

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore


def test_constructor_accepts_valid_stores() -> None:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()

    coordinator = EpisodeCoordinator(event_store, episode_store)

    assert coordinator._event_store is event_store
    assert coordinator._episode_store is episode_store


def test_constructor_rejects_invalid_event_store() -> None:
    with pytest.raises(TypeError, match="event_store"):
        EpisodeCoordinator(object(), InMemoryEpisodeStore())


def test_constructor_rejects_invalid_episode_store() -> None:
    with pytest.raises(TypeError, match="episode_store"):
        EpisodeCoordinator(InMemoryEventStore(), object())


def test_start_episode_creates_and_returns_episode() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = coordinator.start_episode(event)

    assert isinstance(episode, CognitiveEpisode)
    assert episode.tenant_id == "tenant-1"
    assert episode.event_ids == (event.event_id,)


def test_start_episode_stores_event_and_episode() -> None:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = coordinator.start_episode(event)

    assert event_store.get_by_id("tenant-1", event.event_id) is event
    assert episode_store.get_by_id("tenant-1", episode.episode_id) is episode


def test_start_episode_inherits_event_correlation_id_when_not_provided() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    event = Event.create(tenant_id="tenant-1", event_type="test.event", correlation_id="event-corr")

    episode = coordinator.start_episode(event)

    assert episode.correlation_id == "event-corr"


def test_start_episode_uses_explicit_correlation_id() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    event = Event.create(tenant_id="tenant-1", event_type="test.event", correlation_id="event-corr")

    episode = coordinator.start_episode(event, correlation_id="override-corr")

    assert episode.correlation_id == "override-corr"


def test_start_episode_rejects_non_event_input() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())

    with pytest.raises(TypeError, match="Event"):
        coordinator.start_episode(object())


def test_start_episode_does_not_mutate_event() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    original_payload = dict(event.payload)

    coordinator.start_episode(event)

    assert event.payload == original_payload


def test_append_to_episode_appends_event_and_updates_store() -> None:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    appended_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")

    updated_episode = coordinator.append_to_episode(episode.episode_id, appended_event)

    assert updated_episode.event_ids == (initial_event.event_id, appended_event.event_id)
    assert event_store.get_by_id("tenant-1", appended_event.event_id) is appended_event
    assert episode_store.get_by_id("tenant-1", episode.episode_id) is updated_episode


def test_append_to_episode_returns_new_episode_instance() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    appended_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")

    updated_episode = coordinator.append_to_episode(episode.episode_id, appended_event)

    assert updated_episode is not episode


def test_append_to_episode_leaves_original_episode_unchanged() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    appended_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")

    coordinator.append_to_episode(episode.episode_id, appended_event)

    assert episode.event_ids == (initial_event.event_id,)


def test_append_to_episode_preserves_episode_identity_and_metadata() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one", correlation_id="corr-1")
    episode = coordinator.start_episode(initial_event)
    appended_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")

    updated_episode = coordinator.append_to_episode(episode.episode_id, appended_event)

    assert updated_episode.episode_id == episode.episode_id
    assert updated_episode.created_at == episode.created_at
    assert updated_episode.correlation_id == episode.correlation_id
    assert updated_episode.schema_version == episode.schema_version


def test_append_to_episode_preserves_event_order() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    first_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(first_event)
    second_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")
    third_event = Event.create(tenant_id="tenant-1", event_type="test.event.three")

    updated_episode = coordinator.append_to_episode(episode.episode_id, second_event)
    updated_episode = coordinator.append_to_episode(episode.episode_id, third_event)

    assert updated_episode.event_ids == (first_event.event_id, second_event.event_id, third_event.event_id)


def test_append_to_episode_rejects_unknown_episode() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(ValueError, match="episode"):
        coordinator.append_to_episode(uuid.uuid4(), event)


def test_append_to_episode_rejects_cross_tenant_episode_access() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    cross_tenant_event = Event.create(tenant_id="tenant-2", event_type="test.event.two")

    with pytest.raises(ValueError, match="episode"):
        coordinator.append_to_episode(episode.episode_id, cross_tenant_event)


def test_cross_tenant_and_unknown_episode_errors_are_same() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    cross_tenant_event = Event.create(tenant_id="tenant-2", event_type="test.event.two")

    with pytest.raises(ValueError) as unknown_error:
        coordinator.append_to_episode(uuid.uuid4(), Event.create(tenant_id="tenant-1", event_type="test.event.two"))
    with pytest.raises(ValueError) as cross_tenant_error:
        coordinator.append_to_episode(episode.episode_id, cross_tenant_event)

    assert str(unknown_error.value) == str(cross_tenant_error.value)


def test_append_to_episode_rejects_duplicate_event() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)

    with pytest.raises(ValueError, match="already present"):
        coordinator.append_to_episode(episode.episode_id, initial_event)

    assert coordinator._event_store.count_for_tenant("tenant-1") == 1
    assert coordinator._episode_store.count_for_tenant("tenant-1") == 1
    assert coordinator._episode_store.get_by_id("tenant-1", episode.episode_id) is episode
    assert coordinator._episode_store.get_by_id("tenant-1", episode.episode_id).event_ids == (initial_event.event_id,)


def test_append_to_episode_rejects_event_id_already_in_event_store() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    duplicate_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")
    event_store = coordinator._event_store
    event_store.append(duplicate_event)

    with pytest.raises(ValueError, match="duplicate event_id"):
        coordinator.append_to_episode(episode.episode_id, duplicate_event)


def test_append_to_episode_rejects_non_uuid_episode_id() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(TypeError, match="uuid.UUID"):
        coordinator.append_to_episode("not-a-uuid", event)


def test_append_to_episode_rejects_non_event_input() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())

    with pytest.raises(TypeError, match="Event"):
        coordinator.append_to_episode(uuid.uuid4(), object())


def test_episode_store_is_unchanged_when_event_store_append_fails() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = coordinator.start_episode(initial_event)
    other_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")
    coordinator._event_store.append(other_event)

    with pytest.raises(ValueError, match="duplicate event_id"):
        coordinator.append_to_episode(episode.episode_id, other_event)

    assert coordinator._episode_store.get_by_id("tenant-1", episode.episode_id) is episode


def test_updating_one_tenant_does_not_affect_another_tenant() -> None:
    coordinator = EpisodeCoordinator(InMemoryEventStore(), InMemoryEpisodeStore())
    tenant_one_episode = coordinator.start_episode(Event.create(tenant_id="tenant-1", event_type="test.event.one"))
    tenant_two_episode = coordinator.start_episode(Event.create(tenant_id="tenant-2", event_type="test.event.two"))

    coordinator.append_to_episode(tenant_one_episode.episode_id, Event.create(tenant_id="tenant-1", event_type="test.event.three"))

    assert coordinator._episode_store.list_for_tenant("tenant-1")[0].episode_id == tenant_one_episode.episode_id
    assert coordinator._episode_store.list_for_tenant("tenant-2")[0].episode_id == tenant_two_episode.episode_id


def test_find_episode_for_event_finds_first_event() -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
    )
    episode = coordinator.start_episode(event)

    result = coordinator.find_episode_for_event(
        "tenant-1",
        event.event_id,
    )

    assert result is episode


def test_find_episode_for_event_finds_later_event() -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )
    first_event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event.one",
    )
    episode = coordinator.start_episode(first_event)
    later_event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event.two",
    )
    updated_episode = coordinator.append_to_episode(
        episode.episode_id,
        later_event,
    )

    result = coordinator.find_episode_for_event(
        "tenant-1",
        later_event.event_id,
    )

    assert result is updated_episode


def test_find_episode_for_event_returns_none_for_unknown_exact_uuid() -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
    )
    coordinator.start_episode(event)

    assert coordinator.find_episode_for_event(
        "tenant-1",
        uuid.uuid4(),
    ) is None


def test_find_episode_for_event_preserves_tenant_isolation() -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
    )
    coordinator.start_episode(event)

    assert coordinator.find_episode_for_event(
        "tenant-2",
        event.event_id,
    ) is None


def test_find_episode_for_event_does_not_mutate_state() -> None:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
    )
    episode = coordinator.start_episode(event)
    original_event_ids = episode.event_ids

    result = coordinator.find_episode_for_event(
        "tenant-1",
        event.event_id,
    )

    assert result is episode
    assert result.event_ids == original_event_ids
    assert event_store.total_count() == 1
    assert episode_store.total_count() == 1
    with pytest.raises(AttributeError):
        result.tenant_id = "other"


@pytest.mark.parametrize("invalid_tenant_id", [None, object()])
def test_find_episode_for_event_rejects_non_string_tenant_id(
    invalid_tenant_id: object,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(TypeError, match="string"):
        coordinator.find_episode_for_event(
            invalid_tenant_id,
            uuid.uuid4(),
        )


@pytest.mark.parametrize("invalid_tenant_id", ["", "   "])
def test_find_episode_for_event_rejects_empty_tenant_id(
    invalid_tenant_id: str,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(ValueError, match="non-empty"):
        coordinator.find_episode_for_event(
            invalid_tenant_id,
            uuid.uuid4(),
        )


@pytest.mark.parametrize("invalid_event_id", [None, object(), "not-a-uuid"])
def test_find_episode_for_event_rejects_invalid_event_id(
    invalid_event_id: object,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(TypeError, match="uuid.UUID"):
        coordinator.find_episode_for_event(
            "tenant-1",
            invalid_event_id,
        )


def test_get_event_returns_exact_tenant_scoped_event() -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
    )
    coordinator.start_episode(event)

    assert coordinator.get_event("tenant-1", event.event_id) is event
    assert coordinator.get_event("tenant-2", event.event_id) is None
    assert coordinator.get_event("tenant-1", uuid.uuid4()) is None


@pytest.mark.parametrize("invalid_tenant_id", [None, object()])
def test_get_event_rejects_non_string_tenant(
    invalid_tenant_id: object,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(TypeError, match="string"):
        coordinator.get_event(invalid_tenant_id, uuid.uuid4())


@pytest.mark.parametrize("invalid_tenant_id", ["", "   "])
def test_get_event_rejects_empty_tenant(
    invalid_tenant_id: str,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(ValueError, match="non-empty"):
        coordinator.get_event(invalid_tenant_id, uuid.uuid4())


@pytest.mark.parametrize("invalid_event_id", [None, object(), "invalid"])
def test_get_event_rejects_invalid_event_id(
    invalid_event_id: object,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(TypeError, match="uuid.UUID"):
        coordinator.get_event("tenant-1", invalid_event_id)
