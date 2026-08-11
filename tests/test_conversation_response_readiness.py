from dataclasses import FrozenInstanceError

import pytest

from mike_app.communication.readiness import (
    ConversationResponseReadinessEvaluator,
    ReadyConversationResponse,
)


def values(**changes: object) -> dict[str, object]:
    result = {
        "response_type": " intent_response ",
        "language": " es ",
        "text": "  Línea uno\nLínea dos  ",
        "channel": " future/provider:value ",
        "external_message_id": " message-id ",
        "external_conversation_id": " conversation-id ",
        "outbound_sender_id": " sender-id ",
        "outbound_recipient_id": " recipient-id ",
    }
    result.update(changes)
    return result


def test_ready_model_is_valid_frozen_slotted_and_exact() -> None:
    ready = ConversationResponseReadinessEvaluator().evaluate(**values())

    assert ready == ReadyConversationResponse(
        **values(),
        readiness_method="validated_response_with_resolved_target",
    )
    assert not hasattr(ready, "__dict__")
    with pytest.raises(FrozenInstanceError):
        ready.text = "changed"


@pytest.mark.parametrize("value", [None, 1, "", "   "])
def test_ready_model_rejects_invalid_readiness_method(value: object) -> None:
    with pytest.raises((TypeError, ValueError), match="readiness_method"):
        ReadyConversationResponse(**values(), readiness_method=value)


def test_ready_model_rejects_wrong_readiness_method() -> None:
    with pytest.raises(ValueError, match="readiness_method"):
        ReadyConversationResponse(
            **values(),
            readiness_method="different_method",
        )


@pytest.mark.parametrize(
    "field_name",
    list(values()),
)
@pytest.mark.parametrize("value", [None, 1, [], {}])
def test_evaluator_rejects_non_string_fields(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(TypeError, match=field_name):
        ConversationResponseReadinessEvaluator().evaluate(
            **values(**{field_name: value})
        )


@pytest.mark.parametrize("field_name", list(values()))
@pytest.mark.parametrize("value", ["", "   "])
def test_evaluator_rejects_empty_fields(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        ConversationResponseReadinessEvaluator().evaluate(
            **values(**{field_name: value})
        )


def test_evaluator_copies_every_value_without_transforming_direction() -> None:
    inputs = values()

    ready = ConversationResponseReadinessEvaluator().evaluate(**inputs)

    for field_name, value in inputs.items():
        assert getattr(ready, field_name) == value
    assert ready.outbound_sender_id == inputs["outbound_sender_id"]
    assert ready.outbound_recipient_id == inputs["outbound_recipient_id"]


@pytest.mark.parametrize(
    "channel",
    ["development", "whatsapp-like", "future/provider:value"],
)
def test_evaluator_has_no_provider_channel_rules(channel: str) -> None:
    assert (
        ConversationResponseReadinessEvaluator()
        .evaluate(**values(channel=channel))
        .channel
        == channel
    )


def test_evaluator_is_deterministic_and_stateless() -> None:
    evaluator = ConversationResponseReadinessEvaluator()

    assert evaluator.evaluate(**values()) == evaluator.evaluate(**values())
    assert vars(evaluator) == {}
