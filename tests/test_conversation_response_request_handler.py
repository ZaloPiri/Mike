import uuid

import pytest

from mike_app.conversation.response_planning import ResponseRequestPlanner
from mike_app.handlers.conversation_response_request import (
    ConversationResponseRequestHandler,
)
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


class SpyPlanner(ResponseRequestPlanner):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def plan(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return super().plan(**kwargs)


def make_components():
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    planner = SpyPlanner()
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = ConversationResponseRequestHandler(
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
    normalized_type: str = "perception.normalized",
    accepted_source: str | None = None,
    perceived_source: str | None = None,
    perceived_accepted: str | None = None,
    normalized_source: str | None = None,
    normalized_accepted: str | None = None,
    normalized_perceived: str | None = None,
    next_action_payload: dict[str, object] | None = None,
):
    source = Event.create(
        tenant_id=tenant_id,
        event_type=source_type,
        payload={"text": "Hola"},
    )
    episode = coordinator.start_episode(source)
    accepted = Event.create(
        tenant_id=tenant_id,
        event_type=accepted_type,
        payload={
            "source_event_id": accepted_source or str(source.event_id)
        },
    )
    coordinator.append_to_episode(episode.episode_id, accepted)
    perceived = Event.create(
        tenant_id=tenant_id,
        event_type=perceived_type,
        payload={
            "source_event_id": perceived_source or str(source.event_id),
            "accepted_event_id": (
                perceived_accepted or str(accepted.event_id)
            ),
        },
    )
    coordinator.append_to_episode(episode.episode_id, perceived)
    normalized = Event.create(
        tenant_id=tenant_id,
        event_type=normalized_type,
        payload={
            "source_event_id": normalized_source or str(source.event_id),
            "accepted_event_id": (
                normalized_accepted or str(accepted.event_id)
            ),
            "perceived_event_id": (
                normalized_perceived or str(perceived.event_id)
            ),
            "language": "  Español (AR)  ",
            "intent": "place_order",
            "confidence": 0.8,
            "entities": {"product": "sandwich"},
        },
    )
    coordinator.append_to_episode(episode.episode_id, normalized)
    payload = next_action_payload or {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "action": "request_missing_information",
        "reason": "missing_required_entities",
        "can_continue": False,
        "missing_entities": ["quantity"],
    }
    next_action = Event.create(
        tenant_id=tenant_id,
        event_type="conversation.next_action",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, next_action)
    return episode, source, accepted, perceived, normalized, next_action


def test_constructor_and_callable_interface() -> None:
    _, _, coordinator, planner, _ = make_components()

    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = ConversationResponseRequestHandler(
        coordinator,
        planner,
        dispatcher,
    )

    assert handler._episode_coordinator is coordinator
    assert handler._response_request_planner is planner
    assert handler._runtime_dispatcher is dispatcher
    assert callable(handler)


@pytest.mark.parametrize(
    ("coordinator", "planner", "match"),
    [
        (None, ResponseRequestPlanner(), "EpisodeCoordinator"),
        (object(), ResponseRequestPlanner(), "EpisodeCoordinator"),
        (
            EpisodeCoordinator(InMemoryEpisodeJournal()),
            None,
            "ResponseRequestPlanner",
        ),
        (
            EpisodeCoordinator(InMemoryEpisodeJournal()),
            object(),
            "ResponseRequestPlanner",
        ),
    ],
)
def test_constructor_validation(
    coordinator: object,
    planner: object,
    match: str,
) -> None:
    with pytest.raises(TypeError, match=match):
        ConversationResponseRequestHandler(
            coordinator,
            planner,
            RuntimeDispatcher(RuntimeHandlerRegistry()),
        )


@pytest.mark.parametrize("dispatcher", [None, object()])
def test_constructor_rejects_invalid_dispatcher(
    dispatcher: object,
) -> None:
    coordinator = EpisodeCoordinator(InMemoryEpisodeJournal())

    with pytest.raises(TypeError, match="RuntimeDispatcher"):
        ConversationResponseRequestHandler(
            coordinator,
            ResponseRequestPlanner(),
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
        event_type="conversation.next_action.related",
    )

    with pytest.raises(ValueError, match="conversation.next_action"):
        handler(RuntimeContext.create(event))


def test_unknown_containing_episode_is_rejected() -> None:
    *_, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.next_action",
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(event))


@pytest.mark.parametrize(
    "field",
    [
        "source_event_id",
        "accepted_event_id",
        "perceived_event_id",
        "normalized_event_id",
    ],
)
@pytest.mark.parametrize("value", [None, "invalid"])
def test_malformed_uuid_reference_is_rejected(
    field: str,
    value: object,
) -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, normalized, _ = append_chain(
        coordinator
    )
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": [],
    }
    payload[field] = value
    next_action = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.next_action",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, next_action)

    with pytest.raises(ValueError, match=field):
        handler(RuntimeContext.create(next_action))
    assert planner.calls == []


@pytest.mark.parametrize(
    ("type_field", "wrong_type", "match"),
    [
        ("source_type", "wrong", "message.received"),
        ("accepted_type", "wrong", "message.accepted"),
        ("perceived_type", "wrong", "message.perceived"),
        ("normalized_type", "wrong", "perception.normalized"),
    ],
)
def test_wrong_referenced_event_type_is_rejected(
    type_field: str,
    wrong_type: str,
    match: str,
) -> None:
    *_, coordinator, planner, handler = make_components()
    kwargs = {type_field: wrong_type}
    *_, next_action = append_chain(coordinator, **kwargs)

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(next_action))
    assert planner.calls == []


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("accepted_source", "accepted Event source"),
        ("perceived_source", "perceived Event source"),
        ("perceived_accepted", "perceived Event accepted"),
        ("normalized_source", "normalized Event source"),
        ("normalized_accepted", "normalized Event accepted"),
        ("normalized_perceived", "normalized Event perceived"),
    ],
)
def test_explicit_relationship_mismatch_is_rejected(
    field: str,
    match: str,
) -> None:
    *_, coordinator, planner, handler = make_components()
    kwargs = {field: str(uuid.uuid4())}
    *_, next_action = append_chain(coordinator, **kwargs)

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(next_action))
    assert planner.calls == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "source_event_id",
        "accepted_event_id",
        "perceived_event_id",
        "normalized_event_id",
        "action",
        "reason",
        "can_continue",
        "missing_entities",
    ],
)
def test_missing_next_action_payload_field_is_rejected(
    missing_field: str,
) -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, normalized, _ = append_chain(
        coordinator
    )
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": [],
    }
    payload.pop(missing_field)
    next_action = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.next_action",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, next_action)

    with pytest.raises(ValueError, match="missing fields"):
        handler(RuntimeContext.create(next_action))
    assert planner.calls == []


@pytest.mark.parametrize("missing_entities", ["quantity", {"quantity": 1}])
def test_invalid_missing_entities_payload_is_rejected(
    missing_entities: object,
) -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, normalized, _ = append_chain(
        coordinator
    )
    next_action = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.next_action",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "action": "request_missing_information",
            "reason": "missing_required_entities",
            "can_continue": False,
            "missing_entities": missing_entities,
        },
    )
    coordinator.append_to_episode(episode.episode_id, next_action)

    with pytest.raises(ValueError, match="missing_entities"):
        handler(RuntimeContext.create(next_action))
    assert planner.calls == []


def test_cross_episode_reference_is_rejected() -> None:
    *_, coordinator, planner, handler = make_components()
    episode, source, accepted, perceived, normalized, _ = append_chain(
        coordinator
    )
    _, other_source, _, _, _, _ = append_chain(coordinator)
    next_action = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.next_action",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "action": "respond",
            "reason": "intent_understood",
            "can_continue": True,
            "missing_entities": [],
        },
    )
    coordinator.append_to_episode(episode.episode_id, next_action)

    with pytest.raises(ValueError, match="next-action Episode"):
        handler(RuntimeContext.create(next_action))
    assert planner.calls == []


def test_cross_tenant_reference_is_not_resolved() -> None:
    *_, coordinator, planner, handler = make_components()
    episode, _, accepted, perceived, normalized, _ = append_chain(
        coordinator
    )
    _, other_source, _, _, _, _ = append_chain(
        coordinator,
        tenant_id="tenant-2",
    )
    next_action = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.next_action",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "action": "respond",
            "reason": "intent_understood",
            "can_continue": True,
            "missing_entities": [],
        },
    )
    coordinator.append_to_episode(episode.episode_id, next_action)

    with pytest.raises(ValueError, match="next-action Episode"):
        handler(RuntimeContext.create(next_action))
    assert coordinator.get_event(
        "tenant-1",
        other_source.event_id,
    ) is None
    assert planner.calls == []


def test_creates_exact_response_request_and_passes_exact_values() -> None:
    event_store, episode_store, coordinator, planner, handler = (
        make_components()
    )
    episode, source, accepted, perceived, normalized, next_action = (
        append_chain(coordinator)
    )

    result = handler(RuntimeContext.create(next_action))

    events = event_store.list_for_tenant("tenant-1")
    response_request = events[-1]
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    assert result is None
    assert planner.calls == [
        {
            "action": "request_missing_information",
            "reason": "missing_required_entities",
            "can_continue": False,
            "missing_entities": ("quantity",),
            "language": "  Español (AR)  ",
            "intent": "place_order",
            "entities": {"product": "sandwich"},
        }
    ]
    assert [event.event_type for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
        "conversation.response_request",
    ]
    assert response_request.event_id not in {
        source.event_id,
        accepted.event_id,
        perceived.event_id,
        normalized.event_id,
        next_action.event_id,
    }
    assert response_request.tenant_id == "tenant-1"
    assert response_request.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_type": "missing_information",
        "target_language": "  Español (AR)  ",
        "intent": "place_order",
        "requested_entities": ["quantity"],
        "handoff_reason": None,
    }
    assert "text" not in response_request.payload
    assert updated_episode is not None
    assert updated_episode.event_ids == tuple(
        event.event_id for event in events
    )
    assert episode_store.count_for_tenant("tenant-1") == 1


def test_planner_failure_creates_no_response_request() -> None:
    event_store, _, coordinator, planner, handler = make_components()
    *_, next_action = append_chain(coordinator)
    error = ValueError("response planning failed")
    planner.error = error

    with pytest.raises(
        ValueError,
        match="response planning failed",
    ) as exc_info:
        handler(RuntimeContext.create(next_action))

    assert exc_info.value is error
    assert len(event_store.list_for_tenant("tenant-1")) == 5


def test_repeated_invocation_has_no_deduplication() -> None:
    event_store, _, coordinator, _, handler = make_components()
    *_, next_action = append_chain(coordinator)
    context = RuntimeContext.create(next_action)

    handler(context)
    handler(context)

    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )][-2:] == [
        "conversation.response_request",
        "conversation.response_request",
    ]


def test_dispatches_exact_response_request_once_after_append() -> None:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    observed_contexts: list[RuntimeContext] = []

    def downstream(context: RuntimeContext) -> None:
        assert event_store.get_by_id(
            context.event.tenant_id,
            context.event.event_id,
        ) is context.event
        observed_contexts.append(context)

    registry.register("conversation.response_request", downstream)
    handler = ConversationResponseRequestHandler(
        coordinator,
        ResponseRequestPlanner(),
        dispatcher,
    )
    *_, next_action = append_chain(coordinator)

    handler(RuntimeContext.create(next_action))

    response_request = event_store.list_for_tenant("tenant-1")[-1]
    assert len(observed_contexts) == 1
    assert observed_contexts[0].event is response_request


def test_dispatch_failure_preserves_response_request_without_retry() -> None:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    calls = 0
    error = RuntimeError("generation dispatch failed")

    def failing_downstream(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register("conversation.response_request", failing_downstream)
    handler = ConversationResponseRequestHandler(
        coordinator,
        ResponseRequestPlanner(),
        dispatcher,
    )
    *_, next_action = append_chain(coordinator)

    with pytest.raises(
        RuntimeError,
        match="generation dispatch failed",
    ) as exc_info:
        handler(RuntimeContext.create(next_action))

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
        "conversation.response_request",
    ]
