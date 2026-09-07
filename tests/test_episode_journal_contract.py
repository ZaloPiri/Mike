from mike_app.runtime.episode_journal import InMemoryEpisodeJournal
from tests.episode_journal_contract import (
    assert_atomic_create_and_append,
    assert_atomic_outbox_append,
    assert_altered_trace_is_rejected,
    assert_canonical_outbox_order,
    assert_delivery_requested_requires_atomic_append,
    assert_exact_version_conflicts,
    assert_tenant_isolation_and_order,
)


def test_in_memory_shared_atomic_contract() -> None:
    assert_atomic_create_and_append(InMemoryEpisodeJournal)


def test_in_memory_shared_version_contract() -> None:
    assert_exact_version_conflicts(InMemoryEpisodeJournal)


def test_in_memory_shared_tenant_and_order_contract() -> None:
    assert_tenant_isolation_and_order(InMemoryEpisodeJournal)


def test_in_memory_shared_atomic_outbox_contract() -> None:
    assert_atomic_outbox_append(InMemoryEpisodeJournal)


def test_in_memory_protects_delivery_requested_append() -> None:
    assert_delivery_requested_requires_atomic_append(InMemoryEpisodeJournal)


def test_in_memory_uses_canonical_outbox_order() -> None:
    assert_canonical_outbox_order(InMemoryEpisodeJournal)


def test_in_memory_rejects_altered_trace_envelopes() -> None:
    assert_altered_trace_is_rejected(InMemoryEpisodeJournal)
