from __future__ import annotations

from dataclasses import replace
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import uuid

from mike_app.runtime.development_adapter import AdapterOutcome, AdapterResult, DevelopmentAdapter
from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.delivery_processing import DeliveryProcessor
from mike_app.runtime.delivery_receipt import DeliveryReceipt, snapshot_hash
from mike_app.runtime.episode_journal import InMemoryEpisodeJournal
from tests.episode_journal_contract import build_ten_event_episode
from mike_app.runtime.event import Event
from mike_app.runtime.episode import CognitiveEpisode
import pytest


def make_delivery(journal: InMemoryEpisodeJournal, tenant: str = "processing-tenant") -> DeliveryOutboxEntry:
    episode, events = build_ten_event_episode(journal, tenant)
    ready = events[-1]
    delivery = Event.create(
        tenant,
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
        outbox_id=uuid.uuid4(), tenant_id=tenant, episode_id=episode.episode_id,
        delivery_request_event_id=delivery.event_id, response_ready_event_id=ready.event_id,
        idempotency_key=str(ready.event_id), channel="development",
        external_conversation_id="conversation", outbound_sender_id="recipient",
        outbound_recipient_id="sender", response_type="answer", language="es",
        text="  texto exacto  ", status="pending",
        created_at=datetime.now(timezone.utc), schema_version=1,
    )
    journal.append_event_with_outbox(tenant, episode.episode_id, delivery, episode.event_ids, entry)
    return entry


def test_run_once_completes_and_is_idempotent() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal)
    processor = DeliveryProcessor(journal, DevelopmentAdapter())
    result = processor.run_once(entry.tenant_id)
    assert result.outcome == "completed"
    stored = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert stored is not None and stored.status == "completed"
    assert stored.delivery_accepted_event_id is not None
    assert len(journal.list_events(entry.tenant_id, "communication.delivery_accepted")) == 1
    assert processor.run_once(entry.tenant_id).outcome == "no_work"


def test_transient_failures_backoff_then_fail() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal, "transient-tenant")
    clock = [datetime(2026, 9, 27, tzinfo=timezone.utc)]
    processor = DeliveryProcessor(
        journal,
        DevelopmentAdapter(AdapterOutcome.TRANSIENT),
        clock=lambda: clock[0],
    )
    assert processor.run_once(entry.tenant_id).outcome == "rescheduled"
    first = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert first is not None and first.adapter_attempt_count == 1
    assert first.next_attempt_at == clock[0] + timedelta(seconds=30)
    clock[0] = first.next_attempt_at
    assert processor.run_once(entry.tenant_id).outcome == "rescheduled"
    second = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert second is not None and second.adapter_attempt_count == 2
    assert second.next_attempt_at == clock[0] + timedelta(seconds=120)
    clock[0] = second.next_attempt_at
    assert processor.run_once(entry.tenant_id).outcome == "failed"
    final = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert final is not None and final.status == "failed" and final.adapter_attempt_count == 3
    assert journal.list_events(entry.tenant_id, "communication.delivery_accepted") == ()


def test_permanent_failure_does_not_create_receipt() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal, "permanent-tenant")
    processor = DeliveryProcessor(journal, DevelopmentAdapter(AdapterOutcome.PERMANENT))
    assert processor.run_once(entry.tenant_id).outcome == "failed"
    assert journal.get_delivery_receipt(entry.tenant_id, entry.idempotency_key) is None
    stored = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert stored is not None and stored.status == "failed" and stored.adapter_attempt_count == 1


def test_event_12_cannot_use_ordinary_append() -> None:
    journal = InMemoryEpisodeJournal()
    first = Event.create("append-protected", "message.received")
    episode = journal.create_episode_with_event(CognitiveEpisode.create(first), first)
    event12 = Event.create("append-protected", "communication.delivery_accepted")
    with pytest.raises(ValueError, match="atomic delivery finalization"):
        journal.append_event("append-protected", episode.episode_id, event12, episode.event_ids)


def test_claim_is_single_and_tenant_scoped() -> None:
    journal = InMemoryEpisodeJournal()
    first = make_delivery(journal, "claim-tenant")
    second = make_delivery(journal, "claim-tenant")
    now = datetime.now(timezone.utc)
    claimed = journal.claim_one_delivery("claim-tenant", now, 60)
    assert claimed is not None and claimed.outbox_id == first.outbox_id
    assert journal.claim_one_delivery("claim-tenant", now, 60) is not None
    assert journal.claim_one_delivery("other-tenant", now, 60) is None
    assert {claimed.outbox_id, second.outbox_id} == {first.outbox_id, second.outbox_id}


def test_reservation_survives_adapter_crash_before_invocation() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal, "reservation-tenant")
    invoked = False

    def crash() -> object:
        nonlocal invoked
        invoked = True
        raise RuntimeError("crash before adapter result")

    with pytest.raises(RuntimeError, match="crash"):
        DeliveryProcessor(journal, DevelopmentAdapter(operation=crash)).run_once(entry.tenant_id)
    stored = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert stored is not None and stored.status == "processing" and stored.adapter_attempt_count == 1
    assert invoked


def test_receipt_recovery_after_third_reservation_does_not_invoke_again() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal, "receipt-recovery")
    now = datetime.now(timezone.utc)
    claimed = journal.claim_one_delivery(entry.tenant_id, now, 60)
    assert claimed is not None
    for _ in range(3):
        claimed = journal.start_adapter_attempt(entry.tenant_id, entry.outbox_id, claimed.claim_token, now)
    receipt = DeliveryReceipt(
        uuid.uuid4(), entry.tenant_id, entry.outbox_id, entry.delivery_request_event_id,
        entry.idempotency_key, snapshot_hash(claimed), "development", now,
    )
    journal.save_delivery_receipt(receipt, claimed.claim_token)
    calls = 0

    def unexpected() -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("adapter must not be invoked")

    recovery_time = now + timedelta(seconds=61)
    result = DeliveryProcessor(journal, DevelopmentAdapter(operation=unexpected), clock=lambda: recovery_time).run_once(entry.tenant_id)
    assert result.outcome == "completed" and calls == 0
    stored = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert stored is not None and stored.status == "completed" and stored.adapter_attempt_count == 3


def test_timeout_returns_without_waiting_for_late_operation() -> None:
    started = threading.Event()
    release = threading.Event()

    def late() -> object:
        started.set()
        release.wait(2)
        return None

    adapter = DevelopmentAdapter(timeout_seconds=0.05, operation=late)
    began = time.monotonic()
    result = adapter.process(make_delivery(InMemoryEpisodeJournal(), "timeout-tenant"))
    elapsed = time.monotonic() - began
    assert started.is_set()
    assert result.outcome is AdapterOutcome.UNKNOWN
    assert elapsed < 0.5
    release.set()
    assert DevelopmentAdapter.timeout_seconds == 10


def test_repeated_timeouts_leave_no_adapter_threads_after_operations_release() -> None:
    releases = []
    started = []
    baseline = {thread.ident for thread in threading.enumerate()}
    for _ in range(5):
        started_event = threading.Event()
        release_event = threading.Event()
        started.append(started_event)
        releases.append(release_event)

        def late(started_event=started_event, release_event=release_event):
            started_event.set()
            release_event.wait(2)
            return AdapterResult(AdapterOutcome.SUCCESS)

        result = DevelopmentAdapter(timeout_seconds=0.01, operation=late).process(
            make_delivery(InMemoryEpisodeJournal(), "resource-timeout")
        )
        assert result.outcome is AdapterOutcome.UNKNOWN
        assert started_event.is_set()
    assert any(thread.ident not in baseline for thread in threading.enumerate())
    for release_event in releases:
        release_event.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not any(thread.ident not in baseline for thread in threading.enumerate()):
            break
        time.sleep(0.01)
    assert not any(thread.ident not in baseline for thread in threading.enumerate())


def test_different_requests_can_process_concurrently() -> None:
    journal = InMemoryEpisodeJournal()
    entries = (make_delivery(journal, "parallel-tenant"), make_delivery(journal, "parallel-tenant"))
    barrier = threading.Barrier(2)

    def operation() -> AdapterResult:
        barrier.wait(timeout=1)
        return AdapterResult(AdapterOutcome.SUCCESS)

    processor = DeliveryProcessor(journal, DevelopmentAdapter(operation=operation))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda entry: processor.run_once(entry.tenant_id), entries))
    assert [result.outcome for result in results] == ["completed", "completed"]
    assert all(journal.get_outbox_entry(entry.tenant_id, entry.outbox_id).status == "completed" for entry in entries)


def test_stale_token_and_expired_lease_cannot_mutate() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal, "stale-tenant")
    now = datetime.now(timezone.utc)
    first = journal.claim_one_delivery(entry.tenant_id, now, 1)
    assert first is not None
    replacement = journal.claim_one_delivery(entry.tenant_id, now + timedelta(seconds=2), 60)
    assert replacement is not None and replacement.claim_token != first.claim_token
    with pytest.raises(ValueError, match="stale"):
        journal.start_adapter_attempt(entry.tenant_id, entry.outbox_id, first.claim_token, now)


def test_receipt_conflict_and_failed_receipt_races_are_fenced() -> None:
    journal = InMemoryEpisodeJournal()
    entry = make_delivery(journal, "receipt-race")
    now = datetime.now(timezone.utc)
    claimed = journal.claim_one_delivery(entry.tenant_id, now, 60)
    assert claimed is not None
    attempted = journal.start_adapter_attempt(entry.tenant_id, entry.outbox_id, claimed.claim_token, now)
    receipt = DeliveryReceipt(
        uuid.uuid4(), entry.tenant_id, entry.outbox_id, entry.delivery_request_event_id,
        entry.idempotency_key, snapshot_hash(attempted), "development", now,
    )
    journal.save_delivery_receipt(receipt, claimed.claim_token)
    with pytest.raises(ValueError, match="successful receipt"):
        journal.fail_delivery(entry.tenant_id, entry.outbox_id, claimed.claim_token, now, "late", None)

    other = make_delivery(journal, "failed-race")
    failed_claim = journal.claim_one_delivery(other.tenant_id, now, 60)
    assert failed_claim is not None
    attempted_other = journal.start_adapter_attempt(other.tenant_id, other.outbox_id, failed_claim.claim_token, now)
    journal.fail_delivery(other.tenant_id, other.outbox_id, failed_claim.claim_token, now, "failed", None)
    late_receipt = DeliveryReceipt(
        uuid.uuid4(), other.tenant_id, other.outbox_id, other.delivery_request_event_id,
        other.idempotency_key, snapshot_hash(attempted_other), "development", now,
    )
    with pytest.raises(ValueError, match="stale"):
        journal.save_delivery_receipt(late_receipt, failed_claim.claim_token)
