from __future__ import annotations

from collections.abc import Mapping

from mike_app.communication.target_resolution import (
    CommunicationContext,
    ConversationResponseTargetResolver,
)
from mike_app.conversation.response_validation import (
    ValidatedConversationResponse,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class ConversationResponseTargetResolvedHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        response_target_resolver: ConversationResponseTargetResolver,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(
            response_target_resolver,
            ConversationResponseTargetResolver,
        ):
            raise TypeError(
                "response_target_resolver must be a "
                "ConversationResponseTargetResolver"
            )
        self._episode_coordinator = episode_coordinator
        self._response_target_resolver = response_target_resolver

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        response_validated_event = context.event
        if (
            response_validated_event.event_type
            != "conversation.response_validated"
        ):
            raise ValueError(
                "ConversationResponseTargetResolvedHandler requires "
                "conversation.response_validated"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            response_validated_event.tenant_id,
            response_validated_event.event_id,
        )
        if episode is None:
            raise ValueError(
                "response-validated Event is not contained in an Episode"
            )
        if len(episode.event_ids) != 8:
            raise ValueError(
                "Episode must contain exactly the eight preceding Events"
            )

        events = tuple(
            self._get_event(
                response_validated_event.tenant_id,
                event_id,
            )
            for event_id in episode.event_ids
        )
        if events[-1] is not response_validated_event:
            raise ValueError(
                "response-validated Event must be eighth in the Episode"
            )
        expected_types = (
            "message.received",
            "message.accepted",
            "message.perceived",
            "perception.normalized",
            "conversation.next_action",
            "conversation.response_request",
            "conversation.response_generated",
            "conversation.response_validated",
        )
        for event, expected_type in zip(
            events,
            expected_types,
            strict=True,
        ):
            if event.tenant_id != episode.tenant_id:
                raise ValueError(
                    "Event tenant does not match Episode tenant"
                )
            if event.event_type != expected_type:
                raise ValueError(f"Event must be {expected_type}")

        payloads = tuple(self._require_mapping(event) for event in events)
        expected_references = {
            "source_event_id": str(events[0].event_id),
            "accepted_event_id": str(events[1].event_id),
            "perceived_event_id": str(events[2].event_id),
            "normalized_event_id": str(events[3].event_id),
            "next_action_event_id": str(events[4].event_id),
            "response_request_event_id": str(events[5].event_id),
            "response_generated_event_id": str(events[6].event_id),
        }
        reference_fields = (
            (),
            ("source_event_id",),
            ("source_event_id", "accepted_event_id"),
            (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
            ),
            (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
                "normalized_event_id",
            ),
            (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
                "normalized_event_id",
                "next_action_event_id",
            ),
            (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
                "normalized_event_id",
                "next_action_event_id",
                "response_request_event_id",
            ),
            tuple(expected_references),
        )
        for payload, field_names in zip(
            payloads,
            reference_fields,
            strict=True,
        ):
            for field_name in field_names:
                if payload.get(field_name) != expected_references[field_name]:
                    raise ValueError(f"{field_name} does not match")

        request_payload = payloads[5]
        generated_payload = payloads[6]
        validated_payload = payloads[7]
        self._validate_response_chain(
            request_payload,
            generated_payload,
            validated_payload,
        )
        source_payload = payloads[0]
        communication_context = CommunicationContext(
            channel=self._required_value(source_payload, "channel"),
            external_message_id=self._required_value(
                source_payload,
                "external_message_id",
            ),
            external_conversation_id=self._required_value(
                source_payload,
                "external_conversation_id",
            ),
            sender_id=self._required_value(source_payload, "sender_id"),
            recipient_id=self._required_value(
                source_payload,
                "recipient_id",
            ),
        )
        resolved = self._response_target_resolver.resolve(
            communication_context
        )
        target_resolved_event = Event.create(
            tenant_id=response_validated_event.tenant_id,
            event_type="communication.response_target_resolved",
            payload={
                "source_event_id": str(events[0].event_id),
                "response_validated_event_id": str(
                    response_validated_event.event_id
                ),
                "channel": resolved.channel,
                "external_message_id": resolved.external_message_id,
                "external_conversation_id": (
                    resolved.external_conversation_id
                ),
                "outbound_sender_id": resolved.outbound_sender_id,
                "outbound_recipient_id": resolved.outbound_recipient_id,
                "resolution_method": resolved.resolution_method,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            target_resolved_event,
        )

    @staticmethod
    def _validate_response_chain(
        request_payload: Mapping[str, object],
        generated_payload: Mapping[str, object],
        validated_payload: Mapping[str, object],
    ) -> None:
        request_fields = {"response_type", "target_language"}
        generated_fields = {
            "response_type",
            "language",
            "text",
            "generation_method",
        }
        validated_fields = generated_fields | {"validation_method"}
        if not request_fields.issubset(request_payload):
            raise ValueError(
                "response-request Event payload is missing fields"
            )
        if not generated_fields.issubset(generated_payload):
            raise ValueError(
                "response-generated Event payload is missing fields"
            )
        if not validated_fields.issubset(validated_payload):
            raise ValueError(
                "response-validated Event payload is missing fields"
            )
        if (
            generated_payload["response_type"]
            != request_payload["response_type"]
        ):
            raise ValueError("response_type does not match response request")
        if (
            generated_payload["language"]
            != request_payload["target_language"]
        ):
            raise ValueError("language does not match target_language")
        for field_name in generated_fields:
            if (
                validated_payload[field_name]
                != generated_payload[field_name]
            ):
                raise ValueError(
                    f"validated {field_name} does not match generated"
                )
        ValidatedConversationResponse(
            response_type=validated_payload["response_type"],
            language=validated_payload["language"],
            text=validated_payload["text"],
            generation_method=validated_payload["generation_method"],
            validation_method=validated_payload["validation_method"],
        )

    def _get_event(self, tenant_id: str, event_id: object) -> Event:
        event = self._episode_coordinator.get_event(tenant_id, event_id)
        if event is None:
            raise ValueError("Episode Event not found for tenant")
        return event

    @staticmethod
    def _require_mapping(event: Event) -> Mapping[str, object]:
        if not isinstance(event.payload, Mapping):
            raise ValueError("Event payload must be a mapping")
        return event.payload

    @staticmethod
    def _required_value(
        payload: Mapping[str, object],
        field_name: str,
    ) -> object:
        if field_name not in payload:
            raise ValueError(
                "message.received communication context is missing fields"
            )
        return payload[field_name]
