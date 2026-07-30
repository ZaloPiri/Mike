from __future__ import annotations

import uuid
from collections.abc import Mapping

from mike_app.conversation.response_planning import ResponseRequestPlanner
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class ConversationResponseRequestHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        response_request_planner: ResponseRequestPlanner,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(
            response_request_planner,
            ResponseRequestPlanner,
        ):
            raise TypeError(
                "response_request_planner must be a "
                "ResponseRequestPlanner"
            )
        self._episode_coordinator = episode_coordinator
        self._response_request_planner = response_request_planner

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        next_action_event = context.event
        if next_action_event.event_type != "conversation.next_action":
            raise ValueError(
                "ConversationResponseRequestHandler requires "
                "conversation.next_action"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            next_action_event.tenant_id,
            next_action_event.event_id,
        )
        if episode is None:
            raise ValueError(
                "next-action Event is not contained in an Episode"
            )
        if not isinstance(next_action_event.payload, Mapping):
            raise ValueError("next-action Event payload must be a mapping")

        payload = next_action_event.payload
        required_fields = {
            "source_event_id",
            "accepted_event_id",
            "perceived_event_id",
            "normalized_event_id",
            "action",
            "reason",
            "can_continue",
            "missing_entities",
        }
        if not required_fields.issubset(payload):
            raise ValueError("next-action Event payload is missing fields")

        reference_values = {
            field_name: payload[field_name]
            for field_name in (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
                "normalized_event_id",
            )
        }
        reference_ids = {
            field_name: self._parse_uuid(value, field_name)
            for field_name, value in reference_values.items()
        }
        for field_name, event_id in reference_ids.items():
            if event_id not in episode.event_ids:
                event_name = field_name.removesuffix("_event_id")
                raise ValueError(
                    f"{event_name} Event is not in the next-action Episode"
                )

        source_event = self._get_event(
            next_action_event.tenant_id,
            reference_ids["source_event_id"],
            "source",
        )
        accepted_event = self._get_event(
            next_action_event.tenant_id,
            reference_ids["accepted_event_id"],
            "accepted",
        )
        perceived_event = self._get_event(
            next_action_event.tenant_id,
            reference_ids["perceived_event_id"],
            "perceived",
        )
        normalized_event = self._get_event(
            next_action_event.tenant_id,
            reference_ids["normalized_event_id"],
            "normalized",
        )

        expected_types = (
            (source_event, "message.received", "source"),
            (accepted_event, "message.accepted", "accepted"),
            (perceived_event, "message.perceived", "perceived"),
            (normalized_event, "perception.normalized", "normalized"),
        )
        for event, expected_type, event_name in expected_types:
            if event.event_type != expected_type:
                raise ValueError(
                    f"{event_name} Event must be {expected_type}"
                )
        for event, event_name in (
            (accepted_event, "accepted"),
            (perceived_event, "perceived"),
            (normalized_event, "normalized"),
        ):
            if not isinstance(event.payload, Mapping):
                raise ValueError(
                    f"{event_name} Event payload must be a mapping"
                )

        source_value = reference_values["source_event_id"]
        accepted_value = reference_values["accepted_event_id"]
        perceived_value = reference_values["perceived_event_id"]
        if accepted_event.payload.get("source_event_id") != source_value:
            raise ValueError("accepted Event source_event_id does not match")
        if perceived_event.payload.get("source_event_id") != source_value:
            raise ValueError("perceived Event source_event_id does not match")
        if (
            perceived_event.payload.get("accepted_event_id")
            != accepted_value
        ):
            raise ValueError(
                "perceived Event accepted_event_id does not match"
            )
        if normalized_event.payload.get("source_event_id") != source_value:
            raise ValueError(
                "normalized Event source_event_id does not match"
            )
        if (
            normalized_event.payload.get("accepted_event_id")
            != accepted_value
        ):
            raise ValueError(
                "normalized Event accepted_event_id does not match"
            )
        if (
            normalized_event.payload.get("perceived_event_id")
            != perceived_value
        ):
            raise ValueError(
                "normalized Event perceived_event_id does not match"
            )

        normalized_required_fields = {"language", "intent", "entities"}
        if not normalized_required_fields.issubset(
            normalized_event.payload
        ):
            raise ValueError("normalized Event payload is missing fields")
        entities = normalized_event.payload["entities"]
        if not isinstance(entities, Mapping):
            raise ValueError("normalized entities must be a mapping")
        missing_entities = payload["missing_entities"]
        if not isinstance(missing_entities, (list, tuple)):
            raise ValueError("missing_entities must be a sequence")

        response_request = self._response_request_planner.plan(
            action=payload["action"],
            reason=payload["reason"],
            can_continue=payload["can_continue"],
            missing_entities=missing_entities,
            language=normalized_event.payload["language"],
            intent=normalized_event.payload["intent"],
            entities=dict(entities),
        )
        response_request_event = Event.create(
            tenant_id=next_action_event.tenant_id,
            event_type="conversation.response_request",
            payload={
                "source_event_id": str(reference_ids["source_event_id"]),
                "accepted_event_id": str(
                    reference_ids["accepted_event_id"]
                ),
                "perceived_event_id": str(
                    reference_ids["perceived_event_id"]
                ),
                "normalized_event_id": str(
                    reference_ids["normalized_event_id"]
                ),
                "next_action_event_id": str(next_action_event.event_id),
                "response_type": response_request.response_type,
                "target_language": response_request.target_language,
                "intent": response_request.intent,
                "requested_entities": (
                    response_request.requested_entities
                ),
                "handoff_reason": response_request.handoff_reason,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            response_request_event,
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
