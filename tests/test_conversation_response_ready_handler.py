from dataclasses import replace
import uuid

import pytest

from mike_app.communication.readiness import (
    ConversationResponseReadinessEvaluator,
    ReadyConversationResponse,
)
from mike_app.handlers.conversation_response_ready import (
    ConversationResponseReadyHandler,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry
from tests.test_conversation_response_target_resolved_handler import (
    build_eight_event_chain,
)


class SpyEvaluator(ConversationResponseReadinessEvaluator):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def evaluate(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return super().evaluate(**kwargs)


def build_nine_event_chain(*, tenant_id: str = "tenant-1"):
    chain = build_eight_event_chain(tenant_id=tenant_id)
    source = chain[4]
    validated = chain[-1]
    target = Event.create(
        tenant_id=tenant_id,
        event_type="communication.response_target_resolved",
        payload={
            "source_event_id": str(source.event_id),
            "response_validated_event_id": str(validated.event_id),
            "channel": source.payload["channel"],
            "external_message_id": source.payload["external_message_id"],
            "external_conversation_id": source.payload[
                "external_conversation_id"
            ],
            "outbound_sender_id": source.payload["recipient_id"],
            "outbound_recipient_id": source.payload["sender_id"],
            "resolution_method": "reply_to_source",
        },
    )
    chain[2].append_to_episode(chain[3].episode_id, target)
    return chain + (target,)


def make_handler(*, tenant_id: str = "tenant-1"):
    chain = build_nine_event_chain(tenant_id=tenant_id)
    evaluator = SpyEvaluator()
    handler = ConversationResponseReadyHandler(
        chain[2], evaluator, RuntimeDispatcher(RuntimeHandlerRegistry())
    )
    return chain, evaluator, handler


def test_creates_exact_terminal_tenth_event_from_authoritative_events() -> None:
    chain, evaluator, handler = make_handler()
    events_before = chain[0].list_for_tenant("tenant-1")
    source, validated, target = events_before[0], events_before[7], events_before[8]

    result = handler(RuntimeContext.create(target))

    events = chain[0].list_for_tenant("tenant-1")
    ready = events[-1]
    assert result is None
    assert len(evaluator.calls) == 1
    assert len(events) == 10
    assert ready.event_type == "conversation.response_ready"
    assert ready.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "response_validated_event_id": str(validated.event_id),
        "response_target_resolved_event_id": str(target.event_id),
        "response_type": validated.payload["response_type"],
        "language": validated.payload["language"],
        "text": validated.payload["text"],
        "channel": target.payload["channel"],
        "external_message_id": target.payload["external_message_id"],
        "external_conversation_id": target.payload[
            "external_conversation_id"
        ],
        "outbound_sender_id": target.payload["outbound_sender_id"],
        "outbound_recipient_id": target.payload["outbound_recipient_id"],
        "readiness_method": "validated_response_with_resolved_target",
    }
    forbidden = {
        "is_ready", "readiness_status", "violations", "delivery_request_id",
        "idempotency_key", "delivery_status", "sent_at", "delivered_at",
        "provider_message_id", "accepted_event_id", "perceived_event_id",
        "normalized_event_id", "next_action_event_id",
        "response_request_event_id", "response_generated_event_id",
        "generation_method", "validation_method", "resolution_method",
        "tenant_id", "episode_id",
    }
    assert forbidden.isdisjoint(ready.payload)
    episode = chain[1].get_by_id("tenant-1", chain[3].episode_id)
    assert episode is not None
    assert episode.event_ids == tuple(event.event_id for event in events)


def test_accepts_equivalent_reconstructed_target_event() -> None:
    chain, evaluator, handler = make_handler()
    stored = chain[-1]
    reconstructed = Event(
        event_id=stored.event_id,
        tenant_id=stored.tenant_id,
        event_type=stored.event_type,
        occurred_at=stored.occurred_at,
        payload=stored.to_dict()["payload"],
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        schema_version=stored.schema_version,
    )

    assert reconstructed is not stored
    handler(RuntimeContext.create(reconstructed))

    events = chain[0].list_for_tenant("tenant-1")
    assert len(evaluator.calls) == 1
    assert len(events) == 10
    assert events[-1].payload["response_target_resolved_event_id"] == str(stored.event_id)


def test_preserves_content_and_target_whitespace_exactly() -> None:
    chain, _, handler = make_handler()
    validated = chain[0].list_for_tenant("tenant-1")[7]
    target = chain[-1]
    validated_payload = validated.to_dict()["payload"]
    validated_payload["text"] = "  texto\nexacto  "
    generated = chain[0].list_for_tenant("tenant-1")[6]
    generated_payload = generated.to_dict()["payload"]
    generated_payload["text"] = "  texto\nexacto  "
    object.__setattr__(validated, "payload", validated_payload)
    object.__setattr__(generated, "payload", generated_payload)
    target_payload = target.to_dict()["payload"]
    source = chain[0].list_for_tenant("tenant-1")[0]
    source_payload = source.to_dict()["payload"]
    for field_name, value in {
        "channel": " channel ",
        "external_message_id": " message ",
        "external_conversation_id": " conversation ",
    }.items():
        source_payload[field_name] = value
        target_payload[field_name] = value
    source_payload["recipient_id"] = " sender "
    source_payload["sender_id"] = " recipient "
    target_payload["outbound_sender_id"] = " sender "
    target_payload["outbound_recipient_id"] = " recipient "
    object.__setattr__(source, "payload", source_payload)
    object.__setattr__(target, "payload", target_payload)

    handler(RuntimeContext.create(target))

    ready = chain[0].list_for_tenant("tenant-1")[-1].payload
    assert ready["text"] == "  texto\nexacto  "
    assert ready["channel"] == " channel "
    assert ready["outbound_sender_id"] == " sender "
    assert ready["outbound_recipient_id"] == " recipient "


@pytest.mark.parametrize("position", range(9))
def test_wrong_type_at_every_position_preserves_nine(position: int) -> None:
    chain, evaluator, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[position]
    object.__setattr__(event, "event_type", "wrong.event")

    with pytest.raises(ValueError):
        handler(RuntimeContext.create(chain[-1]))

    assert evaluator.calls == []
    assert len(chain[0].list_for_tenant("tenant-1")) == 9


@pytest.mark.parametrize("position", range(9))
def test_tenant_mismatch_at_every_position_preserves_nine(position: int) -> None:
    chain, evaluator, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[position]
    object.__setattr__(event, "tenant_id", "tenant-other")

    with pytest.raises(ValueError):
        handler(RuntimeContext.create(chain[-1]))

    assert evaluator.calls == []
    assert all(
        event.event_type != "conversation.response_ready"
        for event in chain[0].list_for_tenant("tenant-1")
    )


@pytest.mark.parametrize("mutation", ["missing", "additional", "reordered"])
def test_requires_exactly_nine_ordered_events(mutation: str) -> None:
    chain, evaluator, handler = make_handler()
    episode = chain[1].get_by_id("tenant-1", chain[3].episode_id)
    assert episode is not None
    if mutation == "missing":
        event_ids = episode.event_ids[:-1]
    elif mutation == "additional":
        event_ids = episode.event_ids + (uuid.uuid4(),)
    else:
        event_ids = episode.event_ids[:7] + (
            episode.event_ids[8], episode.event_ids[7]
        )
    chain[2]._episode_journal._episodes_by_id[episode.episode_id] = replace(
        episode, event_ids=event_ids
    )

    with pytest.raises(ValueError, match="Episode|ninth"):
        handler(RuntimeContext.create(chain[-1]))

    assert evaluator.calls == []


@pytest.mark.parametrize(
    ("position", "field_name"),
    [
        (1, "source_event_id"), (2, "accepted_event_id"),
        (3, "perceived_event_id"), (4, "normalized_event_id"),
        (5, "next_action_event_id"), (6, "response_request_event_id"),
        (7, "response_generated_event_id"),
        (8, "source_event_id"),
        (8, "response_validated_event_id"),
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "crossed"])
def test_missing_or_crossed_references_preserve_nine(
    position: int, field_name: str, mutation: str
) -> None:
    chain, evaluator, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[position]
    payload = event.to_dict()["payload"]
    if mutation == "missing":
        payload.pop(field_name)
    else:
        payload[field_name] = str(uuid.uuid4())
    object.__setattr__(event, "payload", payload)

    with pytest.raises(ValueError, match=field_name):
        handler(RuntimeContext.create(chain[-1]))

    assert evaluator.calls == []
    assert len(chain[0].list_for_tenant("tenant-1")) == 9


@pytest.mark.parametrize(
    ("event_position", "field_name"),
    [
        (7, "text"),
        (8, "channel"),
        (8, "external_message_id"),
        (8, "external_conversation_id"),
        (8, "outbound_sender_id"),
        (8, "outbound_recipient_id"),
        (8, "resolution_method"),
    ],
)
def test_invalid_or_inconsistent_authoritative_payload_preserves_nine(
    event_position: int, field_name: str
) -> None:
    chain, evaluator, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[event_position]
    payload = event.to_dict()["payload"]
    payload[field_name] = "wrong"
    object.__setattr__(event, "payload", payload)

    with pytest.raises(ValueError):
        handler(RuntimeContext.create(chain[-1]))

    assert evaluator.calls == []
    assert len(chain[0].list_for_tenant("tenant-1")) == 9


def test_evaluator_failure_preserves_nine_without_retry_or_rejection() -> None:
    chain, evaluator, handler = make_handler()
    evaluator.error = RuntimeError("evaluation failed")

    with pytest.raises(RuntimeError, match="evaluation failed"):
        handler(RuntimeContext.create(chain[-1]))

    events = chain[0].list_for_tenant("tenant-1")
    assert len(evaluator.calls) == 1
    assert len(events) == 9
    assert all("reject" not in event.event_type for event in events)


def test_altered_evaluator_snapshot_is_rejected_before_storage() -> None:
    chain, evaluator, handler = make_handler()

    def altered_snapshot(**kwargs: object) -> ReadyConversationResponse:
        return ReadyConversationResponse(
            **{**kwargs, "text": "altered"},
            readiness_method="validated_response_with_resolved_target",
        )

    evaluator.evaluate = altered_snapshot

    with pytest.raises(ValueError, match="authoritative Events"):
        handler(RuntimeContext.create(chain[-1]))

    events = chain[0].list_for_tenant("tenant-1")
    assert len(events) == 9
    assert all(
        event.event_type != "conversation.response_ready"
        for event in events
    )


def test_wrong_event_and_unknown_episode_are_rejected() -> None:
    _, _, handler = make_handler()
    wrong = Event.create(
        tenant_id="tenant-1", event_type="conversation.response_validated"
    )
    with pytest.raises(ValueError, match="response_target_resolved"):
        handler(RuntimeContext.create(wrong))
    unknown = Event.create(
        tenant_id="tenant-1",
        event_type="communication.response_target_resolved",
    )
    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(unknown))


def test_two_tenants_do_not_mix_content_or_targets() -> None:
    first, _, first_handler = make_handler(tenant_id="tenant-one")
    second, _, second_handler = make_handler(tenant_id="tenant-two")

    first_handler(RuntimeContext.create(first[-1]))
    second_handler(RuntimeContext.create(second[-1]))

    first_ready = first[0].list_for_tenant("tenant-one")[-1]
    second_ready = second[0].list_for_tenant("tenant-two")[-1]
    assert first_ready.payload["outbound_sender_id"] == "tenant-one"
    assert second_ready.payload["outbound_sender_id"] == "tenant-two"
    assert first[2].get_event("tenant-one", second_ready.event_id) is None
    assert second[2].get_event("tenant-two", first_ready.event_id) is None
