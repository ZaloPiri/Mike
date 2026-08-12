import uuid

import pytest

from mike_app.handlers.perception_normalization import (
    PerceptionNormalizationHandler,
)
from mike_app.perception.normalization import PerceptionNormalizer
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


class SpyNormalizer(PerceptionNormalizer):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def normalize(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return super().normalize(**kwargs)


def make_components() -> tuple[
    EventJournalView,
    EpisodeJournalView,
    EpisodeCoordinator,
    SpyNormalizer,
    PerceptionNormalizationHandler,
]:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    normalizer = SpyNormalizer()
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = PerceptionNormalizationHandler(
        coordinator,
        normalizer,
        dispatcher,
    )
    return event_store, episode_store, coordinator, normalizer, handler


def append_chain(
    coordinator: EpisodeCoordinator,
    *,
    source_type: str = "message.received",
    accepted_type: str = "message.accepted",
    accepted_source_id: str | None = None,
    perceived_payload: dict[str, object] | None = None,
) -> tuple[object, Event, Event, Event]:
    source = Event.create(
        tenant_id="tenant-1",
        event_type=source_type,
        payload={"text": "Hola"},
    )
    episode = coordinator.start_episode(source)
    accepted = Event.create(
        tenant_id="tenant-1",
        event_type=accepted_type,
        payload={
            "source_event_id": (
                accepted_source_id
                if accepted_source_id is not None
                else str(source.event_id)
            )
        },
    )
    coordinator.append_to_episode(episode.episode_id, accepted)
    payload = perceived_payload or {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "language": "Spanish",
        "intent": "Order Request",
        "confidence": 0.82,
        "entities": {
            "item": "sandwich",
            "qty": "dos",
            "unknown_key": "drop",
        },
    }
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, perceived)
    return episode, source, accepted, perceived


def test_constructor_accepts_dependencies_and_handler_is_callable() -> None:
    _, _, coordinator, normalizer, _ = make_components()

    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = PerceptionNormalizationHandler(
        coordinator,
        normalizer,
        dispatcher,
    )

    assert handler._episode_coordinator is coordinator
    assert handler._perception_normalizer is normalizer
    assert handler._runtime_dispatcher is dispatcher
    assert callable(handler)


@pytest.mark.parametrize("invalid_coordinator", [None, object()])
def test_constructor_rejects_invalid_coordinator(
    invalid_coordinator: object,
) -> None:
    with pytest.raises(TypeError, match="EpisodeCoordinator"):
        PerceptionNormalizationHandler(
            invalid_coordinator,
            PerceptionNormalizer(),
            RuntimeDispatcher(RuntimeHandlerRegistry()),
        )


@pytest.mark.parametrize("invalid_normalizer", [None, object()])
def test_constructor_rejects_invalid_normalizer(
    invalid_normalizer: object,
) -> None:
    coordinator = EpisodeCoordinator(InMemoryEpisodeJournal())

    with pytest.raises(TypeError, match="PerceptionNormalizer"):
        PerceptionNormalizationHandler(
            coordinator,
            invalid_normalizer,
            RuntimeDispatcher(RuntimeHandlerRegistry()),
        )


@pytest.mark.parametrize("invalid_dispatcher", [None, object()])
def test_constructor_rejects_invalid_dispatcher(
    invalid_dispatcher: object,
) -> None:
    coordinator = EpisodeCoordinator(InMemoryEpisodeJournal())

    with pytest.raises(TypeError, match="RuntimeDispatcher"):
        PerceptionNormalizationHandler(
            coordinator,
            PerceptionNormalizer(),
            invalid_dispatcher,
        )


@pytest.mark.parametrize("invalid_context", [None, object()])
def test_invalid_context_is_rejected(invalid_context: object) -> None:
    _, _, _, _, handler = make_components()

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(invalid_context)


def test_wrong_event_type_is_rejected() -> None:
    _, _, _, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived.related",
    )

    with pytest.raises(ValueError, match="message.perceived"):
        handler(RuntimeContext.create(event))


def test_unknown_containing_episode_is_rejected() -> None:
    _, _, _, normalizer, handler = make_components()
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload={},
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_event_id", None),
        ("source_event_id", "invalid"),
        ("accepted_event_id", None),
        ("accepted_event_id", "invalid"),
    ],
)
def test_malformed_event_ids_are_rejected(
    field: str,
    value: object,
) -> None:
    _, _, coordinator, normalizer, handler = make_components()
    episode, source, accepted, _ = append_chain(coordinator)
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.5,
        "entities": {},
    }
    payload[field] = value
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, perceived)

    with pytest.raises(ValueError, match=field):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


@pytest.mark.parametrize("relationship", ["source", "accepted"])
def test_cross_episode_event_reference_is_rejected(
    relationship: str,
) -> None:
    _, _, coordinator, normalizer, handler = make_components()
    episode, source, accepted, _ = append_chain(coordinator)
    other_source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": "Other"},
    )
    other_episode = coordinator.start_episode(other_source)
    other_accepted = Event.create(
        tenant_id="tenant-1",
        event_type="message.accepted",
        payload={"source_event_id": str(other_source.event_id)},
    )
    coordinator.append_to_episode(other_episode.episode_id, other_accepted)
    payload = {
        "source_event_id": str(
            other_source.event_id
            if relationship == "source"
            else source.event_id
        ),
        "accepted_event_id": str(
            other_accepted.event_id
            if relationship == "accepted"
            else accepted.event_id
        ),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.5,
        "entities": {},
    }
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, perceived)

    with pytest.raises(ValueError, match="perceived Episode"):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


def test_cross_tenant_source_and_accepted_are_not_resolved() -> None:
    _, _, coordinator, normalizer, handler = make_components()
    episode, source, accepted, _ = append_chain(coordinator)
    other_source = Event.create(
        tenant_id="tenant-2",
        event_type="message.received",
        payload={"text": "Other"},
    )
    other_episode = coordinator.start_episode(other_source)
    other_accepted = Event.create(
        tenant_id="tenant-2",
        event_type="message.accepted",
        payload={"source_event_id": str(other_source.event_id)},
    )
    coordinator.append_to_episode(other_episode.episode_id, other_accepted)
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload={
            "source_event_id": str(other_source.event_id),
            "accepted_event_id": str(other_accepted.event_id),
            "language": "es",
            "intent": "greeting",
            "confidence": 0.5,
            "entities": {},
        },
    )
    coordinator.append_to_episode(episode.episode_id, perceived)

    with pytest.raises(ValueError, match="perceived Episode"):
        handler(RuntimeContext.create(perceived))

    assert coordinator.get_event(
        "tenant-1",
        other_source.event_id,
    ) is None
    assert coordinator.get_event(
        "tenant-1",
        other_accepted.event_id,
    ) is None
    assert normalizer.calls == []


@pytest.mark.parametrize(
    ("source_type", "accepted_type", "match"),
    [
        ("other.event", "message.accepted", "message.received"),
        ("message.received", "other.event", "message.accepted"),
    ],
)
def test_referenced_event_types_are_validated(
    source_type: str,
    accepted_type: str,
    match: str,
) -> None:
    _, _, coordinator, normalizer, handler = make_components()
    _, _, _, perceived = append_chain(
        coordinator,
        source_type=source_type,
        accepted_type=accepted_type,
    )

    with pytest.raises(ValueError, match=match):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


def test_accepted_source_event_id_must_match_exactly() -> None:
    _, _, coordinator, normalizer, handler = make_components()
    episode, source, accepted, _ = append_chain(
        coordinator,
        accepted_source_id=str(uuid.uuid4()),
    )
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "language": "es",
            "intent": "greeting",
            "confidence": 0.5,
            "entities": {},
        },
    )
    coordinator.append_to_episode(episode.episode_id, perceived)

    with pytest.raises(ValueError, match="does not match"):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "source_event_id",
        "accepted_event_id",
        "language",
        "intent",
        "confidence",
        "entities",
    ],
)
def test_missing_payload_fields_are_rejected(
    missing_field: str,
) -> None:
    _, _, coordinator, normalizer, handler = make_components()
    episode, source, accepted, _ = append_chain(coordinator)
    payload = {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.5,
        "entities": {},
    }
    payload.pop(missing_field)
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload=payload,
    )
    coordinator.append_to_episode(episode.episode_id, perceived)

    with pytest.raises(ValueError, match="missing fields"):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


def test_invalid_entities_payload_is_rejected() -> None:
    _, _, coordinator, normalizer, handler = make_components()
    episode, source, accepted, _ = append_chain(coordinator)
    perceived = Event.create(
        tenant_id="tenant-1",
        event_type="message.perceived",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "language": "es",
            "intent": "greeting",
            "confidence": 0.5,
            "entities": "invalid",
        },
    )
    coordinator.append_to_episode(episode.episode_id, perceived)

    with pytest.raises(ValueError, match="entities"):
        handler(RuntimeContext.create(perceived))

    assert normalizer.calls == []


def test_creates_exact_normalized_event_in_same_episode() -> None:
    event_store, episode_store, coordinator, normalizer, handler = (
        make_components()
    )
    episode, source, accepted, perceived = append_chain(coordinator)

    result = handler(RuntimeContext.create(perceived))

    events = event_store.list_for_tenant("tenant-1")
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    normalized = events[3]
    assert result is None
    assert normalizer.calls == [
        {
            "language": "Spanish",
            "intent": "Order Request",
            "confidence": 0.82,
            "entities": {
                "item": "sandwich",
                "qty": "dos",
                "unknown_key": "drop",
            },
        }
    ]
    assert [event.event_type for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
    ]
    assert normalized.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "language": "Spanish",
        "intent": "place_order",
        "confidence": 0.82,
        "entities": {
            "product": "sandwich",
            "quantity": "dos",
        },
    }
    assert "raw_intent" not in normalized.payload
    assert "provider" not in normalized.payload
    assert updated_episode is not None
    assert updated_episode.episode_id == episode.episode_id
    assert updated_episode.event_ids == tuple(
        event.event_id for event in events
    )


def test_normalizer_exception_adds_no_normalized_event() -> None:
    event_store, _, coordinator, normalizer, handler = make_components()
    _, _, _, perceived = append_chain(coordinator)
    error = ValueError("collision")
    normalizer.error = error

    with pytest.raises(ValueError, match="collision") as exc_info:
        handler(RuntimeContext.create(perceived))

    assert exc_info.value is error
    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )] == [
        "message.received",
        "message.accepted",
        "message.perceived",
    ]


def test_repeated_explicit_invocation_adds_one_event_per_call() -> None:
    event_store, _, coordinator, _, handler = make_components()
    _, _, _, perceived = append_chain(coordinator)
    context = RuntimeContext.create(perceived)

    handler(context)
    handler(context)

    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "perception.normalized",
    ]


def test_dispatches_exact_normalized_context_once_after_append() -> None:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    normalizer = SpyNormalizer()
    observed_contexts: list[RuntimeContext] = []

    def downstream(context: RuntimeContext) -> None:
        assert event_store.get_by_id(
            context.event.tenant_id,
            context.event.event_id,
        ) is context.event
        observed_contexts.append(context)

    registry.register("perception.normalized", downstream)
    handler = PerceptionNormalizationHandler(
        coordinator,
        normalizer,
        dispatcher,
    )
    _, _, _, perceived = append_chain(coordinator)

    handler(RuntimeContext.create(perceived))

    normalized = event_store.list_for_tenant("tenant-1")[-1]
    assert len(observed_contexts) == 1
    assert observed_contexts[0].event is normalized


def test_dispatch_failure_preserves_normalized_event_without_retry() -> None:
    journal = InMemoryEpisodeJournal()
    event_store = EventJournalView(journal)
    episode_store = EpisodeJournalView(journal)
    coordinator = EpisodeCoordinator(journal)
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    calls = 0
    error = RuntimeError("downstream failed")

    def failing_downstream(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register("perception.normalized", failing_downstream)
    handler = PerceptionNormalizationHandler(
        coordinator,
        PerceptionNormalizer(),
        dispatcher,
    )
    _, _, _, perceived = append_chain(coordinator)

    with pytest.raises(RuntimeError, match="downstream failed") as exc_info:
        handler(RuntimeContext.create(perceived))

    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
    ]
