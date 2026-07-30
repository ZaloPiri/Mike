from __future__ import annotations

import uuid

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore


class EpisodeCoordinator:
    def __init__(
        self,
        event_store: InMemoryEventStore,
        episode_store: InMemoryEpisodeStore,
    ) -> None:
        if not isinstance(event_store, InMemoryEventStore):
            raise TypeError("event_store must be an InMemoryEventStore")
        if not isinstance(episode_store, InMemoryEpisodeStore):
            raise TypeError("episode_store must be an InMemoryEpisodeStore")

        self._event_store = event_store
        self._episode_store = episode_store

    def start_episode(
        self,
        event: Event,
        correlation_id: str | None = None,
    ) -> CognitiveEpisode:
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")

        episode = CognitiveEpisode.create(event, correlation_id=correlation_id)
        self._event_store.append(event)
        self._episode_store.add(episode)
        return episode

    def append_to_episode(
        self,
        episode_id: uuid.UUID,
        event: Event,
    ) -> CognitiveEpisode:
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")

        episode = self._episode_store.get_by_id(event.tenant_id, episode_id)
        if episode is None:
            raise ValueError("episode not found")

        new_episode = episode.add_event(event)
        self._event_store.append(event)
        self._episode_store.update(new_episode)
        return new_episode

    def find_episode_for_event(
        self,
        tenant_id: str,
        event_id: uuid.UUID,
    ) -> CognitiveEpisode | None:
        if not isinstance(tenant_id, str):
            raise TypeError("tenant_id must be a string")
        if not tenant_id or tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")
        if not isinstance(event_id, uuid.UUID):
            raise TypeError("event_id must be a uuid.UUID")

        for episode in self._episode_store.list_for_tenant(tenant_id):
            if event_id in episode.event_ids:
                return episode
        return None
