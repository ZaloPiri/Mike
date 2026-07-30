from __future__ import annotations

import uuid
from collections.abc import Mapping

from mike_app.perception.service import PerceptionService
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class MessagePerceptionHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        perception_service: PerceptionService,
        runtime_dispatcher: RuntimeDispatcher,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(perception_service, PerceptionService):
            raise TypeError(
                "perception_service must be a PerceptionService"
            )
        if not isinstance(runtime_dispatcher, RuntimeDispatcher):
            raise TypeError(
                "runtime_dispatcher must be a RuntimeDispatcher"
            )
        self._episode_coordinator = episode_coordinator
        self._perception_service = perception_service
        self._runtime_dispatcher = runtime_dispatcher

    def __call__(
        self,
        context: RuntimeContext,
    ) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        accepted_event = context.event
        if accepted_event.event_type != "message.accepted":
            raise ValueError(
                "MessagePerceptionHandler requires message.accepted"
            )

        episode = self._episode_coordinator.find_episode_for_event(
            accepted_event.tenant_id,
            accepted_event.event_id,
        )
        if episode is None:
            raise ValueError("accepted Event is not contained in an Episode")

        payload = accepted_event.payload
        if not isinstance(payload, Mapping):
            raise ValueError("accepted Event payload must be a mapping")
        source_event_id_value = payload.get("source_event_id")
        if not isinstance(source_event_id_value, str):
            raise ValueError("source_event_id must be a UUID string")
        try:
            source_event_id = uuid.UUID(source_event_id_value)
        except ValueError as exc:
            raise ValueError(
                "source_event_id must be a UUID string"
            ) from exc
        if source_event_id not in episode.event_ids:
            raise ValueError(
                "source Event is not contained in the accepted Episode"
            )

        source_event = self._episode_coordinator.get_event(
            accepted_event.tenant_id,
            source_event_id,
        )
        if source_event is None:
            raise ValueError("source Event not found")
        if source_event.event_type != "message.received":
            raise ValueError("source Event must be message.received")
        if not isinstance(source_event.payload, Mapping):
            raise ValueError("source Event payload must be a mapping")
        text = source_event.payload.get("text")
        if not isinstance(text, str):
            raise ValueError("source Event text must be a string")
        if not text or text.strip() == "":
            raise ValueError("source Event text must be non-empty")

        result = self._perception_service.perceive(text)
        perceived_event = Event.create(
            tenant_id=accepted_event.tenant_id,
            event_type="message.perceived",
            payload={
                "source_event_id": str(source_event.event_id),
                "accepted_event_id": str(accepted_event.event_id),
                "language": result.language,
                "intent": result.intent,
                "confidence": result.confidence,
                "entities": result.entities,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            perceived_event,
        )
        self._runtime_dispatcher.dispatch(
            RuntimeContext.create(perceived_event)
        )
