import uuid

import pytest

from mike_app.conversation.response_validation import (
    ConversationResponseValidator,
)
from mike_app.handlers.conversation_response_validated import (
    ConversationResponseValidatedHandler,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry
from tests.test_conversation_response_validation import build_chain


class SpyValidator(ConversationResponseValidator):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def validate(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return super().validate(**kwargs)


def make_handler():
    chain = build_chain()
    event_store, episode_store, coordinator = chain[:3]
    validator = SpyValidator()
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    handler = ConversationResponseValidatedHandler(
        coordinator,
        validator,
        dispatcher,
    )
    return event_store, episode_store, validator, handler, chain


def test_handler_creates_exact_terminal_eighth_event() -> None:
    event_store, episode_store, validator, handler, chain = make_handler()
    episode = chain[3]
    source, accepted, perceived, normalized = chain[4:8]
    next_action, response_request, generated = chain[8:11]

    result = handler(RuntimeContext.create(generated))

    events = event_store.list_for_tenant("tenant-1")
    stored_episode = episode_store.get_by_id("tenant-1", episode.episode_id)
    validated = events[-1]
    assert result is None
    assert len(validator.calls) == 1
    assert len(events) == 8
    assert validated.event_type == "conversation.response_validated"
    assert validated.tenant_id == "tenant-1"
    assert validated.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "perceived_event_id": str(perceived.event_id),
        "normalized_event_id": str(normalized.event_id),
        "next_action_event_id": str(next_action.event_id),
        "response_request_event_id": str(response_request.event_id),
        "response_generated_event_id": str(generated.event_id),
        "response_type": "intent_response",
        "language": "es",
        "text": "  ¡Hola!\n¿En qué puedo ayudarte?  ",
        "generation_method": "deterministic_template",
        "validation_method": "deterministic_contract",
    }
    assert {
        "is_valid",
        "validation_status",
        "violations",
    }.isdisjoint(validated.payload)
    assert stored_episode is not None
    assert stored_episode.event_ids == tuple(
        event.event_id for event in events
    )


def test_validation_failure_preserves_exactly_seven_events() -> None:
    event_store, _, validator, handler, chain = make_handler()
    error = ValueError("validation failed")
    validator.error = error

    with pytest.raises(ValueError, match="validation failed") as exc_info:
        handler(RuntimeContext.create(chain[-1]))

    assert exc_info.value is error
    events = event_store.list_for_tenant("tenant-1")
    assert len(events) == 7
    assert events[-1].event_type == "conversation.response_generated"
    assert all("reject" not in event.event_type for event in events)


@pytest.mark.parametrize("value", [None, "invalid", str(uuid.uuid4())])
def test_missing_invalid_or_crossed_reference_creates_no_event(
    value: object,
) -> None:
    event_store, _, _, handler, chain = make_handler()
    generated = chain[-1]
    payload = generated.to_dict()["payload"]
    if value is None:
        payload.pop("source_event_id")
    else:
        payload["source_event_id"] = value
    invalid_generated = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_generated",
        payload=payload,
    )
    coordinator = chain[2]
    coordinator.append_to_episode(chain[3].episode_id, invalid_generated)

    with pytest.raises(ValueError):
        handler(RuntimeContext.create(invalid_generated))

    assert event_store.list_for_tenant("tenant-1")[-1] is invalid_generated
    assert all(
        event.event_type != "conversation.response_validated"
        for event in event_store.list_for_tenant("tenant-1")
    )


def test_handler_is_tenant_safe() -> None:
    event_store, _, _, handler, chain = make_handler()
    other_source = Event.create(
        tenant_id="tenant-other",
        event_type="message.received",
    )
    other_episode = chain[2].start_episode(other_source)
    payload = chain[-1].to_dict()["payload"]
    payload["source_event_id"] = str(other_source.event_id)
    crossed = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_generated",
        payload=payload,
    )
    chain[2].append_to_episode(chain[3].episode_id, crossed)

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(crossed))

    assert chain[2].get_event("tenant-1", other_source.event_id) is None
    assert chain[2].get_event(
        "tenant-other",
        other_source.event_id,
    ) is other_source
    assert other_episode.tenant_id == "tenant-other"
    assert event_store.count_for_tenant("tenant-1") == 8


@pytest.mark.parametrize("context", [None, object()])
def test_invalid_context_is_rejected(context: object) -> None:
    *_, handler, _ = make_handler()

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(context)


def test_wrong_initial_event_type_is_rejected() -> None:
    *_, handler, _ = make_handler()
    wrong = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_request",
    )

    with pytest.raises(ValueError, match="response_generated"):
        handler(RuntimeContext.create(wrong))


def test_validated_event_is_appended_before_single_dispatch() -> None:
    chain = build_chain()
    event_store, _, coordinator = chain[:3]
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    observed: list[RuntimeContext] = []

    def downstream(context: RuntimeContext) -> None:
        assert event_store.get_by_id(
            context.event.tenant_id,
            context.event.event_id,
        ) is context.event
        assert coordinator.find_episode_for_event(
            context.event.tenant_id,
            context.event.event_id,
        ) is not None
        observed.append(context)

    registry.register("conversation.response_validated", downstream)
    handler = ConversationResponseValidatedHandler(
        coordinator,
        ConversationResponseValidator(),
        dispatcher,
    )

    handler(RuntimeContext.create(chain[-1]))

    assert len(observed) == 1
    assert observed[0].event.event_type == "conversation.response_validated"


def test_target_dispatch_failure_preserves_eighth_event_without_retry() -> None:
    chain = build_chain()
    event_store, _, coordinator = chain[:3]
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    calls = 0
    error = RuntimeError("target resolution failed")

    def failing_downstream(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register(
        "conversation.response_validated",
        failing_downstream,
    )
    handler = ConversationResponseValidatedHandler(
        coordinator,
        ConversationResponseValidator(),
        dispatcher,
    )

    with pytest.raises(
        RuntimeError,
        match="target resolution failed",
    ) as exc_info:
        handler(RuntimeContext.create(chain[-1]))

    assert exc_info.value is error
    assert calls == 1
    events = event_store.list_for_tenant("tenant-1")
    assert len(events) == 8
    assert events[-1].event_type == "conversation.response_validated"
