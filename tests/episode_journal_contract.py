from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest

from mike_app.runtime.episode import CognitiveEpisode
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
