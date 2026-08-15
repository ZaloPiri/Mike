from mike_app.runtime.episode_journal import InMemoryEpisodeJournal
from tests.episode_journal_contract import (
    assert_atomic_create_and_append,
    assert_exact_version_conflicts,
    assert_tenant_isolation_and_order,
)


def test_in_memory_shared_atomic_contract() -> None:
    assert_atomic_create_and_append(InMemoryEpisodeJournal)


def test_in_memory_shared_version_contract() -> None:
    assert_exact_version_conflicts(InMemoryEpisodeJournal)


def test_in_memory_shared_tenant_and_order_contract() -> None:
    assert_tenant_isolation_and_order(InMemoryEpisodeJournal)
