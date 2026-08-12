import pytest

from mike_app.handlers.message_acceptance import MessageAcceptanceHandler
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_journal import (
    EpisodeJournalView,
    EventJournalView,
    InMemoryEpisodeJournal,
)
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


def make_components() -> tuple[
    EventJournalView,
    EpisodeJournalView,
    EpisodeCoordinator,
    RuntimeHandlerRegistry,
    MessageAcceptanceHandler,
]:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    handler = MessageAcceptanceHandler(coordinator, dispatcher)
    return event_store, episode_store, coordinator, registry, handler


def test_constructor_accepts_coordinator_and_handler_is_callable() -> None:
    coordinator = EpisodeCoordinator(InMemoryEpisodeJournal())
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())

    handler = MessageAcceptanceHandler(coordinator, dispatcher)

    assert handler._episode_coordinator is coordinator
    assert handler._runtime_dispatcher is dispatcher
    assert callable(handler)


@pytest.mark.parametrize("invalid_coordinator", [None, object()])
def test_constructor_rejects_invalid_coordinator(
    invalid_coordinator: object,
) -> None:
    with pytest.raises(TypeError, match="EpisodeCoordinator"):
        MessageAcceptanceHandler(
            invalid_coordinator,
            RuntimeDispatcher(RuntimeHandlerRegistry()),
        )


@pytest.mark.parametrize("invalid_dispatcher", [None, object()])
def test_constructor_rejects_invalid_dispatcher(
    invalid_dispatcher: object,
) -> None:
    coordinator = EpisodeCoordinator(InMemoryEpisodeJournal())

    with pytest.raises(TypeError, match="RuntimeDispatcher"):
        MessageAcceptanceHandler(coordinator, invalid_dispatcher)


@pytest.mark.parametrize("invalid_context", [None, object()])
def test_call_rejects_invalid_context(invalid_context: object) -> None:
    _, _, _, _, handler = make_components()

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(invalid_context)


def test_call_rejects_bare_event() -> None:
    _, _, _, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(event)


def test_non_message_received_event_is_rejected_without_storage() -> None:
    event_store, episode_store, _, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received.related",
    )

    with pytest.raises(ValueError, match="message.received"):
        handler(RuntimeContext.create(event))

    assert event_store.total_count() == 0
    assert episode_store.total_count() == 0


def test_unknown_source_event_raises_without_creating_derived_event() -> None:
    event_store, episode_store, _, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(event))

    assert event_store.total_count() == 0
    assert episode_store.total_count() == 0


def test_cross_tenant_episode_is_not_matched() -> None:
    event_store, episode_store, coordinator, _, handler = make_components()
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
    event_store, episode_store, coordinator, _, handler = make_components()
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
    event_store, episode_store, coordinator, _, handler = make_components()
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


def test_dispatches_exact_accepted_context_once_after_append() -> None:
    event_store, _, coordinator, registry, handler = make_components()
    source_event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )
    coordinator.start_episode(source_event)
    seen: list[RuntimeContext] = []
    registry.register("message.accepted", seen.append)

    handler(RuntimeContext.create(source_event))

    accepted_event = event_store.list_for_tenant("tenant-1")[1]
    assert len(seen) == 1
    assert seen[0].event is accepted_event
    assert coordinator.find_episode_for_event(
        "tenant-1",
        accepted_event.event_id,
    ) is not None


def test_dispatch_failure_leaves_accepted_event_and_is_not_retried() -> None:
    event_store, episode_store, coordinator, registry, handler = (
        make_components()
    )
    source_event = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
    )
    episode = coordinator.start_episode(source_event)
    calls = 0
    error = RuntimeError("perception failed")

    def failing_handler(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register("message.accepted", failing_handler)

    with pytest.raises(RuntimeError, match="perception failed") as exc_info:
        handler(RuntimeContext.create(source_event))

    stored_events = event_store.list_for_tenant("tenant-1")
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in stored_events] == [
        "message.received",
        "message.accepted",
    ]
    assert updated_episode is not None
    assert updated_episode.event_ids == tuple(
        event.event_id for event in stored_events
    )
