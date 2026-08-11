from dataclasses import replace
import uuid

import pytest

from mike_app.communication.target_resolution import (
    ConversationResponseTargetResolver,
)
from mike_app.handlers.conversation_response_target_resolved import (
    ConversationResponseTargetResolvedHandler,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry
from tests.test_conversation_response_validation import build_chain


class SpyResolver(ConversationResponseTargetResolver):
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.error: Exception | None = None

    def resolve(self, context):
        self.calls.append(context)
        if self.error is not None:
            raise self.error
        return super().resolve(context)


def build_eight_event_chain(
    *,
    tenant_id: str = "tenant-1",
    communication_context_values: dict[str, object] | None = None,
):
    chain = build_chain(
        tenant_id=tenant_id,
        communication_context_values=communication_context_values,
    )
    coordinator = chain[2]
    episode = chain[3]
    source, accepted, perceived, normalized = chain[4:8]
    next_action, response_request, generated = chain[8:11]
    validated = Event.create(
        tenant_id=tenant_id,
        event_type="conversation.response_validated",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "next_action_event_id": str(next_action.event_id),
            "response_request_event_id": str(response_request.event_id),
            "response_generated_event_id": str(generated.event_id),
            "response_type": generated.payload["response_type"],
            "language": generated.payload["language"],
            "text": generated.payload["text"],
            "generation_method": generated.payload["generation_method"],
            "validation_method": "deterministic_contract",
        },
    )
    coordinator.append_to_episode(episode.episode_id, validated)
    return chain + (validated,)


def make_handler(**kwargs: object):
    chain = build_eight_event_chain(**kwargs)
    resolver = SpyResolver()
    handler = ConversationResponseTargetResolvedHandler(
        chain[2],
        resolver,
        RuntimeDispatcher(RuntimeHandlerRegistry()),
    )
    return chain, resolver, handler


def test_creates_exact_terminal_ninth_event() -> None:
    chain, resolver, handler = make_handler()
    event_store, episode_store, _, episode = chain[:4]
    source = chain[4]
    validated = chain[-1]

    result = handler(RuntimeContext.create(validated))

    events = event_store.list_for_tenant("tenant-1")
    target = events[-1]
    stored_episode = episode_store.get_by_id("tenant-1", episode.episode_id)
    assert result is None
    assert len(resolver.calls) == 1
    assert len(events) == 9
    assert target.event_type == "communication.response_target_resolved"
    assert target.tenant_id == "tenant-1"
    assert target.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "response_validated_event_id": str(validated.event_id),
        "channel": "development",
        "external_message_id": "message-id",
        "external_conversation_id": "conversation-id",
        "outbound_sender_id": "tenant-1",
        "outbound_recipient_id": "development-user",
        "resolution_method": "reply_to_source",
    }
    forbidden = {
        "text",
        "language",
        "response_type",
        "generation_method",
        "validation_method",
        "accepted_event_id",
        "perceived_event_id",
        "normalized_event_id",
        "next_action_event_id",
        "response_request_event_id",
        "response_generated_event_id",
        "tenant_id",
        "episode_id",
        "is_ready",
        "delivery_status",
        "idempotency_key",
    }
    assert forbidden.isdisjoint(target.payload)
    assert stored_episode is not None
    assert stored_episode.event_ids == tuple(
        event.event_id for event in events
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "channel",
        "external_message_id",
        "external_conversation_id",
        "sender_id",
        "recipient_id",
    ],
)
@pytest.mark.parametrize("value", [None, 1, "", "   "])
def test_invalid_communication_context_preserves_eight_events(
    field_name: str,
    value: object,
) -> None:
    chain, resolver, handler = make_handler(
        communication_context_values={field_name: value}
    )

    with pytest.raises((TypeError, ValueError), match=field_name):
        handler(RuntimeContext.create(chain[-1]))

    events = chain[0].list_for_tenant("tenant-1")
    assert len(events) == 8
    assert resolver.calls == []
    assert all("reject" not in event.event_type for event in events)


def test_resolver_failure_preserves_eight_events_without_retry() -> None:
    chain, resolver, handler = make_handler()
    error = RuntimeError("resolution failed")
    resolver.error = error

    with pytest.raises(RuntimeError, match="resolution failed") as exc_info:
        handler(RuntimeContext.create(chain[-1]))

    assert exc_info.value is error
    assert len(resolver.calls) == 1
    assert len(chain[0].list_for_tenant("tenant-1")) == 8


@pytest.mark.parametrize("position", range(8))
def test_wrong_event_type_at_each_position_is_rejected(
    position: int,
) -> None:
    chain, resolver, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[position]
    object.__setattr__(event, "event_type", "wrong.event")

    with pytest.raises(
        ValueError,
        match="Event must be|requires conversation.response_validated",
    ):
        handler(RuntimeContext.create(chain[-1]))

    assert resolver.calls == []
    assert len(chain[0].list_for_tenant("tenant-1")) == 8


@pytest.mark.parametrize(
    ("position", "field_name"),
    [
        (1, "source_event_id"),
        (2, "accepted_event_id"),
        (3, "perceived_event_id"),
        (4, "normalized_event_id"),
        (5, "next_action_event_id"),
        (6, "response_request_event_id"),
        (7, "response_generated_event_id"),
    ],
)
def test_crossed_reference_is_rejected(
    position: int,
    field_name: str,
) -> None:
    chain, resolver, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[position]
    payload = event.to_dict()["payload"]
    payload[field_name] = str(uuid.uuid4())
    object.__setattr__(event, "payload", payload)

    with pytest.raises(ValueError, match=field_name):
        handler(RuntimeContext.create(chain[-1]))

    assert resolver.calls == []
    assert len(chain[0].list_for_tenant("tenant-1")) == 8


@pytest.mark.parametrize("mutation", ["missing", "additional", "reordered"])
def test_episode_must_contain_exactly_eight_ordered_events(
    mutation: str,
) -> None:
    chain, resolver, handler = make_handler()
    episode_store = chain[1]
    episode = episode_store.get_by_id("tenant-1", chain[3].episode_id)
    assert episode is not None
    if mutation == "missing":
        event_ids = episode.event_ids[:-1]
    elif mutation == "additional":
        event_ids = episode.event_ids + (uuid.uuid4(),)
    else:
        event_ids = episode.event_ids[:6] + (
            episode.event_ids[7],
            episode.event_ids[6],
        )
    episode_store._episodes_by_id[episode.episode_id] = replace(
        episode,
        event_ids=event_ids,
    )

    with pytest.raises(ValueError, match="Episode|eighth"):
        handler(RuntimeContext.create(chain[-1]))

    assert resolver.calls == []
    assert all(
        event.event_type != "communication.response_target_resolved"
        for event in chain[0].list_for_tenant("tenant-1")
    )


def test_wrong_initial_event_and_unknown_episode_are_rejected() -> None:
    chain, _, handler = make_handler()
    wrong = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_generated",
    )
    with pytest.raises(ValueError, match="response_validated"):
        handler(RuntimeContext.create(wrong))

    unknown = Event.create(
        tenant_id="tenant-1",
        event_type="conversation.response_validated",
    )
    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(unknown))


def test_two_tenants_resolve_only_their_own_contexts() -> None:
    first, _, first_handler = make_handler(tenant_id="tenant-one")
    second, _, second_handler = make_handler(tenant_id="tenant-two")

    first_handler(RuntimeContext.create(first[-1]))
    second_handler(RuntimeContext.create(second[-1]))

    first_target = first[0].list_for_tenant("tenant-one")[-1]
    second_target = second[0].list_for_tenant("tenant-two")[-1]
    assert first_target.payload["outbound_sender_id"] == "tenant-one"
    assert second_target.payload["outbound_sender_id"] == "tenant-two"
    assert first[2].get_event("tenant-one", second_target.event_id) is None
    assert second[2].get_event("tenant-two", first_target.event_id) is None


def test_target_is_appended_before_single_dispatch() -> None:
    chain = build_eight_event_chain()
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    observed: list[RuntimeContext] = []

    def downstream(context: RuntimeContext) -> None:
        assert chain[0].get_by_id(
            context.event.tenant_id,
            context.event.event_id,
        ) is context.event
        assert chain[2].find_episode_for_event(
            context.event.tenant_id,
            context.event.event_id,
        ) is not None
        observed.append(context)

    registry.register("communication.response_target_resolved", downstream)
    handler = ConversationResponseTargetResolvedHandler(
        chain[2],
        ConversationResponseTargetResolver(),
        dispatcher,
    )

    handler(RuntimeContext.create(chain[-1]))

    assert len(observed) == 1
    assert observed[0].event.event_type == (
        "communication.response_target_resolved"
    )


def test_readiness_dispatch_failure_preserves_ninth_without_retry() -> None:
    chain = build_eight_event_chain()
    registry = RuntimeHandlerRegistry()
    dispatcher = RuntimeDispatcher(registry)
    calls = 0
    error = RuntimeError("readiness failed")

    def failing_downstream(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise error

    registry.register(
        "communication.response_target_resolved",
        failing_downstream,
    )
    handler = ConversationResponseTargetResolvedHandler(
        chain[2],
        ConversationResponseTargetResolver(),
        dispatcher,
    )

    with pytest.raises(RuntimeError, match="readiness failed") as exc_info:
        handler(RuntimeContext.create(chain[-1]))

    assert exc_info.value is error
    assert calls == 1
    events = chain[0].list_for_tenant("tenant-1")
    assert len(events) == 9
    assert events[-1].event_type == (
        "communication.response_target_resolved"
    )
