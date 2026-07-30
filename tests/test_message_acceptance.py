import pytest

from mike_app.handlers.message_acceptance import MessageAcceptanceHandler
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore


def make_components() -> tuple[
    InMemoryEventStore,
    InMemoryEpisodeStore,
    EpisodeCoordinator,
    MessageAcceptanceHandler,
]:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    handler = MessageAcceptanceHandler(coordinator)
    return event_store, episode_store, coordinator, handler


def test_constructor_accepts_coordinator_and_handler_is_callable() -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    handler = MessageAcceptanceHandler(coordinator)

    assert handler._episode_coordinator is coordinator
    assert callable(handler)


@pytest.mark.parametrize("invalid_coordinator", [None, object()])
def test_constructor_rejects_invalid_coordinator(
    invalid_coordinator: object,
) -> None:
    with pytest.raises(TypeError, match="EpisodeCoordinator"):
        MessageAcceptanceHandler(invalid_coordinator)


@pytest.mark.parametrize("invalid_context", [None, object()])
def test_call_rejects_invalid_context(invalid_context: object) -> None:
    _, _, _, handler = make_components()

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(invalid_context)


def test_call_rejects_bare_event() -> None:
    _, _, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(event)


def test_non_message_received_event_is_rejected_without_storage() -> None:
    event_store, episode_store, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received.related",
    )

    with pytest.raises(ValueError, match="message.received"):
        handler(RuntimeContext.create(event))

    assert event_store.total_count() == 0
    assert episode_store.total_count() == 0


def test_unknown_source_event_raises_without_creating_derived_event() -> None:
    event_store, episode_store, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(event))

    assert event_store.total_count() == 0
    assert episode_store.total_count() == 0


def test_cross_tenant_episode_is_not_matched() -> None:
    event_store, episode_store, coordinator, handler = make_components()
    stored_event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )
    coordinator.start_episode(stored_event)
    source_event = Event(
        event_id=stored_event.event_id,
        tenant_id="tenant-2",
        event_type="message.received",
        occurred_at=stored_event.occurred_at,
        payload={},
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(source_event))

    assert event_store.total_count() == 1
    assert episode_store.total_count() == 1


def test_call_appends_one_exact_derived_event_to_same_episode() -> None:
    event_store, episode_store, coordinator, handler = make_components()
    source_event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": "original"},
    )
    source_state = source_event.to_dict()
    episode = coordinator.start_episode(source_event)
    context = RuntimeContext.create(source_event)

    result = handler(context)

    stored_events = event_store.list_for_tenant("tenant-1")
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    assert result is None
    assert len(stored_events) == 2
    assert episode_store.total_count() == 1
    assert stored_events[0] is source_event
    assert stored_events[1].event_type == "message.accepted"
    assert stored_events[1].tenant_id == source_event.tenant_id
    assert stored_events[1].to_dict()["payload"] == {
        "source_event_id": str(source_event.event_id),
    }
    assert isinstance(
        stored_events[1].to_dict()["payload"]["source_event_id"],
        str,
    )
    assert stored_events[1].event_id != source_event.event_id
    assert updated_episode is not None
    assert updated_episode.episode_id == episode.episode_id
    assert updated_episode.tenant_id == episode.tenant_id
    assert updated_episode.event_ids == (
        source_event.event_id,
        stored_events[1].event_id,
    )
    assert source_event.to_dict() == source_state
    assert context.event is source_event


def test_repeated_explicit_invocation_appends_one_event_per_call() -> None:
    event_store, episode_store, coordinator, handler = make_components()
    source_event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )
    episode = coordinator.start_episode(source_event)
    context = RuntimeContext.create(source_event)

    handler(context)
    handler(context)

    stored_events = event_store.list_for_tenant("tenant-1")
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    assert [event.event_type for event in stored_events] == [
        "message.received",
        "message.accepted",
        "message.accepted",
    ]
    assert updated_episode is not None
    assert updated_episode.event_ids == tuple(
        event.event_id for event in stored_events
    )
