import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.episode_journal import (
    EpisodeConcurrencyConflictError,
    EpisodeJournalView,
    EventJournalView,
    InMemoryEpisodeJournal,
)
from mike_app.runtime.event import Event


def make_initial(
    tenant_id: str = "tenant-1",
) -> tuple[Event, CognitiveEpisode]:
    event = Event.create(tenant_id=tenant_id, event_type="test.initial")
    return event, CognitiveEpisode.create(event)


def test_create_publishes_event_and_episode_together() -> None:
    journal = InMemoryEpisodeJournal()
    event, episode = make_initial()

    result = journal.create_episode_with_event(episode, event)

    assert result is episode
    assert journal.get_event("tenant-1", event.event_id) is event
    assert journal.get_episode("tenant-1", episode.episode_id) is episode
    assert journal.list_events("tenant-1") == (event,)
    assert journal.list_episodes("tenant-1") == (episode,)


@pytest.mark.parametrize("mismatch", ["tenant", "initial_reference"])
def test_failed_create_leaves_no_partial_state(mismatch: str) -> None:
    journal = InMemoryEpisodeJournal()
    event, episode = make_initial()
    if mismatch == "tenant":
        event = Event.create(tenant_id="tenant-2", event_type="test.initial")
    else:
        unrelated = Event.create(
            tenant_id="tenant-1", event_type="test.unrelated"
        )
        episode = CognitiveEpisode.create(unrelated)

    with pytest.raises(ValueError):
        journal.create_episode_with_event(episode, event)

    assert journal.total_event_count() == 0
    assert journal.total_episode_count() == 0


def test_append_publishes_event_and_new_episode_version_together() -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)
    appended = Event.create(tenant_id="tenant-1", event_type="test.next")

    updated = journal.append_event(
        "tenant-1", episode.episode_id, appended, episode.event_ids
    )

    assert journal.get_event("tenant-1", appended.event_id) is appended
    assert journal.get_episode("tenant-1", episode.episode_id) is updated
    assert updated.event_ids == (initial.event_id, appended.event_id)
    assert episode.event_ids == (initial.event_id,)


def test_stale_expected_version_rejects_without_partial_write() -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)
    accepted = Event.create(tenant_id="tenant-1", event_type="test.accepted")
    journal.append_event(
        "tenant-1", episode.episode_id, accepted, episode.event_ids
    )
    stale = Event.create(tenant_id="tenant-1", event_type="test.stale")

    with pytest.raises(EpisodeConcurrencyConflictError):
        journal.append_event(
            "tenant-1", episode.episode_id, stale, episode.event_ids
        )

    assert journal.get_event("tenant-1", stale.event_id) is None
    assert journal.list_events("tenant-1") == (initial, accepted)
    stored = journal.get_episode("tenant-1", episode.episode_id)
    assert stored is not None
    assert stored.event_ids == (initial.event_id, accepted.event_id)


@pytest.mark.parametrize(
    "version_mutation",
    ["incorrect", "incomplete", "additional", "reordered"],
)
def test_exact_expected_version_is_required(
    version_mutation: str,
) -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)
    second = Event.create(tenant_id="tenant-1", event_type="test.second")
    current = journal.append_event(
        "tenant-1", episode.episode_id, second, episode.event_ids
    )
    candidate = Event.create(
        tenant_id="tenant-1", event_type="test.candidate"
    )
    if version_mutation == "incorrect":
        expected = (uuid.uuid4(), current.event_ids[1])
    elif version_mutation == "incomplete":
        expected = current.event_ids[:-1]
    elif version_mutation == "additional":
        expected = current.event_ids + (uuid.uuid4(),)
    else:
        expected = tuple(reversed(current.event_ids))

    with pytest.raises(EpisodeConcurrencyConflictError):
        journal.append_event(
            "tenant-1", episode.episode_id, candidate, expected
        )

    assert journal.get_event("tenant-1", candidate.event_id) is None
    assert journal.get_episode("tenant-1", episode.episode_id) is current


def test_duplicate_event_is_rejected_without_episode_change() -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)

    with pytest.raises(ValueError, match="duplicate event_id"):
        journal.append_event(
            "tenant-1", episode.episode_id, initial, episode.event_ids
        )

    assert journal.list_events("tenant-1") == (initial,)
    assert journal.get_episode("tenant-1", episode.episode_id) is episode


def test_event_id_is_globally_unique_across_tenants() -> None:
    journal = InMemoryEpisodeJournal()
    first, first_episode = make_initial("tenant-1")
    second, second_episode = make_initial("tenant-2")
    journal.create_episode_with_event(first_episode, first)
    journal.create_episode_with_event(second_episode, second)
    duplicate = Event(
        event_id=first.event_id,
        tenant_id="tenant-2",
        event_type="test.duplicate",
        occurred_at=first.occurred_at,
        payload={},
    )

    with pytest.raises(ValueError, match="duplicate event_id"):
        journal.append_event(
            "tenant-2",
            second_episode.episode_id,
            duplicate,
            second_episode.event_ids,
        )

    assert journal.list_events("tenant-1") == (first,)
    assert journal.list_events("tenant-2") == (second,)
    assert (
        journal.get_episode("tenant-2", second_episode.episode_id)
        is second_episode
    )


def test_cross_tenant_access_and_append_are_rejected() -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)
    foreign = Event.create(tenant_id="tenant-2", event_type="test.foreign")

    assert journal.get_event("tenant-2", initial.event_id) is None
    assert journal.get_episode("tenant-2", episode.episode_id) is None
    assert journal.list_events("tenant-2") == ()
    assert journal.list_episodes("tenant-2") == ()
    with pytest.raises(ValueError, match="episode not found"):
        journal.append_event(
            "tenant-2", episode.episode_id, foreign, episode.event_ids
        )
    assert journal.get_event("tenant-2", foreign.event_id) is None


def test_concurrent_append_same_version_allows_exactly_one_winner() -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)
    candidates = tuple(
        Event.create(tenant_id="tenant-1", event_type=f"test.next.{index}")
        for index in range(2)
    )
    barrier = threading.Barrier(2)

    def append(event: Event) -> str:
        barrier.wait()
        try:
            journal.append_event(
                "tenant-1", episode.episode_id, event, episode.event_ids
            )
        except EpisodeConcurrencyConflictError:
            return "conflict"
        return "appended"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(append, candidates))

    assert sorted(outcomes) == ["appended", "conflict"]
    events = journal.list_events("tenant-1")
    stored = journal.get_episode("tenant-1", episode.episode_id)
    assert len(events) == 2
    assert stored is not None
    assert stored.event_ids == tuple(event.event_id for event in events)


def test_concurrent_appends_for_different_tenants_remain_isolated() -> None:
    journal = InMemoryEpisodeJournal()
    initial_1, episode_1 = make_initial("tenant-1")
    initial_2, episode_2 = make_initial("tenant-2")
    journal.create_episode_with_event(episode_1, initial_1)
    journal.create_episode_with_event(episode_2, initial_2)
    next_1 = Event.create(tenant_id="tenant-1", event_type="test.next")
    next_2 = Event.create(tenant_id="tenant-2", event_type="test.next")
    barrier = threading.Barrier(2)

    def append(
        tenant_id: str,
        episode: CognitiveEpisode,
        event: Event,
    ) -> None:
        barrier.wait()
        journal.append_event(
            tenant_id, episode.episode_id, event, episode.event_ids
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(append, "tenant-1", episode_1, next_1),
            executor.submit(append, "tenant-2", episode_2, next_2),
        )
        for future in futures:
            future.result()

    assert journal.list_events("tenant-1") == (initial_1, next_1)
    assert journal.list_events("tenant-2") == (initial_2, next_2)


def test_event_filter_preserves_tenant_order() -> None:
    journal = InMemoryEpisodeJournal()
    initial, episode = make_initial()
    journal.create_episode_with_event(episode, initial)
    first = Event.create(tenant_id="tenant-1", event_type="test.match")
    updated = journal.append_event(
        "tenant-1", episode.episode_id, first, episode.event_ids
    )
    other = Event.create(tenant_id="tenant-1", event_type="test.other")
    updated = journal.append_event(
        "tenant-1", episode.episode_id, other, updated.event_ids
    )
    second = Event.create(tenant_id="tenant-1", event_type="test.match")
    journal.append_event(
        "tenant-1", episode.episode_id, second, updated.event_ids
    )

    assert journal.list_events("tenant-1", "test.match") == (
        first,
        second,
    )


@pytest.mark.parametrize("invalid", [None, object(), "event"])
def test_create_rejects_non_event_without_state(invalid: object) -> None:
    journal = InMemoryEpisodeJournal()
    event, episode = make_initial()

    with pytest.raises(TypeError, match="Event"):
        journal.create_episode_with_event(episode, invalid)

    assert journal.total_event_count() == 0
    assert journal.total_episode_count() == 0


@pytest.mark.parametrize("invalid", [None, object(), "episode"])
def test_create_rejects_non_episode_without_state(invalid: object) -> None:
    journal = InMemoryEpisodeJournal()
    event, _ = make_initial()

    with pytest.raises(TypeError, match="CognitiveEpisode"):
        journal.create_episode_with_event(invalid, event)

    assert journal.total_event_count() == 0
    assert journal.total_episode_count() == 0


def test_create_rejects_duplicate_event_and_episode() -> None:
    journal = InMemoryEpisodeJournal()
    event, episode = make_initial()
    journal.create_episode_with_event(episode, event)

    with pytest.raises(ValueError, match="duplicate event_id"):
        journal.create_episode_with_event(episode, event)

    assert journal.list_events("tenant-1") == (event,)
    assert journal.list_episodes("tenant-1") == (episode,)


@pytest.mark.parametrize("invalid", [None, 1, object()])
def test_append_rejects_non_string_tenant(invalid: object) -> None:
    journal = InMemoryEpisodeJournal()
    event = Event.create(tenant_id="tenant-1", event_type="test.next")

    with pytest.raises(TypeError, match="string"):
        journal.append_event(invalid, event.event_id, event, ())


@pytest.mark.parametrize("invalid", ["", " ", "\t", "\n"])
def test_append_rejects_empty_tenant(invalid: str) -> None:
    journal = InMemoryEpisodeJournal()
    event = Event.create(tenant_id="tenant-1", event_type="test.next")

    with pytest.raises(ValueError, match="tenant_id"):
        journal.append_event(invalid, event.event_id, event, ())


@pytest.mark.parametrize("invalid", [None, "id", 1, object()])
def test_append_rejects_non_uuid_episode_id(invalid: object) -> None:
    journal = InMemoryEpisodeJournal()
    event = Event.create(tenant_id="tenant-1", event_type="test.next")

    with pytest.raises(TypeError, match="uuid.UUID"):
        journal.append_event("tenant-1", invalid, event, ())


@pytest.mark.parametrize("invalid", [None, [], ["id"], ("id",)])
def test_append_rejects_invalid_expected_version(invalid: object) -> None:
    journal = InMemoryEpisodeJournal()
    event = Event.create(tenant_id="tenant-1", event_type="test.next")

    with pytest.raises(TypeError, match="expected_event_ids"):
        journal.append_event(
            "tenant-1", event.event_id, event, invalid
        )


@pytest.mark.parametrize("method", ["get_event", "get_episode"])
def test_get_rejects_non_uuid_identifier(method: str) -> None:
    journal = InMemoryEpisodeJournal()

    with pytest.raises(TypeError, match="uuid.UUID"):
        getattr(journal, method)("tenant-1", "not-a-uuid")


@pytest.mark.parametrize("invalid", [1, object()])
def test_event_filter_rejects_non_string_type(invalid: object) -> None:
    journal = InMemoryEpisodeJournal()

    with pytest.raises(TypeError, match="event_type"):
        journal.list_events("tenant-1", invalid)


@pytest.mark.parametrize("invalid", ["", " ", "\t", "\n"])
def test_event_filter_rejects_empty_type(invalid: str) -> None:
    journal = InMemoryEpisodeJournal()

    with pytest.raises(ValueError, match="event_type"):
        journal.list_events("tenant-1", invalid)


def test_read_only_views_share_the_journal_without_mutation_methods() -> None:
    journal = InMemoryEpisodeJournal()
    event, episode = make_initial()
    journal.create_episode_with_event(episode, event)
    event_view = EventJournalView(journal)
    episode_view = EpisodeJournalView(journal)

    assert event_view.get_by_id("tenant-1", event.event_id) is event
    assert event_view.list_for_tenant("tenant-1") == (event,)
    assert event_view.count_for_tenant("tenant-1") == 1
    assert event_view.total_count() == 1
    assert episode_view.get_by_id("tenant-1", episode.episode_id) is episode
    assert episode_view.list_for_tenant("tenant-1") == (episode,)
    assert episode_view.count_for_tenant("tenant-1") == 1
    assert episode_view.total_count() == 1
    assert not hasattr(event_view, "append")
    assert not hasattr(episode_view, "add")
    assert not hasattr(episode_view, "update")
    assert not hasattr(event_view, "_journal")
    assert not hasattr(episode_view, "_journal")
