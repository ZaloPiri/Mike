from __future__ import annotations

from collections.abc import Mapping

from mike_app.communication.readiness import (
    ConversationResponseReadinessEvaluator,
)
from mike_app.communication.target_resolution import (
    CommunicationContext,
    ResolvedConversationResponseTarget,
)
from mike_app.conversation.response_validation import (
    ValidatedConversationResponse,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class ConversationResponseReadyHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        readiness_evaluator: ConversationResponseReadinessEvaluator,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        if not isinstance(
            readiness_evaluator,
            ConversationResponseReadinessEvaluator,
        ):
            raise TypeError(
                "readiness_evaluator must be a "
                "ConversationResponseReadinessEvaluator"
            )
        self._episode_coordinator = episode_coordinator
        self._readiness_evaluator = readiness_evaluator

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        target_event = context.event
        if target_event.event_type != "communication.response_target_resolved":
            raise ValueError(
                "ConversationResponseReadyHandler requires "
                "communication.response_target_resolved"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            target_event.tenant_id,
            target_event.event_id,
        )
        if episode is None:
            raise ValueError(
                "response-target-resolved Event is not contained in an Episode"
            )
        if len(episode.event_ids) != 9:
            raise ValueError(
                "Episode must contain exactly the nine preceding Events"
            )

        events = tuple(
            self._get_event(target_event.tenant_id, event_id)
            for event_id in episode.event_ids
        )
        if events[-1].event_id != target_event.event_id:
            raise ValueError(
                "response-target-resolved Event must be ninth in the Episode"
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
            "communication.response_target_resolved",
        )
        for event, expected_type in zip(events, expected_types, strict=True):
            if event.tenant_id != episode.tenant_id:
                raise ValueError("Event tenant does not match Episode tenant")
            if event.event_type != expected_type:
                raise ValueError(f"Event must be {expected_type}")

        payloads = tuple(self._require_mapping(event) for event in events)
        self._validate_references(events, payloads)
        validated_payload = payloads[7]
        target_payload = payloads[8]
        self._validate_validated_response(payloads)
        self._validate_resolved_target(payloads[0], target_payload)

        ready = self._readiness_evaluator.evaluate(
            response_type=self._required_value(
                validated_payload, "response_type"
            ),
            language=self._required_value(validated_payload, "language"),
            text=self._required_value(validated_payload, "text"),
            channel=self._required_value(target_payload, "channel"),
            external_message_id=self._required_value(
                target_payload, "external_message_id"
            ),
            external_conversation_id=self._required_value(
                target_payload, "external_conversation_id"
            ),
            outbound_sender_id=self._required_value(
                target_payload, "outbound_sender_id"
            ),
            outbound_recipient_id=self._required_value(
                target_payload, "outbound_recipient_id"
            ),
        )
        expected_snapshot = (
            self._required_value(validated_payload, "response_type"),
            self._required_value(validated_payload, "language"),
            self._required_value(validated_payload, "text"),
            self._required_value(target_payload, "channel"),
            self._required_value(target_payload, "external_message_id"),
            self._required_value(
                target_payload, "external_conversation_id"
            ),
            self._required_value(target_payload, "outbound_sender_id"),
            self._required_value(target_payload, "outbound_recipient_id"),
        )
        actual_snapshot = (
            ready.response_type,
            ready.language,
            ready.text,
            ready.channel,
            ready.external_message_id,
            ready.external_conversation_id,
            ready.outbound_sender_id,
            ready.outbound_recipient_id,
        )
        if actual_snapshot != expected_snapshot:
            raise ValueError(
                "ready snapshot does not match authoritative Events"
            )
        ready_event = Event.create(
            tenant_id=target_event.tenant_id,
            event_type="conversation.response_ready",
            payload={
                "source_event_id": str(events[0].event_id),
                "response_validated_event_id": str(events[7].event_id),
                "response_target_resolved_event_id": str(target_event.event_id),
                "response_type": ready.response_type,
                "language": ready.language,
                "text": ready.text,
                "channel": ready.channel,
                "external_message_id": ready.external_message_id,
                "external_conversation_id": ready.external_conversation_id,
                "outbound_sender_id": ready.outbound_sender_id,
                "outbound_recipient_id": ready.outbound_recipient_id,
                "readiness_method": ready.readiness_method,
            },
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            ready_event,
        )

    @staticmethod
    def _validate_references(
        events: tuple[Event, ...],
        payloads: tuple[Mapping[str, object], ...],
    ) -> None:
        expected = {
            "source_event_id": str(events[0].event_id),
            "accepted_event_id": str(events[1].event_id),
            "perceived_event_id": str(events[2].event_id),
            "normalized_event_id": str(events[3].event_id),
            "next_action_event_id": str(events[4].event_id),
            "response_request_event_id": str(events[5].event_id),
            "response_generated_event_id": str(events[6].event_id),
            "response_validated_event_id": str(events[7].event_id),
        }
        fields = (
            (),
            ("source_event_id",),
            ("source_event_id", "accepted_event_id"),
            ("source_event_id", "accepted_event_id", "perceived_event_id"),
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
            tuple(key for key in expected if key != "response_validated_event_id"),
            ("source_event_id", "response_validated_event_id"),
        )
        for payload, field_names in zip(payloads, fields, strict=True):
            for field_name in field_names:
                if payload.get(field_name) != expected[field_name]:
                    raise ValueError(f"{field_name} does not match")

    @staticmethod
    def _validate_validated_response(
        payloads: tuple[Mapping[str, object], ...],
    ) -> None:
        request = payloads[5]
        generated = payloads[6]
        validated = payloads[7]
        required_request = {"response_type", "target_language"}
        required_generated = {
            "response_type", "language", "text", "generation_method"
        }
        required_validated = required_generated | {"validation_method"}
        if not required_request.issubset(request):
            raise ValueError("response-request Event payload is missing fields")
        if not required_generated.issubset(generated):
            raise ValueError("response-generated Event payload is missing fields")
        if not required_validated.issubset(validated):
            raise ValueError("response-validated Event payload is missing fields")
        if generated["response_type"] != request["response_type"]:
            raise ValueError("response_type does not match response request")
        if generated["language"] != request["target_language"]:
            raise ValueError("language does not match target_language")
        for field_name in required_generated:
            if validated[field_name] != generated[field_name]:
                raise ValueError(
                    f"validated {field_name} does not match generated"
                )
        ValidatedConversationResponse(
            response_type=validated["response_type"],
            language=validated["language"],
            text=validated["text"],
            generation_method=validated["generation_method"],
            validation_method=validated["validation_method"],
        )

    @staticmethod
    def _validate_resolved_target(
        source: Mapping[str, object],
        target: Mapping[str, object],
    ) -> None:
        context = CommunicationContext(
            channel=ConversationResponseReadyHandler._required_value(
                source, "channel"
            ),
            external_message_id=ConversationResponseReadyHandler._required_value(
                source, "external_message_id"
            ),
            external_conversation_id=(
                ConversationResponseReadyHandler._required_value(
                    source, "external_conversation_id"
                )
            ),
            sender_id=ConversationResponseReadyHandler._required_value(
                source, "sender_id"
            ),
            recipient_id=ConversationResponseReadyHandler._required_value(
                source, "recipient_id"
            ),
        )
        resolved = ResolvedConversationResponseTarget(
            channel=ConversationResponseReadyHandler._required_value(
                target, "channel"
            ),
            external_message_id=ConversationResponseReadyHandler._required_value(
                target, "external_message_id"
            ),
            external_conversation_id=(
                ConversationResponseReadyHandler._required_value(
                    target, "external_conversation_id"
                )
            ),
            outbound_sender_id=ConversationResponseReadyHandler._required_value(
                target, "outbound_sender_id"
            ),
            outbound_recipient_id=(
                ConversationResponseReadyHandler._required_value(
                    target, "outbound_recipient_id"
                )
            ),
            resolution_method=ConversationResponseReadyHandler._required_value(
                target, "resolution_method"
            ),
        )
        expected = (
            context.channel,
            context.external_message_id,
            context.external_conversation_id,
            context.recipient_id,
            context.sender_id,
        )
        actual = (
            resolved.channel,
            resolved.external_message_id,
            resolved.external_conversation_id,
            resolved.outbound_sender_id,
            resolved.outbound_recipient_id,
        )
        if actual != expected:
            raise ValueError("resolved target does not match source context")

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
        payload: Mapping[str, object], field_name: str
    ) -> object:
        if field_name not in payload:
            raise ValueError(f"Event payload is missing {field_name}")
        return payload[field_name]
