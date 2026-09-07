from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest

from mike_app.communication.delivery_request import (
    ConversationDeliveryRequestPlanner,
)
from mike_app.communication.readiness import (
    ConversationResponseReadinessEvaluator,
)
from mike_app.handlers.conversation_delivery_requested import (
    ConversationDeliveryRequestedHandler,
)
from mike_app.handlers.conversation_response_ready import (
    ConversationResponseReadyHandler,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry
from tests.test_conversation_response_ready_handler import (
    build_nine_event_chain,
)


def build_ten_event_chain(tenant_id: str = "tenant-1"):
    chain = build_nine_event_chain(tenant_id=tenant_id)
    ready_handler = ConversationResponseReadyHandler(
        chain[2],
        ConversationResponseReadinessEvaluator(),
        RuntimeDispatcher(RuntimeHandlerRegistry()),
    )
    ready_handler(RuntimeContext.create(chain[-1]))
    ready = chain[0].list_for_tenant(tenant_id)[-1]
    return chain, ready


def make_handler(tenant_id: str = "tenant-1"):
    chain, ready = build_ten_event_chain(tenant_id)
    handler = ConversationDeliveryRequestedHandler(
        chain[2], ConversationDeliveryRequestPlanner()
    )
    return chain, ready, handler


def test_creates_exact_terminal_event_and_atomic_outbox_snapshot() -> None:
    chain, ready, handler = make_handler()
    before = chain[0].list_for_tenant("tenant-1")

    result = handler(RuntimeContext.create(ready))

    events = chain[0].list_for_tenant("tenant-1")
    assert result is None
    assert len(events) == 11
    assert events[:10] == before
    delivery = events[10]
    assert delivery.event_type == "communication.delivery_requested"
    assert delivery.to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "response_ready_event_id": str(ready.event_id),
        "channel": ready.payload["channel"],
        "external_conversation_id": ready.payload["external_conversation_id"],
        "outbound_sender_id": ready.payload["outbound_sender_id"],
        "outbound_recipient_id": ready.payload["outbound_recipient_id"],
        "idempotency_key": str(ready.event_id),
        "request_method": "transactional_outbox",
    }
    assert delivery.correlation_id == ready.correlation_id
    assert delivery.causation_id == str(ready.event_id)
    entries = chain[2].list_outbox_entries("tenant-1")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.delivery_request_event_id == delivery.event_id
    assert entry.response_ready_event_id == ready.event_id
    assert entry.status == "pending"
    for field_name in (
        "channel", "external_conversation_id", "outbound_sender_id",
        "outbound_recipient_id", "response_type", "language", "text",
    ):
        assert getattr(entry, field_name) == ready.payload[field_name]
    assert chain[2].get_outbox_entry("tenant-2", entry.outbox_id) is None


def test_accepts_equivalent_reconstructed_response_ready_event() -> None:
    chain, ready, handler = make_handler()
    reconstructed = Event(
        event_id=ready.event_id,
        tenant_id=ready.tenant_id,
        event_type=ready.event_type,
        occurred_at=ready.occurred_at,
        payload=ready.to_dict()["payload"],
        correlation_id=ready.correlation_id,
        causation_id=ready.causation_id,
        schema_version=ready.schema_version,
    )
    handler(RuntimeContext.create(reconstructed))
    assert len(chain[0].list_for_tenant("tenant-1")) == 11


def test_repeated_response_is_explicit_conflict_without_partial_state() -> None:
    chain, ready, handler = make_handler()
    handler(RuntimeContext.create(ready))
    before_events = chain[0].list_for_tenant("tenant-1")
    before_outbox = chain[2].list_outbox_entries("tenant-1")

    with pytest.raises(ValueError, match="exactly ten"):
        handler(RuntimeContext.create(ready))

    assert chain[0].list_for_tenant("tenant-1") == before_events
    assert chain[2].list_outbox_entries("tenant-1") == before_outbox


@pytest.mark.parametrize(
    ("position", "field_name"),
    [(1, "source_event_id"), (9, "source_event_id")],
)
def test_inconsistent_reference_preserves_ten_events(
    position: int, field_name: str
) -> None:
    chain, ready, handler = make_handler()
    event = chain[0].list_for_tenant("tenant-1")[position]
    payload = event.to_dict()["payload"]
    payload[field_name] = "wrong"
    object.__setattr__(event, "payload", payload)

    with pytest.raises(ValueError, match=field_name):
        handler(RuntimeContext.create(ready))

    assert len(chain[0].list_for_tenant("tenant-1")) == 10
    assert chain[2].list_outbox_entries("tenant-1") == ()


def test_planner_divergence_preserves_ten_events() -> None:
    chain, ready, _ = make_handler()

    class AlteringPlanner(ConversationDeliveryRequestPlanner):
        def plan(self, **kwargs: object):
            return replace(super().plan(**kwargs), text="altered")

    handler = ConversationDeliveryRequestedHandler(chain[2], AlteringPlanner())
    with pytest.raises(ValueError, match="snapshot"):
        handler(RuntimeContext.create(ready))
    assert len(chain[0].list_for_tenant("tenant-1")) == 10
    assert chain[2].list_outbox_entries("tenant-1") == ()


def test_concurrent_repetition_has_one_winner_and_no_partial_duplicate() -> None:
    chain, ready, handler = make_handler()

    def invoke() -> object:
        try:
            handler(RuntimeContext.create(ready))
            return "committed"
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: invoke(), range(2)))

    assert outcomes.count("committed") == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1
    assert len(chain[0].list_for_tenant("tenant-1")) == 11
    assert len(chain[2].list_outbox_entries("tenant-1")) == 1


def test_in_memory_instances_do_not_share_outbox_entries() -> None:
    first_chain, first_ready, first_handler = make_handler("tenant-isolated")
    second_chain, _, _ = make_handler("tenant-isolated")

    first_handler(RuntimeContext.create(first_ready))

    assert len(first_chain[2].list_outbox_entries("tenant-isolated")) == 1
    assert second_chain[2].list_outbox_entries("tenant-isolated") == ()


def test_coordinator_ordinary_append_rejects_delivery_requested() -> None:
    chain, _, _ = make_handler()
    episode = chain[2].list_episodes("tenant-1")[0]
    delivery = Event.create(
        "tenant-1", "communication.delivery_requested"
    )

    with pytest.raises(ValueError, match="atomic outbox append"):
        chain[2].append_to_episode(episode.episode_id, delivery)

    assert chain[2].get_episode("tenant-1", episode.episode_id) == episode
    assert chain[2].get_event("tenant-1", delivery.event_id) is None


@pytest.mark.parametrize("field_name", ["correlation_id", "causation_id"])
def test_altered_preceding_trace_envelope_preserves_ten_events(
    field_name: str,
) -> None:
    chain, ready, handler = make_handler()
    object.__setattr__(ready, field_name, "altered")

    with pytest.raises(ValueError, match=field_name):
        handler(RuntimeContext.create(ready))

    assert len(chain[0].list_for_tenant("tenant-1")) == 10
    assert chain[2].list_outbox_entries("tenant-1") == ()
