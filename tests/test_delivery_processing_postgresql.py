from __future__ import annotations

import os
import threading
import time
import pytest
from tests.test_postgresql_episode_journal import migrated_engine
from tests.test_delivery_processing import make_delivery
from mike_app.runtime.delivery_receipt import DeliveryReceipt, snapshot_hash


@pytest.fixture
def journal(migrated_engine):
    from mike_app.runtime.postgresql_episode_journal import PostgreSQLEpisodeJournal

    return PostgreSQLEpisodeJournal(migrated_engine)


pytestmark = pytest.mark.skipif(
    not os.getenv("MIKE_TEST_DATABASE_URL"),
    reason="MIKE_TEST_DATABASE_URL is required for real PostgreSQL tests",
)


def test_phase24_postgresql_schema_is_collected(migrated_engine) -> None:
    from sqlalchemy import inspect

    inspector = inspect(migrated_engine)
    assert "delivery_receipts" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("delivery_outbox")}
    assert {"adapter_attempt_count", "claim_token", "lease_expires_at", "delivery_accepted_event_id"} <= columns


def test_phase24_postgresql_two_claimers_compete_for_one_row(journal) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone

    entry = make_delivery(journal, "pg-claim-race")
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: journal.claim_one_delivery(entry.tenant_id, now, 60), range(2)
        ))
    claims = [result for result in results if result is not None]
    assert len(claims) == 1
    persisted = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert persisted is not None and persisted.status == "processing"
    assert persisted.claim_token == claims[0].claim_token


def test_phase24_postgresql_processing_persists_receipt_and_event12(journal) -> None:
    from mike_app.runtime.delivery_processing import DeliveryProcessor
    from mike_app.runtime.development_adapter import DevelopmentAdapter

    entry = make_delivery(journal, "pg-processing")
    result = DeliveryProcessor(journal, DevelopmentAdapter()).run_once(entry.tenant_id)
    assert result.outcome == "completed"
    persisted = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert persisted is not None and persisted.status == "completed"
    assert persisted.delivery_accepted_event_id is not None
    assert journal.get_delivery_receipt(entry.tenant_id, entry.idempotency_key) is not None
    assert len(journal.list_events(entry.tenant_id, "communication.delivery_accepted")) == 1


def _claimed_with_receipt(journal, tenant_id: str):
    from datetime import datetime, timezone
    import uuid

    entry = make_delivery(journal, tenant_id)
    now = datetime.now(timezone.utc)
    claimed = journal.claim_one_delivery(tenant_id, now, 60)
    assert claimed is not None
    attempted = journal.start_adapter_attempt(tenant_id, entry.outbox_id, claimed.claim_token, now)
    receipt = DeliveryReceipt(
        uuid.uuid4(), tenant_id, entry.outbox_id, entry.delivery_request_event_id,
        entry.idempotency_key, snapshot_hash(attempted), "development", now,
    )
    journal.save_delivery_receipt(receipt, claimed.claim_token)
    return entry, claimed, receipt


def test_phase24_postgresql_t3_rollback_after_event_flush_is_atomic(journal, migrated_engine) -> None:
    from sqlalchemy import event, select
    from sqlalchemy.orm import Session
    from mike_app.runtime.postgresql_episode_journal import EventRow, EpisodeJournalInfrastructureError

    entry, claimed, receipt = _claimed_with_receipt(journal, "pg-t3-event-rollback")
    observed_inside_transaction = threading.Event()

    def fail_after_event_flush(session, flush_context):
        count = session.scalar(select(EventRow).where(EventRow.episode_id == entry.episode_id).count()) if False else session.query(EventRow).filter_by(episode_id=entry.episode_id).count()
        if count == 12:
            observed_inside_transaction.set()
            raise RuntimeError("controlled failure after event 12 flush")

    event.listen(Session, "after_flush_postexec", fail_after_event_flush)
    try:
        with pytest.raises(RuntimeError, match="after event 12"):
            journal.finalize_delivery(entry.tenant_id, entry.outbox_id, claimed.claim_token, receipt)
    finally:
        event.remove(Session, "after_flush_postexec", fail_after_event_flush)
    assert observed_inside_transaction.is_set()
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(EventRow).where(EventRow.episode_id == entry.episode_id).count()) if False else connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM events WHERE episode_id = :episode_id"), {"episode_id": entry.episode_id}).scalar_one() == 11
        assert connection.execute(__import__("sqlalchemy").text("SELECT delivery_accepted_event_id IS NULL AND status = 'processing' FROM delivery_outbox WHERE outbox_id = :outbox_id"), {"outbox_id": entry.outbox_id}).scalar_one()
        assert connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM delivery_receipts WHERE idempotency_key = :key"), {"key": entry.idempotency_key}).scalar_one() == 1
    with migrated_engine.begin() as connection:
        connection.execute(__import__("sqlalchemy").text("UPDATE delivery_outbox SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE outbox_id = :outbox_id"), {"outbox_id": entry.outbox_id})
    recovered = journal.claim_one_delivery(entry.tenant_id, __import__("datetime").datetime.now(__import__("datetime").timezone.utc), 60)
    assert recovered is not None
    journal.finalize_delivery(entry.tenant_id, entry.outbox_id, recovered.claim_token, receipt)
    assert journal.get_outbox_entry(entry.tenant_id, entry.outbox_id).status == "completed"
    assert len(journal.list_events(entry.tenant_id, "communication.delivery_accepted")) == 1


def test_phase24_postgresql_t3_rollback_after_related_state_flush_is_atomic(journal, migrated_engine) -> None:
    from sqlalchemy import event, text
    from sqlalchemy.orm import Session

    entry, claimed, receipt = _claimed_with_receipt(journal, "pg-t3-related-rollback")
    observed_completed_inside_transaction = threading.Event()
    flushes = 0

    def fail_after_related_state_flush(session, flush_context):
        nonlocal flushes
        flushes += 1
        if flushes == 2:
            row = session.execute(text("SELECT status, delivery_accepted_event_id IS NOT NULL FROM delivery_outbox WHERE outbox_id = :id"), {"id": entry.outbox_id}).one()
            assert row == ("completed", True)
            observed_completed_inside_transaction.set()
            raise RuntimeError("controlled failure after related state flush")

    event.listen(Session, "after_flush_postexec", fail_after_related_state_flush)
    try:
        with pytest.raises(RuntimeError, match="related state"):
            journal.finalize_delivery(entry.tenant_id, entry.outbox_id, claimed.claim_token, receipt)
    finally:
        event.remove(Session, "after_flush_postexec", fail_after_related_state_flush)
    assert observed_completed_inside_transaction.is_set()
    with migrated_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM events WHERE episode_id = :episode_id"), {"episode_id": entry.episode_id}).scalar_one() == 11
        persisted = connection.execute(text("SELECT status, delivery_accepted_event_id FROM delivery_outbox WHERE outbox_id = :id"), {"id": entry.outbox_id}).one()
        assert persisted.status == "processing" and persisted.delivery_accepted_event_id is None
        assert connection.execute(text("SELECT count(*) FROM delivery_receipts WHERE idempotency_key = :key"), {"key": entry.idempotency_key}).scalar_one() == 1


def test_phase24_postgresql_two_finalizers_have_one_winner(journal):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    entry, claimed, receipt = _claimed_with_receipt(journal, "pg-t3-finalizer-race")
    first_flushed = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    calls = 0

    def hold_first_flush(session, flush_context):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_flushed.set()
            assert release_first.wait(2)

    event.listen(Session, "after_flush_postexec", hold_first_flush)
    def finalize(index):
        if index == 1:
            second_started.set()
        try:
            return journal.finalize_delivery(entry.tenant_id, entry.outbox_id, claimed.claim_token, receipt)
        except Exception as exc:
            return exc
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(finalize, 0)
            assert first_flushed.wait(2)
            second = pool.submit(finalize, 1)
            assert second_started.wait(2)
            time.sleep(0.1)
            release_first.set()
            results = (first.result(), second.result())
    finally:
        event.remove(Session, "after_flush_postexec", hold_first_flush)
    assert all(not isinstance(result, Exception) for result in results)
    assert journal.get_outbox_entry(entry.tenant_id, entry.outbox_id).status == "completed"
    assert len(journal.list_events(entry.tenant_id, "communication.delivery_accepted")) == 1
    assert journal.get_delivery_receipt(entry.tenant_id, entry.idempotency_key) == receipt


def test_phase24_postgresql_stale_authority_and_altered_chain_are_rejected(journal, migrated_engine) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import text

    entry, claimed, receipt = _claimed_with_receipt(journal, "pg-t3-authority")
    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE delivery_outbox SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE outbox_id = :id"), {"id": entry.outbox_id})
    with pytest.raises(ValueError, match="stale"):
        journal.finalize_delivery(entry.tenant_id, entry.outbox_id, claimed.claim_token, receipt)
    replacement = journal.claim_one_delivery(entry.tenant_id, datetime.now(timezone.utc), 60)
    assert replacement is not None
    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE events SET payload = payload || '{\"text\":\"tampered\"}'::jsonb WHERE event_id = :id"), {"id": entry.response_ready_event_id})
    with pytest.raises(ValueError):
        journal.finalize_delivery(entry.tenant_id, entry.outbox_id, replacement.claim_token, receipt)
    assert journal.get_outbox_entry(entry.tenant_id, entry.outbox_id).status == "processing"
    assert len(journal.list_events(entry.tenant_id, "communication.delivery_accepted")) == 0


@pytest.mark.parametrize("operation", ["receipt", "failure", "finalize"])
def test_phase24_postgresql_rechecks_authority_after_waiting_for_outbox_lock(
    journal, migrated_engine, operation
) -> None:
    """The lease is valid when the operation starts, but expires while blocked."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from sqlalchemy import text

    entry, claimed, receipt = _claimed_with_receipt(journal, f"pg-lock-expiry-{operation}")
    # Remove the receipt for the receipt-publication case; the other two need it.
    if operation == "receipt":
        with migrated_engine.begin() as connection:
            connection.execute(text("DELETE FROM delivery_receipts WHERE outbox_id = :id"), {"id": entry.outbox_id})
    with migrated_engine.begin() as connection:
        connection.execute(text("UPDATE delivery_outbox SET lease_expires_at = clock_timestamp() + interval '0.1 seconds' WHERE outbox_id = :id"), {"id": entry.outbox_id})

    blocker = migrated_engine.connect()
    transaction = blocker.begin()
    try:
        blocker.execute(text("SELECT outbox_id FROM delivery_outbox WHERE outbox_id = :id FOR UPDATE"), {"id": entry.outbox_id})
        now = datetime.now(timezone.utc)
        with ThreadPoolExecutor(max_workers=1) as pool:
            if operation == "receipt":
                future = pool.submit(journal.save_delivery_receipt, receipt, claimed.claim_token)
            elif operation == "failure":
                future = pool.submit(journal.fail_delivery, entry.tenant_id, entry.outbox_id, claimed.claim_token, now, "late", None)
            else:
                future = pool.submit(journal.finalize_delivery, entry.tenant_id, entry.outbox_id, claimed.claim_token, receipt)
            import time
            time.sleep(0.8)
            assert not future.done(), "operation did not reach the database lock"
            transaction.commit()
            with pytest.raises(ValueError, match="stale"):
                future.result(timeout=3)
    finally:
        if transaction.is_active:
            transaction.rollback()
        blocker.close()

    with migrated_engine.connect() as connection:
        row = connection.execute(text("SELECT status, delivery_accepted_event_id FROM delivery_outbox WHERE outbox_id = :id"), {"id": entry.outbox_id}).one()
        assert row.status == "processing" and row.delivery_accepted_event_id is None
        assert connection.execute(text("SELECT count(*) FROM events WHERE episode_id = :episode_id"), {"episode_id": entry.episode_id}).scalar_one() == 11
        expected_receipts = 0 if operation == "receipt" else 1
        assert connection.execute(text("SELECT count(*) FROM delivery_receipts WHERE outbox_id = :id"), {"id": entry.outbox_id}).scalar_one() == expected_receipts


def _race_receipt_and_failed(journal, migrated_engine, receipt_first: bool):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from sqlalchemy import text
    import uuid

    entry = make_delivery(journal, f"pg-receipt-failed-race-{receipt_first}")
    now = datetime.now(timezone.utc)
    claimed = journal.claim_one_delivery(entry.tenant_id, now, 60)
    assert claimed is not None
    attempted = journal.start_adapter_attempt(entry.tenant_id, entry.outbox_id, claimed.claim_token, now)
    receipt = DeliveryReceipt(uuid.uuid4(), entry.tenant_id, entry.outbox_id, entry.delivery_request_event_id,
                              entry.idempotency_key, snapshot_hash(attempted), "development", now)
    blocker = migrated_engine.connect()
    transaction = blocker.begin()
    try:
        blocker.execute(text("SELECT outbox_id FROM delivery_outbox WHERE outbox_id = :id FOR UPDATE"), {"id": entry.outbox_id})
        with ThreadPoolExecutor(max_workers=2) as pool:
            if receipt_first:
                first = pool.submit(journal.save_delivery_receipt, receipt, claimed.claim_token)
                second = pool.submit(journal.fail_delivery, entry.tenant_id, entry.outbox_id, claimed.claim_token, now, "late", None)
            else:
                first = pool.submit(journal.fail_delivery, entry.tenant_id, entry.outbox_id, claimed.claim_token, now, "late", None)
                second = pool.submit(journal.save_delivery_receipt, receipt, claimed.claim_token)
            import time
            time.sleep(0.35)
            assert not first.done() and not second.done()
            transaction.commit()
            def result_or_error(future):
                try:
                    return future.result(timeout=3)
                except Exception as exc:
                    return exc
            first_result = result_or_error(first)
            second_result = result_or_error(second)
    finally:
        if transaction.is_active:
            transaction.rollback()
        blocker.close()
    return entry, receipt, first_result, second_result


def test_phase24_postgresql_compatible_receipt_wins_against_failed(journal, migrated_engine) -> None:
    entry, receipt, first, second = _race_receipt_and_failed(journal, migrated_engine, True)
    assert first == receipt
    assert isinstance(second, ValueError) and "successful receipt" in str(second)
    with migrated_engine.connect() as connection:
        row = connection.execute(__import__("sqlalchemy").text("SELECT status, delivery_accepted_event_id FROM delivery_outbox WHERE outbox_id = :id"), {"id": entry.outbox_id}).one()
        assert row.status == "processing" and row.delivery_accepted_event_id is None
        assert connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM delivery_receipts WHERE outbox_id = :id"), {"id": entry.outbox_id}).scalar_one() == 1


def test_phase24_postgresql_failed_wins_against_late_receipt(journal, migrated_engine) -> None:
    entry, receipt, first, second = _race_receipt_and_failed(journal, migrated_engine, False)
    assert first.status == "failed"
    assert isinstance(second, ValueError) and "stale" in str(second)
    with migrated_engine.connect() as connection:
        row = connection.execute(__import__("sqlalchemy").text("SELECT status, delivery_accepted_event_id FROM delivery_outbox WHERE outbox_id = :id"), {"id": entry.outbox_id}).one()
        assert row.status == "failed" and row.delivery_accepted_event_id is None
        assert connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM delivery_receipts WHERE outbox_id = :id"), {"id": entry.outbox_id}).scalar_one() == 0
        assert connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM events WHERE episode_id = :episode_id"), {"episode_id": entry.episode_id}).scalar_one() == 11


def test_phase24_postgresql_timeout_late_processor_result_has_no_durable_effect(journal, migrated_engine) -> None:
    from mike_app.runtime.development_adapter import AdapterResult, AdapterOutcome, DevelopmentAdapter
    from mike_app.runtime.delivery_processing import DeliveryProcessor
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    import threading
    import time

    entry = make_delivery(journal, "pg-timeout-late-processor")
    started = threading.Event()
    release = threading.Event()

    def late_operation():
        started.set()
        assert release.wait(3)
        return AdapterResult(AdapterOutcome.SUCCESS)

    processor = DeliveryProcessor(journal, DevelopmentAdapter(timeout_seconds=0.05, operation=late_operation))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(processor.run_once, entry.tenant_id)
        assert started.wait(2)
        result = future.result(timeout=2)
    assert result.outcome == "rescheduled"
    claimed = journal.get_outbox_entry(entry.tenant_id, entry.outbox_id)
    assert claimed is not None and claimed.status == "pending"
    with migrated_engine.begin() as connection:
        connection.execute(__import__("sqlalchemy").text("UPDATE delivery_outbox SET next_attempt_at = clock_timestamp() WHERE outbox_id = :id"), {"id": entry.outbox_id})
    replacement = journal.claim_one_delivery(entry.tenant_id, datetime.now(timezone.utc), 60)
    assert replacement is not None
    journal.fail_delivery(entry.tenant_id, entry.outbox_id, replacement.claim_token, datetime.now(timezone.utc), "confirmed failed", None)
    release.set()
    time.sleep(0.1)
    with migrated_engine.connect() as connection:
        assert connection.execute(__import__("sqlalchemy").text("SELECT status, delivery_accepted_event_id FROM delivery_outbox WHERE outbox_id = :id"), {"id": entry.outbox_id}).one() == ("failed", None)
        assert connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM delivery_receipts WHERE outbox_id = :id"), {"id": entry.outbox_id}).scalar_one() == 0
        assert connection.execute(__import__("sqlalchemy").text("SELECT count(*) FROM events WHERE episode_id = :episode_id"), {"episode_id": entry.episode_id}).scalar_one() == 11


def test_phase24_postgresql_physical_pointer_checks_and_receipt_idempotency(journal, migrated_engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    import uuid
    from datetime import datetime, timezone

    first = make_delivery(journal, "physical-tenant")
    other_tenant = make_delivery(journal, "physical-other-tenant")
    now = datetime.now(timezone.utc)
    claimed = journal.claim_one_delivery(first.tenant_id, now, 60)
    assert claimed is not None
    attempted = journal.start_adapter_attempt(first.tenant_id, first.outbox_id, claimed.claim_token, now)
    receipt = DeliveryReceipt(uuid.uuid4(), first.tenant_id, first.outbox_id, first.delivery_request_event_id, first.idempotency_key, snapshot_hash(attempted), "development", now)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(text("UPDATE delivery_outbox SET status = 'completed' WHERE outbox_id = :id"), {"id": first.outbox_id})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(text("UPDATE delivery_outbox SET status = 'processing', delivery_accepted_event_id = :event_id WHERE outbox_id = :id"), {"event_id": other_tenant.response_ready_event_id, "id": first.outbox_id})

    journal.save_delivery_receipt(receipt, claimed.claim_token)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(text("INSERT INTO delivery_receipts (receipt_id, tenant_id, outbox_id, delivery_request_event_id, idempotency_key, snapshot_hash, adapter, accepted_at, schema_version) VALUES (:receipt_id, :tenant_id, :outbox_id, :event_id, :key, :hash, 'development', :accepted, 1)"), {"receipt_id": uuid.uuid4(), "tenant_id": first.tenant_id, "outbox_id": first.outbox_id, "event_id": first.delivery_request_event_id, "key": first.idempotency_key, "hash": receipt.snapshot_hash, "accepted": now})
    assert journal.get_delivery_receipt(first.tenant_id, first.idempotency_key) == receipt
