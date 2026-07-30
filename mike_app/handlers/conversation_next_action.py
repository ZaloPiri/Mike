from __future__ import annotations

import uuid
from collections.abc import Mapping

from mike_app.conversation.action_planning import ConversationActionPlanner
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class ConversationNextActionHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        conversation_action_planner: ConversationActionPlanner,
        runtime_dispatcher: RuntimeDispatcher,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(
            conversation_action_planner,
            ConversationActionPlanner,
        ):
            raise TypeError(
                "conversation_action_planner must be a "
                "ConversationActionPlanner"
            )
        self._episode_coordinator = episode_coordinator
        self._conversation_action_planner = conversation_action_planner
        if not isinstance(runtime_dispatcher, RuntimeDispatcher):
            raise TypeError(
                "runtime_dispatcher must be a RuntimeDispatcher"
            )
        self._runtime_dispatcher = runtime_dispatcher

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        normalized_event = context.event
        if normalized_event.event_type != "perception.normalized":
            raise ValueError(
                "ConversationNextActionHandler requires "
                "perception.normalized"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            normalized_event.tenant_id,
            normalized_event.event_id,
        )
        if episode is None:
            raise ValueError(
                "normalized Event is not contained in an Episode"
            )
        if not isinstance(normalized_event.payload, Mapping):
            raise ValueError("normalized Event payload must be a mapping")

        payload = normalized_event.payload
        required_fields = {
            "source_event_id",
            "accepted_event_id",
            "perceived_event_id",
            "language",
            "intent",
            "confidence",
            "entities",
        }
        if not required_fields.issubset(payload):
            raise ValueError("normalized Event payload is missing fields")

        source_id_value = payload["source_event_id"]
        accepted_id_value = payload["accepted_event_id"]
        perceived_id_value = payload["perceived_event_id"]
        source_id = self._parse_uuid(
            source_id_value,
            "source_event_id",
        )
        accepted_id = self._parse_uuid(
            accepted_id_value,
            "accepted_event_id",
        )
        perceived_id = self._parse_uuid(
            perceived_id_value,
            "perceived_event_id",
        )

        for event_id, event_name in (
            (source_id, "source"),
            (accepted_id, "accepted"),
            (perceived_id, "perceived"),
        ):
            if event_id not in episode.event_ids:
                raise ValueError(
                    f"{event_name} Event is not in the normalized Episode"
                )

        source_event = self._get_event(
            normalized_event.tenant_id,
            source_id,
            "source",
        )
        accepted_event = self._get_event(
            normalized_event.tenant_id,
            accepted_id,
            "accepted",
        )
        perceived_event = self._get_event(
            normalized_event.tenant_id,
            perceived_id,
            "perceived",
        )
        if source_event.event_type != "message.received":
            raise ValueError("source Event must be message.received")
        if accepted_event.event_type != "message.accepted":
            raise ValueError("accepted Event must be message.accepted")
        if perceived_event.event_type != "message.perceived":
            raise ValueError("perceived Event must be message.perceived")
        if not isinstance(accepted_event.payload, Mapping):
            raise ValueError("accepted Event payload must be a mapping")
        if not isinstance(perceived_event.payload, Mapping):
            raise ValueError("perceived Event payload must be a mapping")
        if accepted_event.payload.get(
            "source_event_id"
        ) != source_id_value:
            raise ValueError("accepted Event source_event_id does not match")
        if perceived_event.payload.get(
            "source_event_id"
        ) != source_id_value:
            raise ValueError("perceived Event source_event_id does not match")
        if perceived_event.payload.get(
            "accepted_event_id"
        ) != accepted_id_value:
            raise ValueError(
                "perceived Event accepted_event_id does not match"
            )

        entities = payload["entities"]
        if not isinstance(entities, Mapping):
            raise ValueError("normalized entities must be a mapping")
        action = self._conversation_action_planner.plan(
            intent=payload["intent"],
            entities=dict(entities),
        )
        next_action_event = Event.create(
            tenant_id=normalized_event.tenant_id,
            event_type="conversation.next_action",
            payload={
                "source_event_id": str(source_id),
                "accepted_event_id": str(accepted_id),
                "perceived_event_id": str(perceived_id),
                "normalized_event_id": str(normalized_event.event_id),
                "action": action.action,
                "reason": action.reason,
                "can_continue": action.can_continue,
                "missing_entities": action.missing_entities,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            next_action_event,
        )
        self._runtime_dispatcher.dispatch(
            RuntimeContext.create(next_action_event)
        )

    def _get_event(
        self,
        tenant_id: str,
        event_id: uuid.UUID,
        event_name: str,
    ) -> Event:
        event = self._episode_coordinator.get_event(tenant_id, event_id)
        if event is None:
            raise ValueError(f"{event_name} Event not found")
        return event

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
