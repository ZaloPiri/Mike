from dataclasses import FrozenInstanceError

import pytest

from mike_app.communication.target_resolution import (
    CommunicationContext,
    ConversationResponseTargetResolver,
    ResolvedConversationResponseTarget,
)


def make_context(**changes: object) -> CommunicationContext:
    values = {
        "channel": " custom-channel ",
        "external_message_id": " message-id ",
        "external_conversation_id": " conversation-id ",
        "sender_id": " sender-id ",
        "recipient_id": " recipient-id ",
    }
    values.update(changes)
    return CommunicationContext(**values)


def test_communication_context_is_valid_immutable_and_slotted() -> None:
    context = make_context()

    assert context.channel == " custom-channel "
    assert context.external_message_id == " message-id "
    assert context.external_conversation_id == " conversation-id "
    assert context.sender_id == " sender-id "
    assert context.recipient_id == " recipient-id "
    assert not hasattr(context, "__dict__")
    with pytest.raises(FrozenInstanceError):
        context.channel = "changed"


@pytest.mark.parametrize(
    "field_name",
    [
        "channel",
        "external_message_id",
        "external_conversation_id",
        "sender_id",
        "recipient_id",
    ],
)
@pytest.mark.parametrize("value", [None, 1, [], {}])
def test_communication_context_rejects_non_strings(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(TypeError, match=field_name):
        make_context(**{field_name: value})


@pytest.mark.parametrize(
    "field_name",
    [
        "channel",
        "external_message_id",
        "external_conversation_id",
        "sender_id",
        "recipient_id",
    ],
)
@pytest.mark.parametrize("value", ["", "   "])
def test_communication_context_rejects_empty_strings(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_context(**{field_name: value})


@pytest.mark.parametrize(
    "channel",
    ["development", "whatsapp-like", "future/provider:value"],
)
def test_context_has_no_provider_specific_channel_restriction(
    channel: str,
) -> None:
    assert make_context(channel=channel).channel == channel


def test_resolver_reverses_direction_and_preserves_opaque_values() -> None:
    context = make_context()

    result = ConversationResponseTargetResolver().resolve(context)

    assert result == ResolvedConversationResponseTarget(
        channel=" custom-channel ",
        external_message_id=" message-id ",
        external_conversation_id=" conversation-id ",
        outbound_sender_id=" recipient-id ",
        outbound_recipient_id=" sender-id ",
        resolution_method="reply_to_source",
    )
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.outbound_sender_id = "changed"


def test_resolver_is_deterministic() -> None:
    resolver = ConversationResponseTargetResolver()
    context = make_context()

    assert resolver.resolve(context) == resolver.resolve(context)


@pytest.mark.parametrize("context", [None, object(), {}])
def test_resolver_rejects_invalid_context(context: object) -> None:
    with pytest.raises(TypeError, match="CommunicationContext"):
        ConversationResponseTargetResolver().resolve(context)


def test_resolver_has_no_infrastructure_state() -> None:
    resolver = ConversationResponseTargetResolver()

    assert vars(resolver) == {}
