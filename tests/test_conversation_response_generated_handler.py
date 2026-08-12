import uuid

import pytest

from mike_app.conversation.response_generation import (
    DeterministicResponseGenerator,
)
from mike_app.handlers.conversation_response_generated import (
    ConversationResponseGeneratedHandler,
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


class SpyGenerator(DeterministicResponseGenerator):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def generate(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return super().generate(**kwargs)


def make_components():
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    generator = SpyGenerator()
    handler = ConversationResponseGeneratedHandler(
        coordinator,
        generator,
        dispatcher,
    )
    return event_store, episode_store, coordinator, generator, handler


def append_chain(
    coordinator: EpisodeCoordinator,
    *,
    tenant_id: str = "tenant-1",
    event_types: dict[str, str] | None = None,
    relationship_overrides: dict[str, str] | None = None,
    normalized_values: dict[str, object] | None = None,
    next_action_values: dict[str, object] | None = None,
    response_request_payload: dict[str, object] | None = None,
):
    types = {
        "source": "message.received",
        "accepted": "message.accepted",
        "perceived": "message.perceived",
        "normalized": "perception.normalized",
        "next_action": "conversation.next_action",
    }
    types.update(event_types or {})
    overrides = relationship_overrides or {}
    source = Event.create(
        tenant_id=tenant_id,
        event_type=types["source"],
        payload={"text": "Hola"},
    )
    episode = coordinator.start_episode(source)
    accepted = Event.create(
        tenant_id=tenant_id,
        event_type=types["accepted"],
        payload={
            "source_event_id": overrides.get(
                "accepted_source",
                str(source.event_id),
            )
        },
    )
    coordinator.append_to_episode(episode.episode_id, accepted)
    perceived = Event.create(
        tenant_id=tenant_id,
        event_type=types["perceived"],
        payload={
            "source_event_id": overrides.get(
                "perceived_source",
                str(source.event_id),
            ),
            "accepted_event_id": overrides.get(
                "perceived_accepted",
                str(accepted.event_id),
            ),
        },
    )
    coordinator.append_to_episode(episode.episode_id, perceived)
    normalized_payload = {
        "source_event_id": overrides.get(
            "normalized_source",
            str(source.event_id),
        ),
        "accepted_event_id": overrides.get(
            "normalized_accepted",
            str(accepted.event_id),
        ),
        "perceived_event_id": overrides.get(
            "normalized_perceived",
            str(perceived.event_id),
        ),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.9,
        "entities": {},
    }
    normalized_payload.update(normalized_values or {})
    normalized = Event.create(
        tenant_id=tenant_id,
        event_type=types["normalized"],
        payload=normalized_payload,
    )
    coordinator.append_to_episode(episode.episode_id, normalized)
    next_action_payload = {
        "source_event_id": overrides.get(
            "next_action_source",
            str(source.event_id),
        ),
        "accepted_event_id": overrides.get(
            "next_action_accepted",
            str(accepted.event_id),
        ),
        "perceived_event_id": overrides.get(
            "next_action_perceived",
            str(perceived.event_id),
        ),
        "normalized_event_id": overrides.get(
            "next_action_normalized",
            str(normalized.event_id),
        ),
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": [],
    }
    next_action_payload.update(next_action_values or {})
    next_action = Event.create(
        tenant_id=tenant_id,
        event_type=types["next_action"],
        payload=next_action_payload,
    )
    coordinator.append_to_episode(episode.episode_id, next_action)
    request_payload = response_request_payload or {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_type": "intent_response",
        "target_language": "es",
        "intent": "greeting",
        "requested_entities": [],
        "handoff_reason": None,
    }
    response_request = Event.create(
        tenant_id=tenant_id,
        event_type="conversation.response_request",
        payload=request_payload,
    )
    coordinator.append_to_episode(episode.episode_id, response_request)
    return (
        episode,
        source,
        accepted,
        perceived,
        normalized,
        next_action,
        response_request,
    )


def test_constructor_and_callable_interface() -> None:
    _, _, coordinator, generator, _ = make_components()
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())

    handler = ConversationResponseGeneratedHandler(
        coordinator,
        generator,
        dispatcher,
    )

    assert handler._episode_coordinator is coordinator
    assert handler._response_generator is generator
    assert handler._runtime_dispatcher is dispatcher
    assert callable(handler)


@pytest.mark.parametrize(
    ("coordinator", "generator", "dispatcher", "match"),
    [
        (
            None,
            DeterministicResponseGenerator(),
            RuntimeDispatcher(RuntimeHandlerRegistry()),
            "EpisodeCoordinator",
        ),
        (
            object(),
            DeterministicResponseGenerator(),
            RuntimeDispatcher(RuntimeHandlerRegistry()),
            "EpisodeCoordinator",
        ),
        (
            EpisodeCoordinator(InMemoryEpisodeJournal()),
            None,
            RuntimeDispatcher(RuntimeHandlerRegistry()),
            "DeterministicResponseGenerator",
        ),
        (
            EpisodeCoordinator(InMemoryEpisodeJournal()),
            object(),
            RuntimeDispatcher(RuntimeHandlerRegistry()),
            "DeterministicResponseGenerator",
        ),
        (
            EpisodeCoordinator(InMemoryEpisodeJournal()),
            DeterministicResponseGenerator(),
            None,
            "RuntimeDispatcher",
        ),
    ],
)
def test_constructor_validation(
    coordinator: object,
    generator: object,
    dispatcher: object,
    match: str,
) -> None:
    with pytest.raises(TypeError, match=match):
        ConversationResponseGeneratedHandler(
            coordinator,
            generator,
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
        event_type="conversation.response_request.related",
    )

    with pytest.raises(ValueError, match="conversation.response_request"):
        handler(RuntimeContext.create(event))


def test_unknown_containing_episode_is_rejected() -> None:
    *_, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
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
        "next_action_event_id",
    ],
)
@pytest.mark.parametrize("value", [None, "invalid"])
def test_malformed_uuid_reference_is_rejected(
    field: str,
    value: object,
) -> None:
    *_, coordinator, generator, handler = make_components()
    chain = append_chain(coordinator)
    episode, source, accepted, perceived, normalized, next_action, _ = chain
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_type": "intent_response",
        "target_language": "es",
        "intent": "greeting",
        "requested_entities": [],
        "handoff_reason": None,
    }
    payload[field] = value
    request = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, request)

    with pytest.raises(ValueError, match=field):
        handler(RuntimeContext.create(request))
    assert generator.calls == []


@pytest.mark.parametrize(
    ("event_name", "expected"),
    [
        ("source", "message.received"),
        ("accepted", "message.accepted"),
        ("perceived", "message.perceived"),
        ("normalized", "perception.normalized"),
        ("next_action", "conversation.next_action"),
    ],
)
def test_wrong_referenced_event_type_is_rejected(
    event_name: str,
    expected: str,
) -> None:
    *_, coordinator, generator, handler = make_components()
    *_, request = append_chain(
        coordinator,
        event_types={event_name: "wrong"},
    )

    with pytest.raises(ValueError, match=expected):
        handler(RuntimeContext.create(request))
    assert generator.calls == []


@pytest.mark.parametrize(
    ("relationship", "match"),
    [
        ("accepted_source", "accepted Event source"),
        ("perceived_source", "perceived Event source"),
        ("perceived_accepted", "perceived Event accepted"),
        ("normalized_source", "normalized Event source"),
        ("normalized_accepted", "normalized Event accepted"),
        ("normalized_perceived", "normalized Event perceived"),
        ("next_action_source", "next-action Event source"),
        ("next_action_accepted", "next-action Event accepted"),
        ("next_action_perceived", "next-action Event perceived"),
        ("next_action_normalized", "next-action Event normalized"),
    ],
)
def test_explicit_relationship_mismatch_is_rejected(
    relationship: str,
    match: str,
) -> None:
    *_, coordinator, generator, handler = make_components()
    *_, request = append_chain(
        coordinator,
        relationship_overrides={relationship: str(uuid.uuid4())},
    )

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(request))
    assert generator.calls == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "source_event_id",
        "accepted_event_id",
        "perceived_event_id",
        "normalized_event_id",
        "next_action_event_id",
        "response_type",
        "target_language",
        "intent",
        "requested_entities",
        "handoff_reason",
    ],
)
def test_missing_response_request_field_is_rejected(
    missing_field: str,
) -> None:
    *_, coordinator, generator, handler = make_components()
    episode, source, accepted, perceived, normalized, next_action, _ = (
        append_chain(coordinator)
    )
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_type": "intent_response",
        "target_language": "es",
        "intent": "greeting",
        "requested_entities": [],
        "handoff_reason": None,
    }
    payload.pop(missing_field)
    request = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, request)

    with pytest.raises(ValueError, match="missing fields"):
        handler(RuntimeContext.create(request))
    assert generator.calls == []


def test_cross_episode_and_cross_tenant_references_are_rejected() -> None:
    *_, coordinator, generator, handler = make_components()
    episode, _, accepted, perceived, normalized, next_action, _ = (
        append_chain(coordinator)
    )
    _, other_source, _, _, _, _, _ = append_chain(
        coordinator,
        tenant_id="tenant-2",
    )
    request = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "next_action_event_id": str(next_action.event_id),
            "response_type": "intent_response",
            "target_language": "es",
            "intent": "greeting",
            "requested_entities": [],
            "handoff_reason": None,
        },
    )
    coordinator.append_to_episode(episode.episode_id, request)

    with pytest.raises(ValueError, match="response-request Episode"):
        handler(RuntimeContext.create(request))
    assert coordinator.get_event(
        "tenant-1",
        other_source.event_id,
    ) is None
    assert generator.calls == []


def test_same_tenant_reference_from_another_episode_is_rejected() -> None:
    *_, coordinator, generator, handler = make_components()
    episode, _, accepted, perceived, normalized, next_action, _ = (
        append_chain(coordinator)
    )
    _, other_source, _, _, _, _, _ = append_chain(coordinator)
    request = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "next_action_event_id": str(next_action.event_id),
            "response_type": "intent_response",
            "target_language": "es",
            "intent": "greeting",
            "requested_entities": [],
            "handoff_reason": None,
        },
    )
    coordinator.append_to_episode(episode.episode_id, request)

    with pytest.raises(ValueError, match="response-request Episode"):
        handler(RuntimeContext.create(request))
    assert generator.calls == []


@pytest.mark.parametrize(
    ("request_changes", "normalized_changes", "next_changes", "match"),
    [
        (
            {"target_language": "ES"},
            {},
            {},
            "target_language",
        ),
        (
            {"intent": "unknown"},
            {},
            {},
            "intent",
        ),
        (
            {"response_type": "clarification", "intent": "greeting"},
            {},
            {},
            "next action",
        ),
        (
            {
                "response_type": "missing_information",
                "intent": "place_order",
                "requested_entities": ["product"],
            },
            {"intent": "place_order"},
            {
                "action": "request_missing_information",
                "reason": "missing_required_entities",
                "can_continue": False,
                "missing_entities": ["quantity"],
            },
            "next action",
        ),
        (
            {
                "response_type": "human_handoff",
                "intent": "complaint",
                "handoff_reason": "human_requested",
            },
            {"intent": "complaint"},
            {
                "action": "handoff_human",
                "reason": "complaint_requires_human",
                "can_continue": False,
                "missing_entities": [],
            },
            "next action",
        ),
    ],
)
def test_semantic_mismatch_is_rejected_before_generation(
    request_changes: dict[str, object],
    normalized_changes: dict[str, object],
    next_changes: dict[str, object],
    match: str,
) -> None:
    *_, coordinator, generator, handler = make_components()
    chain = append_chain(
        coordinator,
        normalized_values=normalized_changes,
        next_action_values=next_changes,
    )
    episode, source, accepted, perceived, normalized, next_action, _ = chain
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_type": "intent_response",
        "target_language": "es",
        "intent": "greeting",
        "requested_entities": [],
        "handoff_reason": None,
    }
    payload.update(request_changes)
    request = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, request)

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(request))
    assert generator.calls == []


def test_creates_exact_generated_event_and_passes_exact_values() -> None:
    event_store, episode_store, coordinator, generator, handler = (
        make_components()
    )
    (
        episode,
        source,
        accepted,
        perceived,
        normalized,
        next_action,
        response_request,
    ) = append_chain(coordinator)

    result = handler(RuntimeContext.create(response_request))

    events = event_store.list_for_tenant("tenant-1")
    generated = events[-1]
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    assert result is None
    assert generator.calls == [
        {
            "response_type": "intent_response",
            "language": "es",
            "intent": "greeting",
            "requested_entities": (),
            "handoff_reason": None,
        }
    ]
    assert [event.event_type for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
        "conversation.response_request",
        "conversation.response_generated",
    ]
    assert generated.event_id not in {
        source.event_id,
        accepted.event_id,
        perceived.event_id,
        normalized.event_id,
        next_action.event_id,
        response_request.event_id,
    }
    assert generated.tenant_id == "tenant-1"
    assert generated.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_request_event_id": str(response_request.event_id),
        "response_type": "intent_response",
        "language": "es",
        "text": "¡Hola! ¿En qué puedo ayudarte?",
        "generation_method": "deterministic_template",
    }
    forbidden = {
        "intent",
        "requested_entities",
        "handoff_reason",
        "provider",
        "model",
        "confidence",
    }
    assert forbidden.isdisjoint(generated.payload)
    assert updated_episode is not None
    assert updated_episode.event_ids == tuple(
        event.event_id for event in events
    )
    assert episode_store.count_for_tenant("tenant-1") == 1


def test_generator_failure_creates_no_generated_event() -> None:
    event_store, _, coordinator, generator, handler = make_components()
    *_, response_request = append_chain(coordinator)
    error = ValueError("generation failed")
    generator.error = error

    with pytest.raises(ValueError, match="generation failed") as exc_info:
        handler(RuntimeContext.create(response_request))

    assert exc_info.value is error
    assert len(event_store.list_for_tenant("tenant-1")) == 6


def test_generated_event_is_appended_before_single_dispatch() -> None:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    observed: list[RuntimeContext] = []

    def downstream(context: RuntimeContext) -> None:
        stored = event_store.get_by_id(
            context.event.tenant_id,
            context.event.event_id,
        )
        assert stored is context.event
        episode = coordinator.find_episode_for_event(
            context.event.tenant_id,
            context.event.event_id,
        )
        assert episode is not None
        observed.append(context)

    registry.register("conversation.response_generated", downstream)
    handler = ConversationResponseGeneratedHandler(
        coordinator,
        DeterministicResponseGenerator(),
        dispatcher,
    )
    *_, response_request = append_chain(coordinator)

    handler(RuntimeContext.create(response_request))

    assert len(observed) == 1
    assert observed[0].event.event_type == (
        "conversation.response_generated"
    )


def test_validation_dispatch_failure_preserves_generated_without_retry() -> None:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    calls = 0
    error = RuntimeError("validation failed")

    def failing_downstream(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register(
        "conversation.response_generated",
        failing_downstream,
    )
    handler = ConversationResponseGeneratedHandler(
        coordinator,
        DeterministicResponseGenerator(),
        dispatcher,
    )
    *_, response_request = append_chain(coordinator)

    with pytest.raises(RuntimeError, match="validation failed") as exc_info:
        handler(RuntimeContext.create(response_request))

    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )][-1] == "conversation.response_generated"
    assert len(event_store.list_for_tenant("tenant-1")) == 7


def test_repeated_invocation_has_no_deduplication() -> None:
    event_store, _, coordinator, _, handler = make_components()
    *_, response_request = append_chain(coordinator)
    context = RuntimeContext.create(response_request)

    handler(context)
    handler(context)

    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )][-2:] == [
        "conversation.response_generated",
        "conversation.response_generated",
    ]
