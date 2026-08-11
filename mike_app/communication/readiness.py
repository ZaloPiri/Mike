from __future__ import annotations

from dataclasses import dataclass


READINESS_METHOD = "validated_response_with_resolved_target"


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class ReadyConversationResponse:
    response_type: str
    language: str
    text: str
    channel: str
    external_message_id: str
    external_conversation_id: str
    outbound_sender_id: str
    outbound_recipient_id: str
    readiness_method: str

    def __post_init__(self) -> None:
        for field_name in (
            "response_type",
            "language",
            "text",
            "channel",
            "external_message_id",
            "external_conversation_id",
            "outbound_sender_id",
            "outbound_recipient_id",
            "readiness_method",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        if self.readiness_method != READINESS_METHOD:
            raise ValueError(
                "readiness_method must be "
                "validated_response_with_resolved_target"
            )


class ConversationResponseReadinessEvaluator:
    def evaluate(
        self,
        *,
        response_type: object,
        language: object,
        text: object,
        channel: object,
        external_message_id: object,
        external_conversation_id: object,
        outbound_sender_id: object,
        outbound_recipient_id: object,
    ) -> ReadyConversationResponse:
        return ReadyConversationResponse(
            response_type=response_type,
            language=language,
            text=text,
            channel=channel,
            external_message_id=external_message_id,
            external_conversation_id=external_conversation_id,
            outbound_sender_id=outbound_sender_id,
            outbound_recipient_id=outbound_recipient_id,
            readiness_method=READINESS_METHOD,
        )
