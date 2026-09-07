from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

import pytest

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.episode_journal import EpisodeConcurrencyConflictError, EpisodeJournal
from mike_app.runtime.event import Event


JournalFactory = Callable[[], EpisodeJournal]


def assert_atomic_create_and_append(factory: JournalFactory) -> None:
    journal = factory()
    first = Event.create("contract-tenant", "contract.initial", {"nested": [1, {"ok": True}]})
    episode = CognitiveEpisode.create(first)
    assert journal.create_episode_with_event(episode, first) == episode
    second = Event.create("contract-tenant", "contract.next")
    updated = journal.append_event(
        "contract-tenant", episode.episode_id, second, episode.event_ids
    )
    assert updated.event_ids == (first.event_id, second.event_id)
    assert journal.list_events("contract-tenant") == (first, second)
    assert journal.get_episode("contract-tenant", episode.episode_id) == updated


def assert_exact_version_conflicts(factory: JournalFactory) -> None:
    mutations = (
        lambda ids: ids[:-1],
        lambda ids: ids + (uuid.uuid4(),),
        lambda ids: tuple(reversed(ids)),
        lambda ids: (uuid.uuid4(),) + ids[1:],
    )
    for index, mutate in enumerate(mutations):
        journal = factory()
        first = Event.create(f"version-{index}", "contract.initial")
        episode = CognitiveEpisode.create(first)
        journal.create_episode_with_event(episode, first)
        second = Event.create(f"version-{index}", "contract.second")
        current = journal.append_event(
            f"version-{index}", episode.episode_id, second, episode.event_ids
        )
        losing = Event.create(f"version-{index}", "contract.losing")
        with pytest.raises(EpisodeConcurrencyConflictError):
            journal.append_event(
                f"version-{index}", episode.episode_id, losing, mutate(current.event_ids)
            )
        assert journal.get_event(f"version-{index}", losing.event_id) is None
        assert journal.get_episode(f"version-{index}", episode.episode_id) == current


def assert_tenant_isolation_and_order(factory: JournalFactory) -> None:
    journal = factory()
    first_a = Event.create("tenant-a", "contract.match")
    episode_a = CognitiveEpisode.create(first_a)
    journal.create_episode_with_event(episode_a, first_a)
    first_b = Event.create("tenant-b", "contract.match")
    episode_b = CognitiveEpisode.create(first_b)
    journal.create_episode_with_event(episode_b, first_b)
    second_a = Event.create("tenant-a", "contract.other")
    updated_a = journal.append_event(
        "tenant-a", episode_a.episode_id, second_a, episode_a.event_ids
    )
    third_a = Event.create("tenant-a", "contract.match")
    journal.append_event(
        "tenant-a", episode_a.episode_id, third_a, updated_a.event_ids
    )
    assert journal.get_event("tenant-b", first_a.event_id) is None
    assert journal.get_episode("tenant-b", episode_a.episode_id) is None
    foreign = Event.create("tenant-b", "contract.foreign")
    with pytest.raises(ValueError, match="episode not found"):
        journal.append_event("tenant-b", episode_a.episode_id, foreign, episode_a.event_ids)
    assert journal.get_event("tenant-b", foreign.event_id) is None
    assert journal.list_events("tenant-a") == (first_a, second_a, third_a)
    assert journal.list_events("tenant-a", "contract.match") == (first_a, third_a)
    assert journal.list_events("tenant-b") == (first_b,)


def build_ten_event_episode(
    journal: EpisodeJournal,
    tenant_id: str,
    trace_override: tuple[int, str] | None = None,
) -> tuple[CognitiveEpisode, tuple[Event, ...]]:
    event_types = (
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
        "conversation.response_request",
        "conversation.response_generated",
        "conversation.response_validated",
        "communication.response_target_resolved",
        "conversation.response_ready",
    )
    events: list[Event] = []

    def trace_kwargs(position: int) -> dict[str, str]:
        if trace_override is None or trace_override[0] != position:
            return {}
        return {trace_override[1]: "altered"}

    first = Event.create(
        tenant_id,
        event_types[0],
        {
            "channel": "development",
            "external_message_id": "message",
            "external_conversation_id": "conversation",
            "sender_id": "sender",
            "recipient_id": "recipient",
        },
        **trace_kwargs(0),
    )
    episode = CognitiveEpisode.create(first)
    journal.create_episode_with_event(episode, first)
    events.append(first)
    reference_fields = (
        ("source_event_id", 0),
        ("accepted_event_id", 1),
        ("perceived_event_id", 2),
        ("normalized_event_id", 3),
        ("next_action_event_id", 4),
        ("response_request_event_id", 5),
        ("response_generated_event_id", 6),
    )
    for position, event_type in enumerate(event_types[1:8], start=1):
        payload = {
            field_name: str(events[event_position].event_id)
            for field_name, event_position in reference_fields[:position]
        }
        if position == 5:
            payload.update({
                "response_type": "answer",
                "target_language": "es",
            })
        elif position == 6:
            payload.update({
                "response_type": "answer",
                "language": "es",
                "text": "  texto exacto  ",
                "generation_method": "deterministic_template",
            })
        elif position == 7:
            payload.update({
                "response_type": "answer",
                "language": "es",
                "text": "  texto exacto  ",
                "generation_method": "deterministic_template",
                "validation_method": "deterministic_contract",
            })
        event = Event.create(
            tenant_id, event_type, payload, **trace_kwargs(position)
        )
        episode = journal.append_event(
            tenant_id, episode.episode_id, event, episode.event_ids
        )
        events.append(event)
    target = Event.create(
        tenant_id,
        event_types[8],
        {
            "source_event_id": str(events[0].event_id),
            "response_validated_event_id": str(events[7].event_id),
            "channel": "development",
            "external_message_id": "message",
            "external_conversation_id": "conversation",
            "outbound_sender_id": "recipient",
            "outbound_recipient_id": "sender",
            "resolution_method": "reply_to_source",
        },
        **trace_kwargs(8),
    )
    episode = journal.append_event(
        tenant_id, episode.episode_id, target, episode.event_ids
    )
    events.append(target)
    ready = Event.create(
        tenant_id,
        event_types[9],
        {
            "source_event_id": str(events[0].event_id),
            "response_validated_event_id": str(events[7].event_id),
            "response_target_resolved_event_id": str(events[8].event_id),
            "channel": "development",
            "external_conversation_id": "conversation",
            "outbound_sender_id": "recipient",
            "outbound_recipient_id": "sender",
            "response_type": "answer",
            "language": "es",
            "text": "  texto exacto  ",
            "readiness_method": "validated_response_with_resolved_target",
        },
        **trace_kwargs(9),
    )
    episode = journal.append_event(
        tenant_id, episode.episode_id, ready, episode.event_ids
    )
    events.append(ready)
    return episode, tuple(events)


def assert_atomic_outbox_append(factory: JournalFactory) -> None:
    journal = factory()
    tenant_id = "outbox-contract"
    episode, events = build_ten_event_episode(journal, tenant_id)
    ready = events[-1]
    delivery = Event.create(
        tenant_id,
        "communication.delivery_requested",
        {
            "source_event_id": str(events[0].event_id),
            "response_ready_event_id": str(ready.event_id),
            "channel": "development",
            "external_conversation_id": "conversation",
            "outbound_sender_id": "recipient",
            "outbound_recipient_id": "sender",
            "idempotency_key": str(ready.event_id),
            "request_method": "transactional_outbox",
        },
        correlation_id=ready.correlation_id,
        causation_id=str(ready.event_id),
    )
    entry = DeliveryOutboxEntry(
        outbox_id=uuid.uuid4(),
        tenant_id=tenant_id,
        episode_id=episode.episode_id,
        delivery_request_event_id=delivery.event_id,
        response_ready_event_id=ready.event_id,
        idempotency_key=str(ready.event_id),
        channel="development",
        external_conversation_id="conversation",
        outbound_sender_id="recipient",
        outbound_recipient_id="sender",
        response_type="answer",
        language="es",
        text="  texto exacto  ",
        status="pending",
        created_at=datetime.now(timezone.utc),
        schema_version=1,
    )
    updated = journal.append_event_with_outbox(
        tenant_id,
        episode.episode_id,
        delivery,
        episode.event_ids,
        entry,
    )
    assert updated.event_ids == episode.event_ids + (delivery.event_id,)
    assert journal.get_event(tenant_id, delivery.event_id) == delivery
    assert journal.get_outbox_entry(tenant_id, entry.outbox_id) == entry
    assert journal.list_outbox_entries(tenant_id) == (entry,)
    assert journal.get_outbox_entry("other-tenant", entry.outbox_id) is None


def assert_delivery_requested_requires_atomic_append(
    factory: JournalFactory,
) -> None:
    journal = factory()
    tenant_id = "protected-append"
    first = Event.create(tenant_id, "message.received")
    episode = CognitiveEpisode.create(first)
    journal.create_episode_with_event(episode, first)
    delivery = Event.create(
        tenant_id,
        "communication.delivery_requested",
    )

    with pytest.raises(ValueError, match="atomic outbox append"):
        journal.append_event(
            tenant_id,
            episode.episode_id,
            delivery,
            episode.event_ids,
        )

    assert journal.get_event(tenant_id, delivery.event_id) is None
    assert journal.get_episode(tenant_id, episode.episode_id) == episode
    assert journal.list_outbox_entries(tenant_id) == ()


def assert_canonical_outbox_order(factory: JournalFactory) -> None:
    journal = factory()
    tenant_id = "outbox-order"
    common_time = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    entries: list[DeliveryOutboxEntry] = []

    for index, (created_at, outbox_id) in enumerate((
        (common_time, uuid.UUID(int=3)),
        (common_time.replace(hour=11), uuid.UUID(int=2)),
        (common_time, uuid.UUID(int=1)),
    )):
        episode, events = build_ten_event_episode(journal, tenant_id)
        ready = events[-1]
        delivery = Event.create(
            tenant_id,
            "communication.delivery_requested",
            {
                "source_event_id": str(events[0].event_id),
                "response_ready_event_id": str(ready.event_id),
                "channel": "development",
                "external_conversation_id": "conversation",
                "outbound_sender_id": "recipient",
                "outbound_recipient_id": "sender",
                "idempotency_key": str(ready.event_id),
                "request_method": "transactional_outbox",
            },
            correlation_id=ready.correlation_id,
            causation_id=str(ready.event_id),
        )
        entry = DeliveryOutboxEntry(
            outbox_id=outbox_id,
            tenant_id=tenant_id,
            episode_id=episode.episode_id,
            delivery_request_event_id=delivery.event_id,
            response_ready_event_id=ready.event_id,
            idempotency_key=str(ready.event_id),
            channel="development",
            external_conversation_id="conversation",
            outbound_sender_id="recipient",
            outbound_recipient_id="sender",
            response_type="answer",
            language="es",
            text="  texto exacto  ",
            status="pending",
            created_at=created_at,
            schema_version=1,
        )
        journal.append_event_with_outbox(
            tenant_id,
            episode.episode_id,
            delivery,
            episode.event_ids,
            entry,
        )
        entries.append(entry)

    assert journal.list_outbox_entries(tenant_id) == (
        entries[1],
        entries[2],
        entries[0],
    )


def assert_altered_trace_is_rejected(factory: JournalFactory) -> None:
    for field_name in ("correlation_id", "causation_id"):
        journal = factory()
        tenant_id = f"altered-{field_name}"
        episode, events = build_ten_event_episode(
            journal,
            tenant_id,
            trace_override=(9, field_name),
        )
        ready = events[-1]
        delivery = Event.create(
            tenant_id,
            "communication.delivery_requested",
            {
                "source_event_id": str(events[0].event_id),
                "response_ready_event_id": str(ready.event_id),
                "channel": "development",
                "external_conversation_id": "conversation",
                "outbound_sender_id": "recipient",
                "outbound_recipient_id": "sender",
                "idempotency_key": str(ready.event_id),
                "request_method": "transactional_outbox",
            },
            correlation_id=ready.correlation_id,
            causation_id=str(ready.event_id),
        )
        entry = DeliveryOutboxEntry(
            outbox_id=uuid.uuid4(),
            tenant_id=tenant_id,
            episode_id=episode.episode_id,
            delivery_request_event_id=delivery.event_id,
            response_ready_event_id=ready.event_id,
            idempotency_key=str(ready.event_id),
            channel="development",
            external_conversation_id="conversation",
            outbound_sender_id="recipient",
            outbound_recipient_id="sender",
            response_type="answer",
            language="es",
            text="  texto exacto  ",
            status="pending",
            created_at=datetime.now(timezone.utc),
            schema_version=1,
        )

        with pytest.raises(ValueError, match=field_name):
            journal.append_event_with_outbox(
                tenant_id,
                episode.episode_id,
                delivery,
                episode.event_ids,
                entry,
            )

        assert journal.get_event(tenant_id, delivery.event_id) is None
        assert journal.list_outbox_entries(tenant_id) == ()
