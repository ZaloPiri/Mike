from __future__ import annotations

import uuid
from dataclasses import dataclass


REQUEST_METHOD = "transactional_outbox"


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    channel: str
    external_conversation_id: str
    outbound_sender_id: str
    outbound_recipient_id: str
    response_type: str
    language: str
    text: str
    idempotency_key: str
    request_method: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _validate_non_empty_string(getattr(self, field_name), field_name)
        if self.request_method != REQUEST_METHOD:
            raise ValueError("request_method must be transactional_outbox")


class ConversationDeliveryRequestPlanner:
    def plan(
        self,
        *,
        response_ready_event_id: uuid.UUID,
        channel: object,
        external_conversation_id: object,
        outbound_sender_id: object,
        outbound_recipient_id: object,
        response_type: object,
        language: object,
        text: object,
    ) -> DeliveryRequest:
        if not isinstance(response_ready_event_id, uuid.UUID):
            raise TypeError("response_ready_event_id must be a uuid.UUID")
        return DeliveryRequest(
            channel=channel,
            external_conversation_id=external_conversation_id,
            outbound_sender_id=outbound_sender_id,
            outbound_recipient_id=outbound_recipient_id,
            response_type=response_type,
            language=language,
            text=text,
            idempotency_key=str(response_ready_event_id),
            request_method=REQUEST_METHOD,
        )
