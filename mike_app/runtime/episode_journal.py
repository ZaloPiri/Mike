from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Protocol

from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.event import Event
from mike_app.runtime.delivery_receipt import DeliveryReceipt, ReceiptConflictError, snapshot_hash


class EpisodeConcurrencyConflictError(RuntimeError):
    pass


class EpisodeJournal(Protocol):
    def create_episode_with_event(
        self,
        episode: CognitiveEpisode,
        event: Event,
    ) -> CognitiveEpisode: ...

    def append_event(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
    ) -> CognitiveEpisode: ...

    def append_event_with_outbox(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
        outbox_entry: DeliveryOutboxEntry,
    ) -> CognitiveEpisode: ...

    def get_event(
        self, tenant_id: str, event_id: uuid.UUID
    ) -> Event | None: ...

    def get_episode(
        self, tenant_id: str, episode_id: uuid.UUID
    ) -> CognitiveEpisode | None: ...

    def list_events(
        self, tenant_id: str, event_type: str | None = None
    ) -> tuple[Event, ...]: ...

    def list_episodes(
        self, tenant_id: str
    ) -> tuple[CognitiveEpisode, ...]: ...

    def get_outbox_entry(
        self, tenant_id: str, outbox_id: uuid.UUID
    ) -> DeliveryOutboxEntry | None: ...

    def list_outbox_entries(
        self, tenant_id: str
    ) -> tuple[DeliveryOutboxEntry, ...]: ...

    def total_event_count(self) -> int: ...

    def total_episode_count(self) -> int: ...

    def claim_one_delivery(self, tenant_id: str, now: datetime, lease_seconds: int) -> DeliveryOutboxEntry | None: ...
    def get_delivery_receipt(self, tenant_id: str, idempotency_key: str) -> DeliveryReceipt | None: ...
    def save_delivery_receipt(self, receipt: DeliveryReceipt, claim_token: uuid.UUID) -> DeliveryReceipt: ...
    def finalize_delivery(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, receipt: DeliveryReceipt) -> DeliveryOutboxEntry: ...
    def fail_delivery(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, now: datetime, error: str, retry_at: datetime | None) -> DeliveryOutboxEntry: ...
    def start_adapter_attempt(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, now: datetime) -> DeliveryOutboxEntry: ...


class InMemoryEpisodeJournal:
    def __init__(self) -> None:
        self._events_by_id: dict[uuid.UUID, Event] = {}
        self._tenant_events: dict[str, list[Event]] = {}
        self._episodes_by_id: dict[uuid.UUID, CognitiveEpisode] = {}
        self._tenant_episode_ids: dict[str, list[uuid.UUID]] = {}
        self._outbox_by_id: dict[uuid.UUID, DeliveryOutboxEntry] = {}
        self._tenant_outbox: dict[str, list[DeliveryOutboxEntry]] = {}
        self._outbox_delivery_event_ids: set[uuid.UUID] = set()
        self._outbox_response_ready_ids: set[uuid.UUID] = set()
        self._outbox_idempotency_keys: set[str] = set()
        self._receipts_by_key: dict[str, DeliveryReceipt] = {}
        self._lock = Lock()

    def create_episode_with_event(
        self,
        episode: CognitiveEpisode,
        event: Event,
    ) -> CognitiveEpisode:
        if not isinstance(episode, CognitiveEpisode):
            raise TypeError("episode must be a CognitiveEpisode")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        _reject_delivery_requested_for_ordinary_append(event)
        _reject_delivery_accepted_for_ordinary_append(event)
        with self._lock:
            if episode.tenant_id != event.tenant_id:
                raise ValueError("event tenant does not match episode tenant")
            if episode.event_ids != (event.event_id,):
                raise ValueError(
                    "initial episode must reference exactly its initial Event"
                )
            if event.event_id in self._events_by_id:
                raise ValueError("duplicate event_id")
            if episode.episode_id in self._episodes_by_id:
                raise ValueError("episode_id already exists")

            self._events_by_id[event.event_id] = event
            self._tenant_events.setdefault(event.tenant_id, []).append(event)
            self._episodes_by_id[episode.episode_id] = episode
            self._tenant_episode_ids.setdefault(
                episode.tenant_id, []
            ).append(episode.episode_id)
            return episode

    def append_event(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
    ) -> CognitiveEpisode:
        self._validate_tenant_id(tenant_id)
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        _reject_delivery_requested_for_ordinary_append(event)
        _reject_delivery_accepted_for_ordinary_append(event)
        if not isinstance(expected_event_ids, tuple) or not all(
            isinstance(event_id, uuid.UUID)
            for event_id in expected_event_ids
        ):
            raise TypeError("expected_event_ids must be a tuple of uuid.UUID")

        with self._lock:
            episode = self._episodes_by_id.get(episode_id)
            if episode is None or episode.tenant_id != tenant_id:
                raise ValueError("episode not found")
            if event.tenant_id != tenant_id:
                raise ValueError("event tenant does not match episode tenant")
            if episode.event_ids != expected_event_ids:
                raise EpisodeConcurrencyConflictError(
                    "episode event_ids do not match expected_event_ids"
                )
            if event.event_id in self._events_by_id:
                raise ValueError("duplicate event_id")
            if event.event_id in episode.event_ids:
                raise ValueError("event_id is already present")

            updated_episode = episode.add_event(event)
            self._events_by_id[event.event_id] = event
            self._tenant_events.setdefault(event.tenant_id, []).append(event)
            self._episodes_by_id[episode_id] = updated_episode
            return updated_episode

    def append_event_with_outbox(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
        outbox_entry: DeliveryOutboxEntry,
    ) -> CognitiveEpisode:
        self._validate_append_inputs(
            tenant_id, episode_id, event, expected_event_ids
        )
        if not isinstance(outbox_entry, DeliveryOutboxEntry):
            raise TypeError("outbox_entry must be a DeliveryOutboxEntry")
        with self._lock:
            episode = self._episodes_by_id.get(episode_id)
            if episode is None or episode.tenant_id != tenant_id:
                raise ValueError("episode not found")
            if episode.event_ids != expected_event_ids:
                raise EpisodeConcurrencyConflictError(
                    "episode event_ids do not match expected_event_ids"
                )
            if event.event_id in self._events_by_id:
                raise ValueError("duplicate event_id")
            self._validate_outbox_uniqueness(outbox_entry)
            preceding_events = tuple(
                self._events_by_id[event_id]
                for event_id in episode.event_ids
            )
            _validate_delivery_append(
                tenant_id,
                episode_id,
                preceding_events,
                event,
                outbox_entry,
            )
            updated_episode = episode.add_event(event)
            self._events_by_id[event.event_id] = event
            self._tenant_events.setdefault(tenant_id, []).append(event)
            self._episodes_by_id[episode_id] = updated_episode
            self._outbox_by_id[outbox_entry.outbox_id] = outbox_entry
            self._tenant_outbox.setdefault(tenant_id, []).append(outbox_entry)
            self._outbox_delivery_event_ids.add(
                outbox_entry.delivery_request_event_id
            )
            self._outbox_response_ready_ids.add(
                outbox_entry.response_ready_event_id
            )
            self._outbox_idempotency_keys.add(outbox_entry.idempotency_key)
            return updated_episode

    def get_event(
        self,
        tenant_id: str,
        event_id: uuid.UUID,
    ) -> Event | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(event_id, uuid.UUID):
            raise TypeError("event_id must be a uuid.UUID")
        with self._lock:
            event = self._events_by_id.get(event_id)
            if event is None or event.tenant_id != tenant_id:
                return None
            return event

    def get_episode(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
    ) -> CognitiveEpisode | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        with self._lock:
            episode = self._episodes_by_id.get(episode_id)
            if episode is None or episode.tenant_id != tenant_id:
                return None
            return episode

    def list_events(
        self,
        tenant_id: str,
        event_type: str | None = None,
    ) -> tuple[Event, ...]:
        self._validate_tenant_id(tenant_id)
        if event_type is not None:
            self._validate_event_type(event_type)
        with self._lock:
            events: Sequence[Event] = self._tenant_events.get(tenant_id, ())
            if event_type is None:
                return tuple(events)
            return tuple(
                event for event in events if event.event_type == event_type
            )

    def list_episodes(
        self,
        tenant_id: str,
    ) -> tuple[CognitiveEpisode, ...]:
        self._validate_tenant_id(tenant_id)
        with self._lock:
            return tuple(
                self._episodes_by_id[episode_id]
                for episode_id in self._tenant_episode_ids.get(tenant_id, ())
            )

    def get_outbox_entry(
        self,
        tenant_id: str,
        outbox_id: uuid.UUID,
    ) -> DeliveryOutboxEntry | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(outbox_id, uuid.UUID):
            raise TypeError("outbox_id must be a uuid.UUID")
        with self._lock:
            entry = self._outbox_by_id.get(outbox_id)
            if entry is None or entry.tenant_id != tenant_id:
                return None
            return entry

    def list_outbox_entries(
        self,
        tenant_id: str,
    ) -> tuple[DeliveryOutboxEntry, ...]:
        self._validate_tenant_id(tenant_id)
        with self._lock:
            return tuple(sorted(
                self._tenant_outbox.get(tenant_id, ()),
                key=lambda entry: (entry.created_at, entry.outbox_id),
            ))

    def count_events_for_tenant(self, tenant_id: str) -> int:
        return len(self.list_events(tenant_id))

    def count_episodes_for_tenant(self, tenant_id: str) -> int:
        return len(self.list_episodes(tenant_id))

    def total_event_count(self) -> int:
        with self._lock:
            return len(self._events_by_id)

    def total_episode_count(self) -> int:
        with self._lock:
            return len(self._episodes_by_id)

    def claim_one_delivery(self, tenant_id: str, now: datetime, lease_seconds: int) -> DeliveryOutboxEntry | None:
        self._validate_tenant_id(tenant_id)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        now = now.astimezone(timezone.utc)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        with self._lock:
            candidates = sorted(self._tenant_outbox.get(tenant_id, ()), key=lambda e: (e.created_at, e.outbox_id))
            for entry in candidates:
                eligible = entry.status == "pending" and (entry.next_attempt_at is None or entry.next_attempt_at <= now)
                expired = entry.status == "processing" and entry.lease_expires_at is not None and entry.lease_expires_at <= now
                if not (eligible or expired):
                    continue
                claimed = replace(entry, status="processing", claim_token=uuid.uuid4(), claimed_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
                self._replace_outbox(claimed)
                return claimed
            return None

    def get_delivery_receipt(self, tenant_id: str, idempotency_key: str) -> DeliveryReceipt | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        with self._lock:
            receipt = self._receipts_by_key.get(idempotency_key)
            return receipt if receipt is not None and receipt.tenant_id == tenant_id else None

    def save_delivery_receipt(self, receipt: DeliveryReceipt, claim_token: uuid.UUID) -> DeliveryReceipt:
        if not isinstance(receipt, DeliveryReceipt):
            raise TypeError("receipt must be a DeliveryReceipt")
        with self._lock:
            existing = self._receipts_by_key.get(receipt.idempotency_key)
            if existing is not None:
                if existing != receipt:
                    raise ReceiptConflictError("receipt idempotency conflict")
                return existing
            entry = self._outbox_by_id.get(receipt.outbox_id)
            now = datetime.now(timezone.utc)
            if entry is None or entry.tenant_id != receipt.tenant_id or entry.status != "processing" or entry.claim_token != claim_token or entry.lease_expires_at is None or entry.lease_expires_at <= now:
                raise ValueError("stale or invalid delivery claim")
            if receipt.snapshot_hash != snapshot_hash(entry):
                raise ValueError("receipt outbox not found")
            self._receipts_by_key[receipt.idempotency_key] = receipt
            return receipt

    def finalize_delivery(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, receipt: DeliveryReceipt) -> DeliveryOutboxEntry:
        if not isinstance(claim_token, uuid.UUID):
            raise TypeError("claim_token must be a uuid.UUID")
        with self._lock:
            entry = self._outbox_by_id.get(outbox_id)
            if entry is None or entry.tenant_id != tenant_id:
                raise ValueError("outbox not found")
            if entry.status == "completed":
                return entry
            now = datetime.now(timezone.utc)
            if entry.status != "processing" or entry.claim_token != claim_token or entry.lease_expires_at is None or entry.lease_expires_at <= now:
                raise ValueError("stale or invalid delivery claim")
            if not receipt.is_compatible(entry) or self._receipts_by_key.get(receipt.idempotency_key) != receipt:
                raise ValueError("receipt is not compatible with outbox")
            episode = self._episodes_by_id.get(entry.episode_id)
            if episode is None or len(episode.event_ids) != 11 or episode.event_ids[-1] != entry.delivery_request_event_id:
                raise ValueError("delivery request is not terminal in episode")
            preceding = tuple(self._events_by_id[event_id] for event_id in episode.event_ids[:-1])
            _validate_delivery_append(tenant_id, episode.episode_id, preceding, self._events_by_id[entry.delivery_request_event_id], entry)
            event = Event.create(tenant_id, "communication.delivery_accepted", {
                "schema_version": 1,
                "delivery_request_event_id": str(entry.delivery_request_event_id),
                "response_ready_event_id": str(entry.response_ready_event_id),
                "outbox_id": str(entry.outbox_id),
                "receipt_id": str(receipt.receipt_id),
                "acceptance_method": "development_adapter",
                "adapter": "development",
            }, causation_id=str(entry.delivery_request_event_id))
            delivery_event = self._events_by_id[entry.delivery_request_event_id]
            event = Event(
                event_id=event.event_id, tenant_id=tenant_id, event_type=event.event_type,
                occurred_at=event.occurred_at, payload=event.payload,
                correlation_id=delivery_event.correlation_id,
                causation_id=event.causation_id, schema_version=event.schema_version,
            )
            updated_episode = episode.add_event(event)
            completed = replace(entry, status="completed", delivery_accepted_event_id=event.event_id, claim_token=None, claimed_at=None, lease_expires_at=None)
            self._events_by_id[event.event_id] = event
            self._tenant_events.setdefault(tenant_id, []).append(event)
            self._episodes_by_id[episode.episode_id] = updated_episode
            self._replace_outbox(completed)
            return completed

    def fail_delivery(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, now: datetime, error: str, retry_at: datetime | None) -> DeliveryOutboxEntry:
        if not isinstance(error, str) or not error or len(error) > 512:
            raise ValueError("error must be a bounded non-empty string")
        with self._lock:
            entry = self._outbox_by_id.get(outbox_id)
            if entry is None or entry.tenant_id != tenant_id:
                raise ValueError("outbox not found")
            if entry.status != "processing" or entry.claim_token != claim_token or entry.lease_expires_at is None or entry.lease_expires_at <= now:
                raise ValueError("stale or invalid delivery claim")
            if entry.idempotency_key in self._receipts_by_key:
                raise ValueError("successful receipt already exists")
            status = "pending" if retry_at is not None and entry.adapter_attempt_count < 3 else "failed"
            updated = replace(entry, status=status, next_attempt_at=retry_at, last_error=error, claim_token=None, claimed_at=None, lease_expires_at=None)
            self._replace_outbox(updated)
            return updated

    def start_adapter_attempt(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, now: datetime) -> DeliveryOutboxEntry:
        with self._lock:
            entry = self._outbox_by_id.get(outbox_id)
            if entry is None or entry.tenant_id != tenant_id or entry.status != "processing" or entry.claim_token != claim_token or entry.lease_expires_at is None or entry.lease_expires_at <= now:
                raise ValueError("stale or invalid delivery claim")
            if entry.adapter_attempt_count >= 3:
                raise ValueError("maximum adapter attempts exceeded")
            updated = replace(entry, adapter_attempt_count=entry.adapter_attempt_count + 1)
            self._replace_outbox(updated)
            return updated

    def _replace_outbox(self, entry: DeliveryOutboxEntry) -> None:
        self._outbox_by_id[entry.outbox_id] = entry
        rows = self._tenant_outbox[entry.tenant_id]
        for index, old in enumerate(rows):
            if old.outbox_id == entry.outbox_id:
                rows[index] = entry
                return

    def _validate_outbox_uniqueness(
        self, entry: DeliveryOutboxEntry
    ) -> None:
        if entry.outbox_id in self._outbox_by_id:
            raise ValueError("duplicate outbox_id")
        if entry.delivery_request_event_id in self._outbox_delivery_event_ids:
            raise ValueError("duplicate delivery_request_event_id")
        if entry.response_ready_event_id in self._outbox_response_ready_ids:
            raise ValueError("duplicate response_ready_event_id")
        if entry.idempotency_key in self._outbox_idempotency_keys:
            raise ValueError("duplicate idempotency_key")

    @classmethod
    def _validate_append_inputs(
        cls,
        tenant_id: str,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
    ) -> None:
        cls._validate_tenant_id(tenant_id)
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        if not isinstance(expected_event_ids, tuple) or not all(
            isinstance(event_id, uuid.UUID)
            for event_id in expected_event_ids
        ):
            raise TypeError("expected_event_ids must be a tuple of uuid.UUID")

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not isinstance(tenant_id, str):
            raise TypeError("tenant_id must be a string")
        if not tenant_id or tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")

    @staticmethod
    def _validate_event_type(event_type: str) -> None:
        if not isinstance(event_type, str):
            raise TypeError("event_type must be a string")
        if not event_type or event_type.strip() == "":
            raise ValueError("event_type is required and must be non-empty")


class EventJournalView:
    __slots__ = ("__journal",)

    def __init__(self, journal: EpisodeJournal) -> None:
        self.__journal = journal

    def get_by_id(self, tenant_id: str, event_id: uuid.UUID) -> Event | None:
        return self.__journal.get_event(tenant_id, event_id)

    def list_for_tenant(
        self, tenant_id: str, event_type: str | None = None
    ) -> tuple[Event, ...]:
        return self.__journal.list_events(tenant_id, event_type)

    def count_for_tenant(self, tenant_id: str) -> int:
        return len(self.__journal.list_events(tenant_id))

    def total_count(self) -> int:
        return self.__journal.total_event_count()


class EpisodeJournalView:
    __slots__ = ("__journal",)

    def __init__(self, journal: EpisodeJournal) -> None:
        self.__journal = journal

    def get_by_id(
        self, tenant_id: str, episode_id: uuid.UUID
    ) -> CognitiveEpisode | None:
        return self.__journal.get_episode(tenant_id, episode_id)

    def list_for_tenant(
        self, tenant_id: str
    ) -> tuple[CognitiveEpisode, ...]:
        return self.__journal.list_episodes(tenant_id)

    def count_for_tenant(self, tenant_id: str) -> int:
        return len(self.__journal.list_episodes(tenant_id))

    def total_count(self) -> int:
        return self.__journal.total_episode_count()


def _validate_delivery_append(
    tenant_id: str,
    episode_id: uuid.UUID,
    preceding_events: tuple[Event, ...],
    event: Event,
    entry: DeliveryOutboxEntry,
) -> None:
    if len(preceding_events) != 10:
        raise ValueError("delivery request requires exactly ten preceding Events")
    expected_types = (
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
    for preceding, expected_type in zip(
        preceding_events, expected_types, strict=True
    ):
        if preceding.tenant_id != tenant_id:
            raise ValueError("Event tenant does not match Episode tenant")
        if preceding.event_type != expected_type:
            raise ValueError(f"Event must be {expected_type}")
        if preceding.schema_version != 1:
            raise ValueError("preceding Event schema_version does not match")
        if not isinstance(preceding.payload, Mapping):
            raise ValueError("Event payload must be a mapping")
        if preceding.correlation_id is not None:
            raise ValueError("preceding Event correlation_id does not match")
        if preceding.causation_id is not None:
            raise ValueError("preceding Event causation_id does not match")
    reference_ids = {
        "source_event_id": str(preceding_events[0].event_id),
        "accepted_event_id": str(preceding_events[1].event_id),
        "perceived_event_id": str(preceding_events[2].event_id),
        "normalized_event_id": str(preceding_events[3].event_id),
        "next_action_event_id": str(preceding_events[4].event_id),
        "response_request_event_id": str(preceding_events[5].event_id),
        "response_generated_event_id": str(preceding_events[6].event_id),
        "response_validated_event_id": str(preceding_events[7].event_id),
        "response_target_resolved_event_id": str(
            preceding_events[8].event_id
        ),
    }
    reference_fields = (
        (),
        ("source_event_id",),
        ("source_event_id", "accepted_event_id"),
        ("source_event_id", "accepted_event_id", "perceived_event_id"),
        (
            "source_event_id", "accepted_event_id", "perceived_event_id",
            "normalized_event_id",
        ),
        (
            "source_event_id", "accepted_event_id", "perceived_event_id",
            "normalized_event_id", "next_action_event_id",
        ),
        (
            "source_event_id", "accepted_event_id", "perceived_event_id",
            "normalized_event_id", "next_action_event_id",
            "response_request_event_id",
        ),
        (
            "source_event_id", "accepted_event_id", "perceived_event_id",
            "normalized_event_id", "next_action_event_id",
            "response_request_event_id", "response_generated_event_id",
        ),
        ("source_event_id", "response_validated_event_id"),
        (
            "source_event_id", "response_validated_event_id",
            "response_target_resolved_event_id",
        ),
    )
    for preceding, field_names in zip(
        preceding_events, reference_fields, strict=True
    ):
        for field_name in field_names:
            if preceding.payload.get(field_name) != reference_ids[field_name]:
                raise ValueError(f"{field_name} does not match")
    _validate_response_ready_contract(
        tuple(preceding.payload for preceding in preceding_events)
    )
    if event.tenant_id != tenant_id or entry.tenant_id != tenant_id:
        raise ValueError("delivery tenant does not match episode tenant")
    if entry.episode_id != episode_id:
        raise ValueError("outbox episode does not match Episode")
    if event.event_type != "communication.delivery_requested":
        raise ValueError("Event must be communication.delivery_requested")
    if event.schema_version != 1 or entry.schema_version != 1:
        raise ValueError("delivery schema_version does not match")
    ready_event = preceding_events[9]
    if event.correlation_id != ready_event.correlation_id:
        raise ValueError("delivery-requested correlation_id does not match")
    if event.causation_id != str(ready_event.event_id):
        raise ValueError("delivery-requested causation_id does not match")
    payload = event.payload
    if not isinstance(payload, Mapping):
        raise ValueError("Event payload must be a mapping")
    expected_payload = {
        "source_event_id": str(preceding_events[0].event_id),
        "response_ready_event_id": str(preceding_events[9].event_id),
        "channel": entry.channel,
        "external_conversation_id": entry.external_conversation_id,
        "outbound_sender_id": entry.outbound_sender_id,
        "outbound_recipient_id": entry.outbound_recipient_id,
        "idempotency_key": entry.idempotency_key,
        "request_method": "transactional_outbox",
    }
    if dict(payload) != expected_payload:
        raise ValueError("delivery-requested Event payload is inconsistent")
    ready_payload = preceding_events[9].payload
    expected_ready_values = {
        "channel": entry.channel,
        "external_conversation_id": entry.external_conversation_id,
        "outbound_sender_id": entry.outbound_sender_id,
        "outbound_recipient_id": entry.outbound_recipient_id,
        "response_type": entry.response_type,
        "language": entry.language,
        "text": entry.text,
    }
    for field_name, expected_value in expected_ready_values.items():
        if ready_payload.get(field_name) != expected_value:
            raise ValueError("outbox snapshot does not match response-ready Event")
    if ready_payload.get("source_event_id") != str(preceding_events[0].event_id):
        raise ValueError("response-ready source_event_id does not match")
    if entry.delivery_request_event_id != event.event_id:
        raise ValueError("delivery_request_event_id does not match Event")
    if entry.response_ready_event_id != preceding_events[9].event_id:
        raise ValueError("response_ready_event_id does not match Event 10")
    if entry.idempotency_key != str(entry.response_ready_event_id):
        raise ValueError("idempotency_key does not match response_ready_event_id")


def _reject_delivery_requested_for_ordinary_append(event: Event) -> None:
    if event.event_type == "communication.delivery_requested":
        raise ValueError(
            "communication.delivery_requested requires atomic outbox append"
        )


def _reject_delivery_accepted_for_ordinary_append(event: Event) -> None:
    if event.event_type == "communication.delivery_accepted":
        raise ValueError(
            "communication.delivery_accepted requires atomic delivery finalization"
        )


def _validate_response_ready_contract(
    payloads: tuple[Mapping[str, object], ...],
) -> None:
    source = payloads[0]
    request = payloads[5]
    generated = payloads[6]
    validated = payloads[7]
    target = payloads[8]
    ready = payloads[9]
    required = (
        (source, ("channel", "external_message_id",
                  "external_conversation_id", "sender_id", "recipient_id")),
        (request, ("response_type", "target_language")),
        (generated, ("response_type", "language", "text",
                     "generation_method")),
        (validated, ("response_type", "language", "text",
                     "generation_method", "validation_method")),
        (target, ("channel", "external_message_id",
                  "external_conversation_id", "outbound_sender_id",
                  "outbound_recipient_id", "resolution_method")),
        (ready, ("channel", "external_conversation_id",
                 "outbound_sender_id", "outbound_recipient_id",
                 "response_type", "language", "text",
                 "readiness_method")),
    )
    for payload, field_names in required:
        if not set(field_names).issubset(payload):
            raise ValueError("Event payload is missing required fields")
    if generated["response_type"] != request["response_type"]:
        raise ValueError("response_type does not match response request")
    if generated["language"] != request["target_language"]:
        raise ValueError("language does not match response request")
    for field_name in ("response_type", "language", "text",
                       "generation_method"):
        if validated[field_name] != generated[field_name]:
            raise ValueError(f"validated {field_name} does not match generated")
    if generated["generation_method"] != "deterministic_template":
        raise ValueError("generation_method does not match")
    if validated["validation_method"] != "deterministic_contract":
        raise ValueError("validation_method does not match")
    expected_target = {
        "channel": source["channel"],
        "external_message_id": source["external_message_id"],
        "external_conversation_id": source["external_conversation_id"],
        "outbound_sender_id": source["recipient_id"],
        "outbound_recipient_id": source["sender_id"],
        "resolution_method": "reply_to_source",
    }
    for field_name, expected_value in expected_target.items():
        if target[field_name] != expected_value:
            raise ValueError(f"target {field_name} does not match source")
    expected_ready = {
        "channel": target["channel"],
        "external_conversation_id": target["external_conversation_id"],
        "outbound_sender_id": target["outbound_sender_id"],
        "outbound_recipient_id": target["outbound_recipient_id"],
        "response_type": validated["response_type"],
        "language": validated["language"],
        "text": validated["text"],
        "readiness_method": "validated_response_with_resolved_target",
    }
    for field_name, expected_value in expected_ready.items():
        if ready[field_name] != expected_value:
            raise ValueError(f"response-ready {field_name} does not match")
