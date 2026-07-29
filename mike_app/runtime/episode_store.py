from __future__ import annotations

import uuid

from mike_app.runtime.episode import CognitiveEpisode


class InMemoryEpisodeStore:
    def __init__(self) -> None:
        self._episodes_by_id: dict[uuid.UUID, CognitiveEpisode] = {}
        self._tenant_episode_ids: dict[str, list[uuid.UUID]] = {}

    def add(self, episode: CognitiveEpisode) -> None:
        if not isinstance(episode, CognitiveEpisode):
            raise TypeError("add expects a CognitiveEpisode instance")
        if episode.episode_id in self._episodes_by_id:
            raise ValueError("episode_id already exists")

        self._episodes_by_id[episode.episode_id] = episode
        self._tenant_episode_ids.setdefault(episode.tenant_id, []).append(episode.episode_id)

    def update(self, episode: CognitiveEpisode) -> None:
        if not isinstance(episode, CognitiveEpisode):
            raise TypeError("update expects a CognitiveEpisode instance")
        if episode.episode_id not in self._episodes_by_id:
            raise ValueError("episode does not exist")

        stored_episode = self._episodes_by_id[episode.episode_id]
        if episode.tenant_id != stored_episode.tenant_id:
            raise ValueError("episode tenant does not match stored episode")
        if episode.created_at != stored_episode.created_at:
            raise ValueError("created_at cannot change")
        if episode.updated_at < stored_episode.updated_at:
            raise ValueError("updated_at cannot move backwards")

        self._episodes_by_id[episode.episode_id] = episode

    def get_by_id(self, tenant_id: str, episode_id: uuid.UUID) -> CognitiveEpisode | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")

        episode = self._episodes_by_id.get(episode_id)
        if episode is None:
            return None
        if episode.tenant_id != tenant_id:
            return None
        return episode

    def list_for_tenant(self, tenant_id: str) -> tuple[CognitiveEpisode, ...]:
        self._validate_tenant_id(tenant_id)
        episode_ids = self._tenant_episode_ids.get(tenant_id, [])
        return tuple(self._episodes_by_id[episode_id] for episode_id in episode_ids)

    def count_for_tenant(self, tenant_id: str) -> int:
        self._validate_tenant_id(tenant_id)
        return len(self._tenant_episode_ids.get(tenant_id, []))

    def total_count(self) -> int:
        return len(self._episodes_by_id)

    def _validate_tenant_id(self, tenant_id: str) -> None:
        if not tenant_id or tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")
