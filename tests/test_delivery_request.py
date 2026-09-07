from dataclasses import FrozenInstanceError, replace
import uuid

import pytest

from mike_app.communication.delivery_request import (
    REQUEST_METHOD,
    ConversationDeliveryRequestPlanner,
    DeliveryRequest,
)


def test_delivery_request_is_validated_and_immutable() -> None:
    request = DeliveryRequest(
        channel="development",
        external_conversation_id=" conversation ",
        outbound_sender_id="sender",
        outbound_recipient_id="recipient",
        response_type="answer",
        language="es",
        text="  ¡Hola, Ñandú!  ",
        idempotency_key=str(uuid.uuid4()),
        request_method=REQUEST_METHOD,
    )

    assert request.text == "  ¡Hola, Ñandú!  "
    assert request.external_conversation_id == " conversation "
    with pytest.raises(FrozenInstanceError):
        request.text = "changed"


@pytest.mark.parametrize("field_name", DeliveryRequest.__dataclass_fields__)
def test_delivery_request_rejects_non_string_fields(field_name: str) -> None:
    values = {
        "channel": "channel",
        "external_conversation_id": "conversation",
        "outbound_sender_id": "sender",
        "outbound_recipient_id": "recipient",
        "response_type": "answer",
        "language": "es",
        "text": "text",
        "idempotency_key": str(uuid.uuid4()),
        "request_method": REQUEST_METHOD,
    }
    values[field_name] = object()
    with pytest.raises(TypeError, match=field_name):
        DeliveryRequest(**values)


@pytest.mark.parametrize("empty", ["", " ", "\t", "\n"])
def test_delivery_request_rejects_empty_strings(empty: str) -> None:
    request = DeliveryRequest(
        channel="channel",
        external_conversation_id="conversation",
        outbound_sender_id="sender",
        outbound_recipient_id="recipient",
        response_type="answer",
        language="es",
        text="text",
        idempotency_key=str(uuid.uuid4()),
        request_method=REQUEST_METHOD,
    )
    with pytest.raises(ValueError, match="text"):
        replace(request, text=empty)


def test_planner_copies_exact_values_and_derives_fixed_fields() -> None:
    event_id = uuid.uuid4()
    planner = ConversationDeliveryRequestPlanner()

    result = planner.plan(
        response_ready_event_id=event_id,
        channel=" channel ",
        external_conversation_id=" conversation ",
        outbound_sender_id=" sender ",
        outbound_recipient_id=" recipient ",
        response_type=" answer ",
        language=" es ",
        text="  respuesta\nUnicode: áéíóú  ",
    )

    assert result == DeliveryRequest(
        channel=" channel ",
        external_conversation_id=" conversation ",
        outbound_sender_id=" sender ",
        outbound_recipient_id=" recipient ",
        response_type=" answer ",
        language=" es ",
        text="  respuesta\nUnicode: áéíóú  ",
        idempotency_key=str(event_id),
        request_method="transactional_outbox",
    )


def test_planner_rejects_invalid_response_ready_event_id() -> None:
    with pytest.raises(TypeError, match="response_ready_event_id"):
        ConversationDeliveryRequestPlanner().plan(
            response_ready_event_id="not-a-uuid",
            channel="channel",
            external_conversation_id="conversation",
            outbound_sender_id="sender",
            outbound_recipient_id="recipient",
            response_type="answer",
            language="es",
            text="text",
        )
