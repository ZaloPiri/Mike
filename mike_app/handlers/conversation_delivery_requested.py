from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from mike_app.communication.delivery_request import (
    ConversationDeliveryRequestPlanner,
)
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_journal import _validate_response_ready_contract
from mike_app.runtime.event import Event


class ConversationDeliveryRequestedHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        planner: ConversationDeliveryRequestPlanner,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError("episode_coordinator must be an EpisodeCoordinator")
        if not isinstance(planner, ConversationDeliveryRequestPlanner):
            raise TypeError(
                "planner must be a ConversationDeliveryRequestPlanner"
            )
        self._episode_coordinator = episode_coordinator
        self._planner = planner

    def __call__(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")
        ready_event = context.event
        if ready_event.event_type != "conversation.response_ready":
            raise ValueError(
                "ConversationDeliveryRequestedHandler requires "
                "conversation.response_ready"
            )
        episode = self._episode_coordinator.find_episode_for_event(
            ready_event.tenant_id, ready_event.event_id
        )
        if episode is None:
            raise ValueError("response-ready Event is not contained in an Episode")
        if len(episode.event_ids) != 10:
            raise ValueError("Episode must contain exactly ten preceding Events")
        events = tuple(
            self._get_event(ready_event.tenant_id, event_id)
            for event_id in episode.event_ids
        )
        if events[-1].event_id != ready_event.event_id:
            raise ValueError("response-ready Event must be tenth in the Episode")
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
            "conversation.response_ready",
        )
        for event, expected_type in zip(events, expected_types, strict=True):
            if event.tenant_id != episode.tenant_id:
                raise ValueError("Event tenant does not match Episode tenant")
            if event.event_type != expected_type:
                raise ValueError(f"Event must be {expected_type}")
            if event.schema_version != 1:
                raise ValueError("Event schema_version does not match")
            if event.correlation_id is not None:
                raise ValueError("Event correlation_id does not match")
            if event.causation_id is not None:
                raise ValueError("Event causation_id does not match")
        payloads = tuple(self._require_mapping(event) for event in events)
        self._validate_references(events, payloads)
        _validate_response_ready_contract(payloads)
        ready_payload = payloads[9]
        request = self._planner.plan(
            response_ready_event_id=ready_event.event_id,
            channel=self._required_value(ready_payload, "channel"),
            external_conversation_id=self._required_value(
                ready_payload, "external_conversation_id"
            ),
            outbound_sender_id=self._required_value(
                ready_payload, "outbound_sender_id"
            ),
            outbound_recipient_id=self._required_value(
                ready_payload, "outbound_recipient_id"
            ),
            response_type=self._required_value(
                ready_payload, "response_type"
            ),
            language=self._required_value(ready_payload, "language"),
            text=self._required_value(ready_payload, "text"),
        )
        delivery_event = Event.create(
            tenant_id=ready_event.tenant_id,
            event_type="communication.delivery_requested",
            payload={
                "source_event_id": str(events[0].event_id),
                "response_ready_event_id": str(ready_event.event_id),
                "channel": request.channel,
                "external_conversation_id": request.external_conversation_id,
                "outbound_sender_id": request.outbound_sender_id,
                "outbound_recipient_id": request.outbound_recipient_id,
                "idempotency_key": request.idempotency_key,
                "request_method": request.request_method,
            },
            correlation_id=ready_event.correlation_id,
            causation_id=str(ready_event.event_id),
        )
        outbox_entry = DeliveryOutboxEntry(
            outbox_id=uuid.uuid4(),
            tenant_id=ready_event.tenant_id,
            episode_id=episode.episode_id,
            delivery_request_event_id=delivery_event.event_id,
            response_ready_event_id=ready_event.event_id,
            idempotency_key=request.idempotency_key,
            channel=request.channel,
            external_conversation_id=request.external_conversation_id,
            outbound_sender_id=request.outbound_sender_id,
            outbound_recipient_id=request.outbound_recipient_id,
            response_type=request.response_type,
            language=request.language,
            text=request.text,
            status="pending",
            created_at=datetime.now(timezone.utc),
            schema_version=1,
        )
        self._episode_coordinator.append_to_episode_with_outbox(
            episode.episode_id,
            delivery_event,
            episode.event_ids,
            outbox_entry,
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
            "response_target_resolved_event_id": str(events[8].event_id),
        }
        fields = (
            (),
            ("source_event_id",),
            ("source_event_id", "accepted_event_id"),
            ("source_event_id", "accepted_event_id", "perceived_event_id"),
            (
                "source_event_id", "accepted_event_id", "perceived_event_id",
                "normalized_event_id",
            ),
            (
                "source_event_id", "accepted_event_id", "perceived_event_id",
                "normalized_event_id", "next_action_event_id",
            ),
            (
                "source_event_id", "accepted_event_id", "perceived_event_id",
                "normalized_event_id", "next_action_event_id",
                "response_request_event_id",
            ),
            (
                "source_event_id", "accepted_event_id", "perceived_event_id",
                "normalized_event_id", "next_action_event_id",
                "response_request_event_id", "response_generated_event_id",
            ),
            ("source_event_id", "response_validated_event_id"),
            (
                "source_event_id", "response_validated_event_id",
                "response_target_resolved_event_id",
            ),
        )
        for payload, field_names in zip(payloads, fields, strict=True):
            for field_name in field_names:
                if payload.get(field_name) != expected[field_name]:
                    raise ValueError(f"{field_name} does not match")

    def _get_event(self, tenant_id: str, event_id: uuid.UUID) -> Event:
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
