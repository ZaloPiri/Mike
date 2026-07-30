from __future__ import annotations

import uuid
from collections.abc import Mapping

from mike_app.perception.normalization import PerceptionNormalizer
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class PerceptionNormalizationHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        perception_normalizer: PerceptionNormalizer,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(perception_normalizer, PerceptionNormalizer):
            raise TypeError(
                "perception_normalizer must be a PerceptionNormalizer"
            )
        self._episode_coordinator = episode_coordinator
        self._perception_normalizer = perception_normalizer

    def __call__(
        self,
        context: RuntimeContext,
    ) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        perceived_event = context.event
        if perceived_event.event_type != "message.perceived":
            raise ValueError(
                "PerceptionNormalizationHandler requires message.perceived"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            perceived_event.tenant_id,
            perceived_event.event_id,
        )
        if episode is None:
            raise ValueError("perceived Event is not contained in an Episode")
        if not isinstance(perceived_event.payload, Mapping):
            raise ValueError("perceived Event payload must be a mapping")

        payload = perceived_event.payload
        required_fields = {
            "source_event_id",
            "accepted_event_id",
            "language",
            "intent",
            "confidence",
            "entities",
        }
        if not required_fields.issubset(payload):
            raise ValueError("perceived Event payload is missing fields")

        source_id_value = payload["source_event_id"]
        accepted_id_value = payload["accepted_event_id"]
        source_id = self._parse_uuid(source_id_value, "source_event_id")
        accepted_id = self._parse_uuid(
            accepted_id_value,
            "accepted_event_id",
        )
        if source_id not in episode.event_ids:
            raise ValueError("source Event is not in the perceived Episode")
        if accepted_id not in episode.event_ids:
            raise ValueError("accepted Event is not in the perceived Episode")

        source_event = self._episode_coordinator.get_event(
            perceived_event.tenant_id,
            source_id,
        )
        accepted_event = self._episode_coordinator.get_event(
            perceived_event.tenant_id,
            accepted_id,
        )
        if source_event is None:
            raise ValueError("source Event not found")
        if accepted_event is None:
            raise ValueError("accepted Event not found")
        if source_event.event_type != "message.received":
            raise ValueError("source Event must be message.received")
        if accepted_event.event_type != "message.accepted":
            raise ValueError("accepted Event must be message.accepted")
        if not isinstance(accepted_event.payload, Mapping):
            raise ValueError("accepted Event payload must be a mapping")
        if accepted_event.payload.get("source_event_id") != source_id_value:
            raise ValueError("accepted Event source_event_id does not match")

        entities = payload["entities"]
        if not isinstance(entities, Mapping):
            raise ValueError("perceived entities must be a mapping")
        normalized = self._perception_normalizer.normalize(
            language=payload["language"],
            intent=payload["intent"],
            confidence=payload["confidence"],
            entities=dict(entities),
        )
        normalized_event = Event.create(
            tenant_id=perceived_event.tenant_id,
            event_type="perception.normalized",
            payload={
                "source_event_id": str(source_id),
                "accepted_event_id": str(accepted_id),
                "perceived_event_id": str(perceived_event.event_id),
                "language": normalized.language,
                "intent": normalized.intent,
                "confidence": normalized.confidence,
                "entities": normalized.entities,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            normalized_event,
        )

    @staticmethod
    def _parse_uuid(value: object, field_name: str) -> uuid.UUID:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a UUID string")
        try:
            return uuid.UUID(value)
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be a UUID string"
            ) from exc
