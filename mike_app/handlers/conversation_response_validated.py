from __future__ import annotations

import uuid
from collections.abc import Mapping

from mike_app.conversation.response_validation import (
    ConversationResponseValidator,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class ConversationResponseValidatedHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        response_validator: ConversationResponseValidator,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(
            response_validator,
            ConversationResponseValidator,
        ):
            raise TypeError(
                "response_validator must be a "
                "ConversationResponseValidator"
            )
        self._episode_coordinator = episode_coordinator
        self._response_validator = response_validator

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        generated_event = context.event
        if generated_event.event_type != "conversation.response_generated":
            raise ValueError(
                "ConversationResponseValidatedHandler requires "
                "conversation.response_generated"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            generated_event.tenant_id,
            generated_event.event_id,
        )
        if episode is None:
            raise ValueError(
                "response-generated Event is not contained in an Episode"
            )
        if not isinstance(generated_event.payload, Mapping):
            raise ValueError(
                "response-generated Event payload must be a mapping"
            )

        reference_fields = (
            "source_event_id",
            "accepted_event_id",
            "perceived_event_id",
            "normalized_event_id",
            "next_action_event_id",
            "response_request_event_id",
        )
        if not set(reference_fields).issubset(generated_event.payload):
            raise ValueError(
                "response-generated Event payload is missing fields"
            )
        reference_ids = {
            field_name: self._parse_uuid(
                generated_event.payload[field_name],
                field_name,
            )
            for field_name in reference_fields
        }
        for field_name, event_id in reference_ids.items():
            if event_id not in episode.event_ids:
                event_name = field_name.removesuffix("_event_id")
                raise ValueError(
                    f"{event_name} Event is not in the "
                    "response-generated Episode"
                )

        resolved_events = {
            field_name: self._get_event(
                generated_event.tenant_id,
                event_id,
                field_name.removesuffix("_event_id"),
            )
            for field_name, event_id in reference_ids.items()
        }
        validated = self._response_validator.validate(
            episode=episode,
            source_event=resolved_events["source_event_id"],
            accepted_event=resolved_events["accepted_event_id"],
            perceived_event=resolved_events["perceived_event_id"],
            normalized_event=resolved_events["normalized_event_id"],
            next_action_event=resolved_events["next_action_event_id"],
            response_request_event=resolved_events[
                "response_request_event_id"
            ],
            response_generated_event=generated_event,
        )
        validated_event = Event.create(
            tenant_id=generated_event.tenant_id,
            event_type="conversation.response_validated",
            payload={
                **{
                    field_name: str(event_id)
                    for field_name, event_id in reference_ids.items()
                },
                "response_generated_event_id": str(
                    generated_event.event_id
                ),
                "response_type": validated.response_type,
                "language": validated.language,
                "text": validated.text,
                "generation_method": validated.generation_method,
                "validation_method": validated.validation_method,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            validated_event,
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
