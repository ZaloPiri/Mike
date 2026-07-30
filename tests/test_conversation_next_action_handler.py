import uuid

import pytest

from mike_app.conversation.action_planning import ConversationActionPlanner
from mike_app.handlers.conversation_next_action import (
    ConversationNextActionHandler,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


class SpyPlanner(ConversationActionPlanner):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def plan(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return super().plan(**kwargs)


def make_components():
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    planner = SpyPlanner()
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = ConversationNextActionHandler(
        coordinator,
        planner,
        dispatcher,
    )
    return event_store, episode_store, coordinator, planner, handler


def append_chain(
    coordinator: EpisodeCoordinator,
    *,
    tenant_id: str = "tenant-1",
    source_type: str = "message.received",
    accepted_type: str = "message.accepted",
    perceived_type: str = "message.perceived",
    accepted_source_id: str | None = None,
    perceived_source_id: str | None = None,
    perceived_accepted_id: str | None = None,
    normalized_payload: dict[str, object] | None = None,
):
    source = Event.create(
        tenant_id=tenant_id,
        event_type=source_type,
        payload={"text": "Quiero dos sandwiches"},
    )
    episode = coordinator.start_episode(source)
    accepted = Event.create(
        tenant_id=tenant_id,
        event_type=accepted_type,
        payload={
            "source_event_id": accepted_source_id or str(source.event_id)
        },
    )
    coordinator.append_to_episode(episode.episode_id, accepted)
    perceived = Event.create(
        tenant_id=tenant_id,
        event_type=perceived_type,
        payload={
            "source_event_id": perceived_source_id or str(source.event_id),
            "accepted_event_id": (
                perceived_accepted_id or str(accepted.event_id)
            ),
        },
    )
    coordinator.append_to_episode(episode.episode_id, perceived)
    payload = normalized_payload or {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "language": "es",
        "intent": "place_order",
        "confidence": 0.9,
        "entities": {"product": "sandwich", "quantity": 2},
    }
    normalized = Event.create(
        tenant_id=tenant_id,
        event_type="perception.normalized",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, normalized)
    return episode, source, accepted, perceived, normalized


def test_constructor_and_callable_interface() -> None:
    _, _, coordinator, planner, _ = make_components()

    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = ConversationNextActionHandler(
        coordinator,
        planner,
        dispatcher,
    )

    assert handler._episode_coordinator is coordinator
    assert handler._conversation_action_planner is planner
    assert handler._runtime_dispatcher is dispatcher
    assert callable(handler)


@pytest.mark.parametrize(
    ("coordinator", "planner", "match"),
    [
        (None, ConversationActionPlanner(), "EpisodeCoordinator"),
        (object(), ConversationActionPlanner(), "EpisodeCoordinator"),
        (
            EpisodeCoordinator(
                InMemoryEventStore(),
                InMemoryEpisodeStore(),
            ),
            None,
            "ConversationActionPlanner",
        ),
        (
            EpisodeCoordinator(
                InMemoryEventStore(),
                InMemoryEpisodeStore(),
            ),
            object(),
            "ConversationActionPlanner",
        ),
    ],
)
def test_constructor_validation(
    coordinator: object,
    planner: object,
    match: str,
) -> None:
    with pytest.raises(TypeError, match=match):
        ConversationNextActionHandler(
            coordinator,
            planner,
            RuntimeDispatcher(RuntimeHandlerRegistry()),
        )


@pytest.mark.parametrize("dispatcher", [None, object()])
def test_constructor_rejects_invalid_dispatcher(
    dispatcher: object,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(TypeError, match="RuntimeDispatcher"):
        ConversationNextActionHandler(
            coordinator,
            ConversationActionPlanner(),
            dispatcher,
        )


@pytest.mark.parametrize("context", [None, object()])
def test_invalid_context_is_rejected(context: object) -> None:
    *_, handler = make_components()

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(context)


def test_wrong_event_type_is_rejected() -> None:
    *_, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized.related",
    )

    with pytest.raises(ValueError, match="perception.normalized"):
        handler(RuntimeContext.create(event))


def test_missing_containing_episode_is_rejected() -> None:
    *_, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized",
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(event))


@pytest.mark.parametrize(
    "field",
    ["source_event_id", "accepted_event_id", "perceived_event_id"],
)
@pytest.mark.parametrize("value", [None, "invalid"])
def test_malformed_reference_uuid_is_rejected(
    field: str,
    value: object,
) -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, _ = append_chain(coordinator)
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.9,
        "entities": {},
    }
    payload[field] = value
    normalized = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, normalized)

    with pytest.raises(ValueError, match=field):
        handler(RuntimeContext.create(normalized))
    assert planner.calls == []


@pytest.mark.parametrize(
    ("source_type", "accepted_type", "perceived_type", "match"),
    [
        ("wrong", "message.accepted", "message.perceived", "message.received"),
        ("message.received", "wrong", "message.perceived", "message.accepted"),
        ("message.received", "message.accepted", "wrong", "message.perceived"),
    ],
)
def test_wrong_referenced_event_type_is_rejected(
    source_type: str,
    accepted_type: str,
    perceived_type: str,
    match: str,
) -> None:
    *_, coordinator, planner, handler = make_components()
    *_, normalized = append_chain(
        coordinator,
        source_type=source_type,
        accepted_type=accepted_type,
        perceived_type=perceived_type,
    )

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(normalized))
    assert planner.calls == []


@pytest.mark.parametrize(
    ("relationship", "match"),
    [
        ("accepted_source", "accepted Event source"),
        ("perceived_source", "perceived Event source"),
        ("perceived_accepted", "perceived Event accepted"),
    ],
)
def test_reference_relationship_mismatch_is_rejected(
    relationship: str,
    match: str,
) -> None:
    *_, coordinator, planner, handler = make_components()
    kwargs = {relationship + "_id": str(uuid.uuid4())}
    *_, normalized = append_chain(coordinator, **kwargs)

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(normalized))
    assert planner.calls == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "source_event_id",
        "accepted_event_id",
        "perceived_event_id",
        "language",
        "intent",
        "confidence",
        "entities",
    ],
)
def test_missing_payload_field_is_rejected(missing_field: str) -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, _ = append_chain(coordinator)
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.9,
        "entities": {},
    }
    payload.pop(missing_field)
    normalized = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, normalized)

    with pytest.raises(ValueError, match="missing fields"):
        handler(RuntimeContext.create(normalized))
    assert planner.calls == []


def test_invalid_entities_are_rejected() -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, _ = append_chain(coordinator)
    normalized = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "language": "es",
            "intent": "greeting",
            "confidence": 0.9,
            "entities": "invalid",
        },
    )
    coordinator.append_to_episode(episode.episode_id, normalized)

    with pytest.raises(ValueError, match="entities"):
        handler(RuntimeContext.create(normalized))
    assert planner.calls == []


def test_cross_episode_reference_is_rejected() -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, _ = append_chain(coordinator)
    _, other_source, _, _, _ = append_chain(coordinator)
    normalized = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "language": "es",
            "intent": "greeting",
            "confidence": 0.9,
            "entities": {},
        },
    )
    coordinator.append_to_episode(episode.episode_id, normalized)

    with pytest.raises(ValueError, match="normalized Episode"):
        handler(RuntimeContext.create(normalized))
    assert planner.calls == []


def test_cross_tenant_reference_is_not_resolved() -> None:
    *_, coordinator, planner, handler = make_components()
    episode, _, accepted, perceived, _ = append_chain(coordinator)
    _, other_source, _, _, _ = append_chain(
        coordinator,
        tenant_id="tenant-2",
    )
    normalized = Event.create(
        tenant_id="tenant-1",
        event_type="perception.normalized",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "language": "es",
            "intent": "greeting",
            "confidence": 0.9,
            "entities": {},
        },
    )
    coordinator.append_to_episode(episode.episode_id, normalized)

    with pytest.raises(ValueError, match="normalized Episode"):
        handler(RuntimeContext.create(normalized))
    assert coordinator.get_event(
        "tenant-1",
        other_source.event_id,
    ) is None
    assert planner.calls == []


def test_creates_exact_event_and_passes_exact_planner_values() -> None:
    event_store, episode_store, coordinator, planner, handler = (
        make_components()
    )
    episode, source, accepted, perceived, normalized = append_chain(
        coordinator
    )

    result = handler(RuntimeContext.create(normalized))

    events = event_store.list_for_tenant("tenant-1")
    next_action = events[-1]
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    assert result is None
    assert planner.calls == [
        {
            "intent": "place_order",
            "entities": {"product": "sandwich", "quantity": 2},
        }
    ]
    assert [event.event_type for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
    ]
    assert next_action.event_id not in {
        source.event_id,
        accepted.event_id,
        perceived.event_id,
        normalized.event_id,
    }
    assert next_action.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": [],
    }
    assert updated_episode is not None
    assert updated_episode.event_ids == tuple(
        event.event_id for event in events
    )


def test_planner_failure_adds_no_next_action_event() -> None:
    event_store, _, coordinator, planner, handler = make_components()
    *_, normalized = append_chain(coordinator)
    error = ValueError("planning failed")
    planner.error = error

    with pytest.raises(ValueError, match="planning failed") as exc_info:
        handler(RuntimeContext.create(normalized))

    assert exc_info.value is error
    assert len(event_store.list_for_tenant("tenant-1")) == 4


def test_repeated_invocation_has_no_deduplication() -> None:
    event_store, _, coordinator, _, handler = make_components()
    *_, normalized = append_chain(coordinator)
    context = RuntimeContext.create(normalized)

    handler(context)
    handler(context)

    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )][-2:] == [
        "conversation.next_action",
        "conversation.next_action",
    ]


def test_dispatches_exact_next_action_context_once_after_append() -> None:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    observed_contexts: list[RuntimeContext] = []

    def downstream(context: RuntimeContext) -> None:
        assert event_store.get_by_id(
            context.event.tenant_id,
            context.event.event_id,
        ) is context.event
        observed_contexts.append(context)

    registry.register("conversation.next_action", downstream)
    handler = ConversationNextActionHandler(
        coordinator,
        ConversationActionPlanner(),
        dispatcher,
    )
    *_, normalized = append_chain(coordinator)

    handler(RuntimeContext.create(normalized))

    next_action = event_store.list_for_tenant("tenant-1")[-1]
    assert len(observed_contexts) == 1
    assert observed_contexts[0].event is next_action


def test_dispatch_failure_preserves_next_action_without_retry() -> None:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    calls = 0
    error = RuntimeError("response-request dispatch failed")

    def failing_downstream(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register("conversation.next_action", failing_downstream)
    handler = ConversationNextActionHandler(
        coordinator,
        ConversationActionPlanner(),
        dispatcher,
    )
    *_, normalized = append_chain(coordinator)

    with pytest.raises(
        RuntimeError,
        match="response-request dispatch failed",
    ) as exc_info:
        handler(RuntimeContext.create(normalized))

    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
    ]
