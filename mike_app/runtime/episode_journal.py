from __future__ import annotations

import uuid
from collections.abc import Sequence
from threading import Lock
from typing import Protocol

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.event import Event


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

    def total_event_count(self) -> int: ...

    def total_episode_count(self) -> int: ...


class InMemoryEpisodeJournal:
    def __init__(self) -> None:
        self._events_by_id: dict[uuid.UUID, Event] = {}
        self._tenant_events: dict[str, list[Event]] = {}
        self._episodes_by_id: dict[uuid.UUID, CognitiveEpisode] = {}
        self._tenant_episode_ids: dict[str, list[uuid.UUID]] = {}
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
