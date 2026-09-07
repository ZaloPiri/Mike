from __future__ import annotations

import uuid

from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.episode_journal import (
    EpisodeJournal,
    _reject_delivery_requested_for_ordinary_append,
)
from mike_app.runtime.event import Event


class EpisodeCoordinator:
    def __init__(
        self,
        episode_journal: EpisodeJournal,
    ) -> None:
        self._episode_journal = episode_journal

    def start_episode(
        self,
        event: Event,
        correlation_id: str | None = None,
    ) -> CognitiveEpisode:
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        _reject_delivery_requested_for_ordinary_append(event)

        episode = CognitiveEpisode.create(event, correlation_id=correlation_id)
        return self._episode_journal.create_episode_with_event(episode, event)

    def append_to_episode(
        self,
        episode_id: uuid.UUID,
        event: Event,
    ) -> CognitiveEpisode:
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        _reject_delivery_requested_for_ordinary_append(event)

        episode = self._episode_journal.get_episode(
            event.tenant_id, episode_id
        )
        if episode is None:
            raise ValueError("episode not found")

        return self._episode_journal.append_event(
            event.tenant_id,
            episode_id,
            event,
            episode.event_ids,
        )

    def append_to_episode_with_outbox(
        self,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
        outbox_entry: DeliveryOutboxEntry,
    ) -> CognitiveEpisode:
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        if not isinstance(outbox_entry, DeliveryOutboxEntry):
            raise TypeError("outbox_entry must be a DeliveryOutboxEntry")
        return self._episode_journal.append_event_with_outbox(
            event.tenant_id,
            episode_id,
            event,
            expected_event_ids,
            outbox_entry,
        )

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

        for episode in self._episode_journal.list_episodes(tenant_id):
            if event_id in episode.event_ids:
                return episode
        return None

    def get_event(
        self,
        tenant_id: str,
        event_id: uuid.UUID,
    ) -> Event | None:
        if not isinstance(tenant_id, str):
            raise TypeError("tenant_id must be a string")
        if not tenant_id or tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")
        if not isinstance(event_id, uuid.UUID):
            raise TypeError("event_id must be a uuid.UUID")
        return self._episode_journal.get_event(tenant_id, event_id)

    def get_episode(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
    ) -> CognitiveEpisode | None:
        return self._episode_journal.get_episode(tenant_id, episode_id)

    def list_events(
        self,
        tenant_id: str,
        event_type: str | None = None,
    ) -> tuple[Event, ...]:
        return self._episode_journal.list_events(tenant_id, event_type)

    def list_episodes(
        self,
        tenant_id: str,
    ) -> tuple[CognitiveEpisode, ...]:
        return self._episode_journal.list_episodes(tenant_id)

    def get_outbox_entry(
        self,
        tenant_id: str,
        outbox_id: uuid.UUID,
    ) -> DeliveryOutboxEntry | None:
        return self._episode_journal.get_outbox_entry(tenant_id, outbox_id)

    def list_outbox_entries(
        self,
        tenant_id: str,
    ) -> tuple[DeliveryOutboxEntry, ...]:
        return self._episode_journal.list_outbox_entries(tenant_id)
