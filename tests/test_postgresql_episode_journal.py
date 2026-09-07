from __future__ import annotations

import math
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone

import pytest


TEST_DATABASE_URL = os.getenv("MIKE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="MIKE_TEST_DATABASE_URL is required for real PostgreSQL tests",
)


def _validated_url() -> str:
    from sqlalchemy.engine import make_url

    assert TEST_DATABASE_URL is not None
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        pytest.fail("MIKE_TEST_DATABASE_URL must be a PostgreSQL URL")
    database = url.database or ""
    if "test" not in database.casefold():
        pytest.fail("MIKE_TEST_DATABASE_URL database name must identify a test database")
    return TEST_DATABASE_URL


@pytest.fixture(scope="module")
def migrated_engine():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = _validated_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(autouse=True)
def clean_journal_tables(migrated_engine):
    from sqlalchemy import text

    with migrated_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE events, episodes RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def journal(migrated_engine):
    from mike_app.runtime.postgresql_episode_journal import PostgreSQLEpisodeJournal

    return PostgreSQLEpisodeJournal(migrated_engine)


def _initial(journal, tenant: str = "tenant-postgres"):
    from mike_app.runtime.episode import CognitiveEpisode
    from mike_app.runtime.event import Event

    event = Event.create(tenant, "test.initial", {"nested": [1, {"ok": True}]})
    episode = CognitiveEpisode.create(event)
    journal.create_episode_with_event(episode, event)
    return event, episode


def test_migration_downgrade_and_reupgrade(migrated_engine) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    config = Config("alembic.ini")
    command.downgrade(config, "base")
    assert not set(inspect(migrated_engine).get_table_names()) & {
        "episodes", "events", "delivery_outbox"
    }
    command.upgrade(config, "head")
    assert {"episodes", "events", "delivery_outbox"} <= set(
        inspect(migrated_engine).get_table_names()
    )


def test_delivery_outbox_schema_has_exact_approved_columns(migrated_engine) -> None:
    from sqlalchemy import inspect

    inspector = inspect(migrated_engine)
    assert {column["name"] for column in inspector.get_columns("delivery_outbox")} == {
        "outbox_id", "tenant_id", "episode_id", "delivery_request_event_id",
        "response_ready_event_id", "idempotency_key", "channel",
        "external_conversation_id", "outbound_sender_id",
        "outbound_recipient_id", "response_type", "language", "text",
        "status", "created_at", "schema_version",
    }
    event_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("events")
    }
    assert event_uniques["uq_events_event_episode_tenant"] == (
        "event_id", "episode_id", "tenant_id"
    )
    outbox_foreign_keys = {
        constraint["name"]: (
            tuple(constraint["constrained_columns"]),
            tuple(constraint["referred_columns"]),
        )
        for constraint in inspector.get_foreign_keys("delivery_outbox")
    }
    assert outbox_foreign_keys[
        "fk_delivery_outbox_delivery_event_episode_tenant"
    ] == (
        ("delivery_request_event_id", "episode_id", "tenant_id"),
        ("event_id", "episode_id", "tenant_id"),
    )
    assert outbox_foreign_keys[
        "fk_delivery_outbox_ready_event_episode_tenant"
    ] == (
        ("response_ready_event_id", "episode_id", "tenant_id"),
        ("event_id", "episode_id", "tenant_id"),
    )


def test_shared_contract_against_postgresql(migrated_engine) -> None:
    from sqlalchemy import text
    from mike_app.runtime.postgresql_episode_journal import PostgreSQLEpisodeJournal
    from tests.episode_journal_contract import (
        assert_atomic_create_and_append,
        assert_atomic_outbox_append,
        assert_altered_trace_is_rejected,
        assert_canonical_outbox_order,
        assert_delivery_requested_requires_atomic_append,
        assert_exact_version_conflicts,
        assert_tenant_isolation_and_order,
    )

    def factory():
        with migrated_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE events, episodes RESTART IDENTITY CASCADE"))
        return PostgreSQLEpisodeJournal(migrated_engine)

    assert_atomic_create_and_append(factory)
    assert_exact_version_conflicts(factory)
    assert_tenant_isolation_and_order(factory)
    assert_atomic_outbox_append(factory)
    assert_delivery_requested_requires_atomic_append(factory)
    assert_canonical_outbox_order(factory)
    assert_altered_trace_is_rejected(factory)


def test_atomic_create_and_append_rows(journal, migrated_engine) -> None:
    from sqlalchemy import text
    from mike_app.runtime.event import Event

    first, episode = _initial(journal)
    second = Event.create(first.tenant_id, "test.next")
    updated = journal.append_event(first.tenant_id, episode.episode_id, second, episode.event_ids)
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM episodes")) == 1
        assert connection.scalar(text("SELECT count(*) FROM events")) == 2
        assert connection.execute(text("SELECT sequence FROM events ORDER BY sequence")).scalars().all() == [0, 1]
    assert updated.event_ids == (first.event_id, second.event_id)


def test_create_database_failure_rolls_back_episode_and_event(journal, migrated_engine) -> None:
    from sqlalchemy import text
    from mike_app.runtime.episode import CognitiveEpisode
    from mike_app.runtime.event import Event

    with migrated_engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE events ADD CONSTRAINT test_forced_create_failure "
            "CHECK (event_type <> 'test.force_create_failure')"
        ))
    event = Event.create("create-rollback", "test.force_create_failure")
    episode = CognitiveEpisode.create(event)
    try:
        with pytest.raises(ValueError, match="integrity constraint violated"):
            journal.create_episode_with_event(episode, event)
        assert journal.get_event(event.tenant_id, event.event_id) is None
        assert journal.get_episode(event.tenant_id, episode.episode_id) is None
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE events DROP CONSTRAINT IF EXISTS test_forced_create_failure"
            ))


def test_append_database_failure_rolls_back_event_and_episode(journal, migrated_engine) -> None:
    from sqlalchemy import text
    from mike_app.runtime.event import Event

    first, episode = _initial(journal)
    before = journal.get_episode(first.tenant_id, episode.episode_id)
    with migrated_engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE events ADD CONSTRAINT test_forced_append_failure "
            "CHECK (event_type <> 'test.force_failure')"
        ))
    failing = Event.create(first.tenant_id, "test.force_failure")
    try:
        with pytest.raises(ValueError, match="integrity constraint violated"):
            journal.append_event(first.tenant_id, episode.episode_id, failing, episode.event_ids)
        assert journal.get_event(first.tenant_id, failing.event_id) is None
        assert journal.get_episode(first.tenant_id, episode.episode_id) == before
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE events DROP CONSTRAINT IF EXISTS test_forced_append_failure"
            ))


@pytest.mark.parametrize(
    "mutation",
    ["incomplete", "additional", "reordered", "incorrect"],
)
def test_expected_event_ids_are_compared_exactly(journal, mutation) -> None:
    from mike_app.runtime.episode_journal import EpisodeConcurrencyConflictError
    from mike_app.runtime.event import Event

    first, episode = _initial(journal, f"expected-{mutation}")
    second = Event.create(first.tenant_id, "test.second")
    current = journal.append_event(first.tenant_id, episode.episode_id, second, episode.event_ids)
    expected = {
        "incomplete": current.event_ids[:-1],
        "additional": current.event_ids + (uuid.uuid4(),),
        "reordered": tuple(reversed(current.event_ids)),
        "incorrect": (uuid.uuid4(), current.event_ids[1]),
    }[mutation]
    losing = Event.create(first.tenant_id, "test.losing")
    with pytest.raises(EpisodeConcurrencyConflictError):
        journal.append_event(first.tenant_id, episode.episode_id, losing, expected)
    assert journal.get_event(first.tenant_id, losing.event_id) is None
    assert journal.get_episode(first.tenant_id, episode.episode_id) == current


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("nested", [False, True])
def test_non_finite_payload_is_rejected_without_partial_write(journal, value, nested) -> None:
    from mike_app.runtime.event import Event

    before_events = journal.total_event_count()
    before_episodes = journal.total_episode_count()
    payload = {"value": {"nested": [value]}} if nested else {"value": value}
    with pytest.raises(ValueError, match="finite"):
        Event.create("finite-tenant", "test.invalid", payload)
    assert journal.total_event_count() == before_events
    assert journal.total_episode_count() == before_episodes


def test_duplicate_event_id_is_global_across_tenants(journal) -> None:
    from mike_app.runtime.episode import CognitiveEpisode
    from mike_app.runtime.event import Event

    original, _ = _initial(journal, "tenant-one")
    duplicate = Event(
        event_id=original.event_id, tenant_id="tenant-two", event_type="test.initial",
        occurred_at=original.occurred_at, payload={},
    )
    with pytest.raises(ValueError, match="duplicate"):
        journal.create_episode_with_event(CognitiveEpisode.create(duplicate), duplicate)
    assert journal.list_events("tenant-two") == ()


def test_episode_and_tenant_wide_ordering_use_relational_positions(journal, migrated_engine) -> None:
    from sqlalchemy import text
    from mike_app.runtime.event import Event

    first, episode = _initial(journal, "order-tenant")
    other_first, _ = _initial(journal, "other-tenant")
    second = Event.create("order-tenant", "test.match")
    current = journal.append_event("order-tenant", episode.episode_id, second, episode.event_ids)
    third = Event.create("order-tenant", "test.other")
    journal.append_event("order-tenant", episode.episode_id, third, current.event_ids)
    with migrated_engine.connect() as connection:
        positions = connection.execute(text(
            "SELECT journal_position FROM events WHERE tenant_id='order-tenant' ORDER BY journal_position"
        )).scalars().all()
    assert positions == sorted(positions) and len(set(positions)) == 3
    assert journal.list_events("order-tenant") == (first, second, third)
    assert journal.list_events("order-tenant", "test.match") == (second,)
    assert journal.get_episode("order-tenant", episode.episode_id).event_ids == (first.event_id, second.event_id, third.event_id)
    assert journal.list_events("other-tenant") == (other_first,)


def test_list_episodes_preserves_initial_event_creation_order(journal) -> None:
    first, first_episode = _initial(journal, "episode-order")
    second, second_episode = _initial(journal, "episode-order")
    assert journal.list_episodes("episode-order") == (first_episode, second_episode)
    assert first.event_id != second.event_id


def test_reconstruction_preserves_json_immutability_and_utc(journal) -> None:
    from mike_app.runtime.episode import CognitiveEpisode
    from mike_app.runtime.event import Event

    non_utc = timezone(timedelta(hours=-3))
    source = Event(
        event_id=uuid.uuid4(), tenant_id="reconstruct", event_type="test.initial",
        occurred_at=Event.create("x", "x").occurred_at.astimezone(non_utc),
        payload={"items": [1, {"key": "value"}]},
    )
    episode = CognitiveEpisode.create(source)
    journal.create_episode_with_event(episode, source)
    event = journal.get_event("reconstruct", source.event_id)
    rebuilt = journal.get_episode("reconstruct", episode.episode_id)
    assert event is not None and rebuilt is not None
    assert event.occurred_at.utcoffset() == timezone.utc.utcoffset(event.occurred_at)
    assert rebuilt.created_at.utcoffset() == timezone.utc.utcoffset(rebuilt.created_at)
    assert event.to_dict()["payload"] == {"items": [1, {"key": "value"}]}
    with pytest.raises(TypeError):
        event.payload["items"][1]["key"] = "changed"
    with pytest.raises(AttributeError):
        rebuilt.tenant_id = "changed"


def test_persistence_after_engine_and_journal_reconstruction(journal, migrated_engine) -> None:
    from sqlalchemy import create_engine
    from mike_app.runtime.postgresql_episode_journal import PostgreSQLEpisodeJournal

    first, episode = _initial(journal, "persistent")
    migrated_engine.dispose()
    replacement_engine = create_engine(_validated_url(), pool_pre_ping=True)
    try:
        replacement = PostgreSQLEpisodeJournal(replacement_engine)
        assert replacement.get_event("persistent", first.event_id) == first
        assert replacement.get_episode("persistent", episode.episode_id) == episode
    finally:
        replacement_engine.dispose()


def test_same_version_concurrency_has_one_winner(journal) -> None:
    from mike_app.runtime.episode_journal import EpisodeConcurrencyConflictError
    from mike_app.runtime.event import Event

    first, episode = _initial(journal, "concurrent-same")
    candidates = [Event.create(first.tenant_id, f"test.concurrent.{index}") for index in range(2)]
    barrier = threading.Barrier(2)

    def append(candidate):
        barrier.wait()
        try:
            journal.append_event(first.tenant_id, episode.episode_id, candidate, episode.event_ids)
            return "committed"
        except EpisodeConcurrencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append, candidates))
    assert sorted(outcomes) == ["committed", "conflict"]
    stored = journal.list_events(first.tenant_id)
    assert len(stored) == 2
    assert sum(candidate.event_id in {event.event_id for event in stored} for candidate in candidates) == 1


def test_different_episode_appends_can_both_commit(journal) -> None:
    from mike_app.runtime.event import Event

    first_a, episode_a = _initial(journal, "concurrent-different")
    first_b, episode_b = _initial(journal, "concurrent-different")
    next_a = Event.create(first_a.tenant_id, "test.next.a")
    next_b = Event.create(first_b.tenant_id, "test.next.b")
    barrier = threading.Barrier(2)

    def append(args):
        episode, event = args
        barrier.wait()
        return journal.append_event(event.tenant_id, episode.episode_id, event, episode.event_ids)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, [(episode_a, next_a), (episode_b, next_b)]))
    assert all(len(result.event_ids) == 2 for result in results)


def _outbox_values(journal, tenant_id: str):
    from datetime import datetime, timezone
    from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
    from mike_app.runtime.event import Event
    from tests.episode_journal_contract import build_ten_event_episode

    episode, events = build_ten_event_episode(journal, tenant_id)
    ready = events[-1]
    delivery = Event.create(
        tenant_id,
        "communication.delivery_requested",
        {
            "source_event_id": str(events[0].event_id),
            "response_ready_event_id": str(ready.event_id),
            "channel": ready.payload["channel"],
            "external_conversation_id": ready.payload["external_conversation_id"],
            "outbound_sender_id": ready.payload["outbound_sender_id"],
            "outbound_recipient_id": ready.payload["outbound_recipient_id"],
            "idempotency_key": str(ready.event_id),
            "request_method": "transactional_outbox",
        },
        correlation_id=ready.correlation_id,
        causation_id=str(ready.event_id),
    )
    entry = DeliveryOutboxEntry(
        outbox_id=uuid.uuid4(), tenant_id=tenant_id,
        episode_id=episode.episode_id,
        delivery_request_event_id=delivery.event_id,
        response_ready_event_id=ready.event_id,
        idempotency_key=str(ready.event_id),
        channel=ready.payload["channel"],
        external_conversation_id=ready.payload["external_conversation_id"],
        outbound_sender_id=ready.payload["outbound_sender_id"],
        outbound_recipient_id=ready.payload["outbound_recipient_id"],
        response_type=ready.payload["response_type"],
        language=ready.payload["language"], text=ready.payload["text"],
        status="pending", created_at=datetime.now(timezone.utc), schema_version=1,
    )
    return episode, events, delivery, entry


def test_outbox_database_failure_rolls_back_event_episode_and_outbox(
    journal, migrated_engine, monkeypatch
) -> None:
    from sqlalchemy import event as sqlalchemy_event, text

    episode, _, delivery, entry = _outbox_values(journal, "outbox-rollback")
    before = journal.get_episode(entry.tenant_id, episode.episode_id)
    original = journal._outbox_row

    def invalid_row(value):
        row = original(value)
        row.status = "invalid"
        return row

    monkeypatch.setattr(journal, "_outbox_row", invalid_row)
    observed_outbox_inserts = []

    def verify_event_before_outbox(
        connection, cursor, statement, parameters, context, executemany
    ):
        if statement.startswith("INSERT INTO delivery_outbox"):
            assert connection.scalar(
                text("SELECT count(*) FROM events WHERE event_id = :event_id"),
                {"event_id": delivery.event_id},
            ) == 1
            observed_outbox_inserts.append(statement)

    sqlalchemy_event.listen(
        migrated_engine, "before_cursor_execute", verify_event_before_outbox
    )
    try:
        with pytest.raises(ValueError, match="integrity constraint violated"):
            journal.append_event_with_outbox(
                entry.tenant_id, episode.episode_id, delivery,
                episode.event_ids, entry,
            )
    finally:
        sqlalchemy_event.remove(
            migrated_engine, "before_cursor_execute", verify_event_before_outbox
        )
    assert len(observed_outbox_inserts) == 1
    assert journal.get_event(entry.tenant_id, delivery.event_id) is None
    assert journal.get_episode(entry.tenant_id, episode.episode_id) == before
    assert journal.get_outbox_entry(entry.tenant_id, entry.outbox_id) is None
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM delivery_outbox")) == 0


def test_outbox_foreign_key_failure_is_not_reported_as_duplicate(
    journal, monkeypatch
) -> None:
    episode, _, delivery, entry = _outbox_values(journal, "outbox-fk")
    original = journal._outbox_row

    def invalid_row(value):
        row = original(value)
        row.response_ready_event_id = uuid.uuid4()
        return row

    monkeypatch.setattr(journal, "_outbox_row", invalid_row)
    with pytest.raises(ValueError, match="integrity constraint violated") as error:
        journal.append_event_with_outbox(
            entry.tenant_id, episode.episode_id, delivery,
            episode.event_ids, entry,
        )
    assert "duplicate" not in str(error.value)
    assert journal.get_event(entry.tenant_id, delivery.event_id) is None


@pytest.mark.parametrize(
    ("field_name", "foreign_tenant"),
    [
        ("response_ready_event_id", "ownership-primary"),
        ("response_ready_event_id", "ownership-foreign-tenant"),
        ("delivery_request_event_id", "ownership-primary"),
        ("delivery_request_event_id", "ownership-foreign-tenant"),
    ],
)
def test_composite_event_foreign_keys_reject_existing_foreign_ownership(
    journal, monkeypatch, field_name: str, foreign_tenant: str
) -> None:
    episode, _, delivery, entry = _outbox_values(
        journal, "ownership-primary"
    )
    _, foreign_events, _, _ = _outbox_values(journal, foreign_tenant)
    foreign_event_id = foreign_events[-1].event_id
    original = journal._outbox_row

    def invalid_row(value):
        row = original(value)
        setattr(row, field_name, foreign_event_id)
        return row

    monkeypatch.setattr(journal, "_outbox_row", invalid_row)
    with pytest.raises(ValueError, match="integrity constraint violated"):
        journal.append_event_with_outbox(
            entry.tenant_id,
            episode.episode_id,
            delivery,
            episode.event_ids,
            entry,
        )

    assert journal.get_event(entry.tenant_id, delivery.event_id) is None
    assert journal.get_outbox_entry(entry.tenant_id, entry.outbox_id) is None


def test_concurrent_outbox_append_has_one_commit_and_no_orphans(
    journal, migrated_engine
) -> None:
    from dataclasses import replace
    from mike_app.runtime.episode_journal import EpisodeConcurrencyConflictError
    from mike_app.runtime.event import Event
    from mike_app.runtime.postgresql_episode_journal import PostgreSQLEpisodeJournal

    episode, events, first_delivery, first_entry = _outbox_values(
        journal, "outbox-concurrent"
    )
    second_delivery = Event.create(
        first_delivery.tenant_id,
        first_delivery.event_type,
        first_delivery.to_dict()["payload"],
        correlation_id=first_delivery.correlation_id,
        causation_id=first_delivery.causation_id,
    )
    second_entry = replace(
        first_entry,
        outbox_id=uuid.uuid4(),
        delivery_request_event_id=second_delivery.event_id,
    )
    candidates = (
        (PostgreSQLEpisodeJournal(migrated_engine), first_delivery, first_entry),
        (PostgreSQLEpisodeJournal(migrated_engine), second_delivery, second_entry),
    )
    barrier = threading.Barrier(2)

    def append(candidate):
        candidate_journal, event, entry = candidate
        barrier.wait()
        try:
            candidate_journal.append_event_with_outbox(
                entry.tenant_id, episode.episode_id, event,
                episode.event_ids, entry,
            )
            return "committed"
        except EpisodeConcurrencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append, candidates))
    assert sorted(outcomes) == ["committed", "conflict"]
    stored_events = journal.list_events(first_entry.tenant_id)
    stored_outbox = journal.list_outbox_entries(first_entry.tenant_id)
    assert len(stored_events) == 11
    assert tuple(event.event_id for event in stored_events[:10]) == tuple(
        event.event_id for event in events
    )
    assert len(stored_outbox) == 1
    assert stored_outbox[0].delivery_request_event_id == stored_events[-1].event_id


def test_postgres_http_pipeline_and_pool_shutdown(migrated_engine, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from mike_app.core.settings import Settings
    from mike_app.handlers.message_perception import MessagePerceptionHandler
    import mike_app.main as main_module
    from mike_app.perception.model import PerceptionResult
    from mike_app.perception.service import PerceptionService

    class FakePerceptionClient:
        def perceive(self, text: str) -> PerceptionResult:
            return PerceptionResult("es", "greeting", 0.91, {})

    created_engines = []
    real_create_engine = main_module.create_engine

    def recording_create_engine(*args, **kwargs):
        engine = real_create_engine(*args, **kwargs)
        created_engines.append(engine)
        return engine

    monkeypatch.setattr(main_module, "create_engine", recording_create_engine)

    settings = Settings("mike", "0.1.0", "test", None, None, "postgres", _validated_url(), _validated_url())
    application = main_module.create_app(settings)
    with TestClient(application) as client:
        handler = MessagePerceptionHandler(
            application.state.episode_coordinator,
            PerceptionService(FakePerceptionClient()),
            application.state.runtime_dispatcher,
        )
        application.state.runtime_handler_registry.register("message.accepted", handler)
        response = client.post("/dev/messages", json={"tenant_id": "http-postgres", "text": "Hola"})
        assert response.status_code == 201
        assert response.json()["event_type"] == "message.received"
        events = application.state.episode_coordinator.list_events("http-postgres")
        assert len(events) == 11
        assert events[-1].event_type == "communication.delivery_requested"
        assert client.get("/health").json() == {"status": "ok", "service": "mike", "version": "0.1.0"}
        assert not hasattr(application.state, "database_engine")
        engine = created_engines[0]
        pool = engine.pool
    assert engine.pool is not pool
