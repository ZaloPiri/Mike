from __future__ import annotations

from dataclasses import dataclass


RESOLUTION_METHOD = "reply_to_source"


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class CommunicationContext:
    channel: str
    external_message_id: str
    external_conversation_id: str
    sender_id: str
    recipient_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "channel",
            "external_message_id",
            "external_conversation_id",
            "sender_id",
            "recipient_id",
        ):
            _validate_non_empty_string(
                getattr(self, field_name),
                field_name,
            )


@dataclass(frozen=True, slots=True)
class ResolvedConversationResponseTarget:
    channel: str
    external_message_id: str
    external_conversation_id: str
    outbound_sender_id: str
    outbound_recipient_id: str
    resolution_method: str

    def __post_init__(self) -> None:
        for field_name in (
            "channel",
            "external_message_id",
            "external_conversation_id",
            "outbound_sender_id",
            "outbound_recipient_id",
        ):
            _validate_non_empty_string(
                getattr(self, field_name),
                field_name,
            )
        if self.resolution_method != RESOLUTION_METHOD:
            raise ValueError(
                "resolution_method must be reply_to_source"
            )


class ConversationResponseTargetResolver:
    def resolve(
        self,
        context: CommunicationContext,
    ) -> ResolvedConversationResponseTarget:
        if not isinstance(context, CommunicationContext):
            raise TypeError(
                "context must be a CommunicationContext"
            )
        return ResolvedConversationResponseTarget(
            channel=context.channel,
            external_message_id=context.external_message_id,
            external_conversation_id=context.external_conversation_id,
            outbound_sender_id=context.recipient_id,
            outbound_recipient_id=context.sender_id,
            resolution_method=RESOLUTION_METHOD,
        )
