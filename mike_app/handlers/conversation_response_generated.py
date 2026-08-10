from __future__ import annotations

import uuid
from collections.abc import Mapping

from mike_app.conversation.action_planning import ConversationNextAction
from mike_app.conversation.response_generation import (
    DeterministicResponseGenerator,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class ConversationResponseGeneratedHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        response_generator: DeterministicResponseGenerator,
        runtime_dispatcher: RuntimeDispatcher,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(
            response_generator,
            DeterministicResponseGenerator,
        ):
            raise TypeError(
                "response_generator must be a "
                "DeterministicResponseGenerator"
            )
        self._episode_coordinator = episode_coordinator
        self._response_generator = response_generator
        if not isinstance(runtime_dispatcher, RuntimeDispatcher):
            raise TypeError(
                "runtime_dispatcher must be a RuntimeDispatcher"
            )
        self._runtime_dispatcher = runtime_dispatcher

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        response_request_event = context.event
        if (
            response_request_event.event_type
            != "conversation.response_request"
        ):
            raise ValueError(
                "ConversationResponseGeneratedHandler requires "
                "conversation.response_request"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            response_request_event.tenant_id,
            response_request_event.event_id,
        )
        if episode is None:
            raise ValueError(
                "response-request Event is not contained in an Episode"
            )
        if not isinstance(response_request_event.payload, Mapping):
            raise ValueError(
                "response-request Event payload must be a mapping"
            )

        payload = response_request_event.payload
        required_fields = {
            "source_event_id",
            "accepted_event_id",
            "perceived_event_id",
            "normalized_event_id",
            "next_action_event_id",
            "response_type",
            "target_language",
            "intent",
            "requested_entities",
            "handoff_reason",
        }
        if not required_fields.issubset(payload):
            raise ValueError(
                "response-request Event payload is missing fields"
            )

        reference_fields = (
            "source_event_id",
            "accepted_event_id",
            "perceived_event_id",
            "normalized_event_id",
            "next_action_event_id",
        )
        reference_values = {
            field_name: payload[field_name]
            for field_name in reference_fields
        }
        reference_ids = {
            field_name: self._parse_uuid(value, field_name)
            for field_name, value in reference_values.items()
        }
        for field_name, event_id in reference_ids.items():
            if event_id not in episode.event_ids:
                event_name = field_name.removesuffix("_event_id")
                raise ValueError(
                    f"{event_name} Event is not in the "
                    "response-request Episode"
                )

        resolved_events = {
            event_name: self._get_event(
                response_request_event.tenant_id,
                reference_ids[field_name],
                event_name,
            )
            for event_name, field_name in (
                ("source", "source_event_id"),
                ("accepted", "accepted_event_id"),
                ("perceived", "perceived_event_id"),
                ("normalized", "normalized_event_id"),
                ("next-action", "next_action_event_id"),
            )
        }
        expected_types = {
            "source": "message.received",
            "accepted": "message.accepted",
            "perceived": "message.perceived",
            "normalized": "perception.normalized",
            "next-action": "conversation.next_action",
        }
        for event_name, expected_type in expected_types.items():
            if resolved_events[event_name].event_type != expected_type:
                raise ValueError(
                    f"{event_name} Event must be {expected_type}"
                )
        for event_name in (
            "accepted",
            "perceived",
            "normalized",
            "next-action",
        ):
            if not isinstance(
                resolved_events[event_name].payload,
                Mapping,
            ):
                raise ValueError(
                    f"{event_name} Event payload must be a mapping"
                )

        source_value = reference_values["source_event_id"]
        accepted_value = reference_values["accepted_event_id"]
        perceived_value = reference_values["perceived_event_id"]
        normalized_value = reference_values["normalized_event_id"]
        accepted_payload = resolved_events["accepted"].payload
        perceived_payload = resolved_events["perceived"].payload
        normalized_payload = resolved_events["normalized"].payload
        next_action_payload = resolved_events["next-action"].payload
        self._require_match(
            accepted_payload,
            "source_event_id",
            source_value,
            "accepted",
        )
        self._require_match(
            perceived_payload,
            "source_event_id",
            source_value,
            "perceived",
        )
        self._require_match(
            perceived_payload,
            "accepted_event_id",
            accepted_value,
            "perceived",
        )
        self._require_match(
            normalized_payload,
            "source_event_id",
            source_value,
            "normalized",
        )
        self._require_match(
            normalized_payload,
            "accepted_event_id",
            accepted_value,
            "normalized",
        )
        self._require_match(
            normalized_payload,
            "perceived_event_id",
            perceived_value,
            "normalized",
        )
        for field_name, expected_value in (
            ("source_event_id", source_value),
            ("accepted_event_id", accepted_value),
            ("perceived_event_id", perceived_value),
            ("normalized_event_id", normalized_value),
        ):
            self._require_match(
                next_action_payload,
                field_name,
                expected_value,
                "next-action",
            )

        normalized_required = {"language", "intent"}
        if not normalized_required.issubset(normalized_payload):
            raise ValueError("normalized Event payload is missing fields")
        next_action_required = {
            "action",
            "reason",
            "can_continue",
            "missing_entities",
        }
        if not next_action_required.issubset(next_action_payload):
            raise ValueError("next-action Event payload is missing fields")
        requested_entities = payload["requested_entities"]
        if not isinstance(requested_entities, (list, tuple)):
            raise ValueError("requested_entities must be a sequence")
        next_action = ConversationNextAction(
            action=next_action_payload["action"],
            reason=next_action_payload["reason"],
            can_continue=next_action_payload["can_continue"],
            missing_entities=next_action_payload["missing_entities"],
        )
        self._validate_semantic_correspondence(
            payload=payload,
            normalized_payload=normalized_payload,
            next_action=next_action,
            requested_entities=tuple(requested_entities),
        )

        generated = self._response_generator.generate(
            response_type=payload["response_type"],
            language=payload["target_language"],
            intent=payload["intent"],
            requested_entities=requested_entities,
            handoff_reason=payload["handoff_reason"],
        )
        generated_event = Event.create(
            tenant_id=response_request_event.tenant_id,
            event_type="conversation.response_generated",
            payload={
                "source_event_id": str(
                    reference_ids["source_event_id"]
                ),
                "accepted_event_id": str(
                    reference_ids["accepted_event_id"]
                ),
                "perceived_event_id": str(
                    reference_ids["perceived_event_id"]
                ),
                "normalized_event_id": str(
                    reference_ids["normalized_event_id"]
                ),
                "next_action_event_id": str(
                    reference_ids["next_action_event_id"]
                ),
                "response_request_event_id": str(
                    response_request_event.event_id
                ),
                "response_type": generated.response_type,
                "language": generated.language,
                "text": generated.text,
                "generation_method": generated.generation_method,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            generated_event,
        )
        self._runtime_dispatcher.dispatch(
            RuntimeContext.create(generated_event)
        )

    @staticmethod
    def _validate_semantic_correspondence(
        *,
        payload: Mapping[str, object],
        normalized_payload: Mapping[str, object],
        next_action: ConversationNextAction,
        requested_entities: tuple[object, ...],
    ) -> None:
        if payload["target_language"] != normalized_payload["language"]:
            raise ValueError(
                "target_language does not match normalized language"
            )
        if payload["intent"] != normalized_payload["intent"]:
            raise ValueError("intent does not match normalized intent")

        response_type = payload["response_type"]
        if response_type == "intent_response":
            valid = (
                next_action.action == "respond"
                and not requested_entities
                and payload["handoff_reason"] is None
            )
        elif response_type == "missing_information":
            valid = (
                next_action.action == "request_missing_information"
                and requested_entities == next_action.missing_entities
                and payload["handoff_reason"] is None
            )
        elif response_type == "clarification":
            valid = (
                next_action.action == "request_clarification"
                and not requested_entities
                and payload["handoff_reason"] is None
            )
        elif response_type == "human_handoff":
            valid = (
                next_action.action == "handoff_human"
                and not requested_entities
                and payload["handoff_reason"] == next_action.reason
            )
        else:
            raise ValueError("response_type must be canonical")
        if not valid:
            raise ValueError(
                "response request does not match next action"
            )

    @staticmethod
    def _require_match(
        payload: Mapping[str, object],
        field_name: str,
        expected_value: object,
        event_name: str,
    ) -> None:
        if payload.get(field_name) != expected_value:
            raise ValueError(
                f"{event_name} Event {field_name} does not match"
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
