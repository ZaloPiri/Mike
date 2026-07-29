from datetime import datetime, timedelta, timezone
import uuid

import pytest

from mike_app.runtime.event import Event
from mike_app.runtime.episode import CognitiveEpisode


def test_create_generates_uuid_episode_id() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = CognitiveEpisode.create(event)

    assert isinstance(episode.episode_id, uuid.UUID)


def test_create_uses_initial_event_tenant_id() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = CognitiveEpisode.create(event)

    assert episode.tenant_id == "tenant-1"


def test_create_contains_initial_event_id() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = CognitiveEpisode.create(event)

    assert episode.event_ids == (event.event_id,)


def test_timestamps_are_timezone_aware_utc() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = CognitiveEpisode.create(event)

    assert episode.created_at.tzinfo is not None
    assert episode.updated_at.tzinfo is not None
    assert episode.created_at.utcoffset() == timezone.utc.utcoffset(episode.created_at)
    assert episode.updated_at.utcoffset() == timezone.utc.utcoffset(episode.updated_at)


def test_event_ids_is_tuple() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    episode = CognitiveEpisode.create(event)

    assert isinstance(episode.event_ids, tuple)


def test_add_event_returns_new_episode() -> None:
    first_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = CognitiveEpisode.create(first_event)
    second_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")

    next_episode = episode.add_event(second_event)

    assert next_episode is not episode
    assert next_episode.event_ids == (first_event.event_id, second_event.event_id)


def test_original_episode_remains_unchanged_after_add_event() -> None:
    first_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = CognitiveEpisode.create(first_event)
    second_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")

    episode.add_event(second_event)

    assert episode.event_ids == (first_event.event_id,)


def test_event_insertion_order_is_preserved() -> None:
    first_event = Event.create(tenant_id="tenant-1", event_type="test.event.one")
    episode = CognitiveEpisode.create(first_event)
    second_event = Event.create(tenant_id="tenant-1", event_type="test.event.two")
    third_event = Event.create(tenant_id="tenant-1", event_type="test.event.three")

    next_episode = episode.add_event(second_event).add_event(third_event)

    assert next_episode.event_ids == (first_event.event_id, second_event.event_id, third_event.event_id)


def test_cross_tenant_event_is_rejected() -> None:
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))
    other_tenant_event = Event.create(tenant_id="tenant-2", event_type="test.event")

    with pytest.raises(ValueError, match="tenant"):
        episode.add_event(other_tenant_event)


def test_duplicate_event_is_rejected() -> None:
    first_event = Event.create(tenant_id="tenant-1", event_type="test.event")
    episode = CognitiveEpisode.create(first_event)

    with pytest.raises(ValueError, match="already present"):
        episode.add_event(first_event)


def test_non_event_input_is_rejected() -> None:
    episode = CognitiveEpisode.create(Event.create(tenant_id="tenant-1", event_type="test.event"))

    with pytest.raises(TypeError, match="Event"):
        episode.add_event(object())


def test_empty_tenant_id_is_rejected_when_constructing_directly() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            event_ids=(uuid.uuid4(),),
            correlation_id=None,
            schema_version=1,
        )


def test_whitespace_only_tenant_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="   ",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            event_ids=(uuid.uuid4(),),
            correlation_id=None,
            schema_version=1,
        )


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="tenant-1",
            created_at=datetime(2026, 7, 29, 12, 0),
            updated_at=datetime.now(timezone.utc),
            event_ids=(uuid.uuid4(),),
            correlation_id=None,
            schema_version=1,
        )


def test_non_utc_datetime_is_normalized_to_utc() -> None:
    source_time = datetime(2026, 7, 29, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    episode = CognitiveEpisode(
        episode_id=uuid.uuid4(),
        tenant_id="tenant-1",
        created_at=source_time,
        updated_at=source_time,
        event_ids=(uuid.uuid4(),),
        correlation_id=None,
        schema_version=1,
    )

    assert episode.created_at.tzinfo is not None
    assert episode.created_at.utcoffset() == timezone.utc.utcoffset(episode.created_at)
    assert episode.created_at.isoformat().endswith("+00:00")


def test_updated_at_earlier_than_created_at_is_rejected() -> None:
    created_at = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    updated_at = created_at - timedelta(minutes=1)

    with pytest.raises(ValueError, match="updated_at"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="tenant-1",
            created_at=created_at,
            updated_at=updated_at,
            event_ids=(uuid.uuid4(),),
            correlation_id=None,
            schema_version=1,
        )


def test_non_uuid_event_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="uuid"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="tenant-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            event_ids=("not-a-uuid",),
            correlation_id=None,
            schema_version=1,
        )


def test_duplicate_event_ids_are_rejected() -> None:
    duplicate_id = uuid.uuid4()

    with pytest.raises(ValueError, match="duplicate"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="tenant-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            event_ids=(duplicate_id, duplicate_id),
            correlation_id=None,
            schema_version=1,
        )


def test_schema_version_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="tenant-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            event_ids=(uuid.uuid4(),),
            correlation_id=None,
            schema_version=0,
        )


def test_schema_version_bool_is_rejected() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        CognitiveEpisode(
            episode_id=uuid.uuid4(),
            tenant_id="tenant-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            event_ids=(uuid.uuid4(),),
            correlation_id=None,
            schema_version=True,
        )


def test_to_dict_is_json_compatible() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    episode = CognitiveEpisode.create(event)

    result = episode.to_dict()

    assert isinstance(result, dict)
    assert result["episode_id"] == str(episode.episode_id)
    assert result["event_ids"] == [str(event.event_id)]


def test_mutating_to_dict_output_does_not_mutate_episode() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    episode = CognitiveEpisode.create(event)

    result = episode.to_dict()
    result["tenant_id"] = "other"
    result["event_ids"].append("changed")

    assert episode.tenant_id == "tenant-1"
    assert episode.event_ids == (event.event_id,)


def test_explicit_correlation_id_overrides_event_correlation_id() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event", correlation_id="event-corr")

    episode = CognitiveEpisode.create(event, correlation_id="episode-corr")

    assert episode.correlation_id == "episode-corr"


def test_absent_explicit_correlation_id_inherits_event_correlation_id() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event", correlation_id="event-corr")

    episode = CognitiveEpisode.create(event)

    assert episode.correlation_id == "event-corr"
