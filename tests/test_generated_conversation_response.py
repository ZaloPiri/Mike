from dataclasses import FrozenInstanceError

import pytest

from mike_app.conversation.response_generation import (
    GeneratedConversationResponse,
)


@pytest.mark.parametrize(
    "response_type",
    [
        "intent_response",
        "missing_information",
        "clarification",
        "human_handoff",
    ],
)
def test_valid_construction_for_every_response_type(
    response_type: str,
) -> None:
    result = GeneratedConversationResponse(
        response_type=response_type,
        language="es",
        text="Texto",
        generation_method="deterministic_template",
    )

    assert result.response_type == response_type


def test_model_is_frozen_and_slotted() -> None:
    result = GeneratedConversationResponse(
        "intent_response",
        "es",
        "Texto",
        "deterministic_template",
    )

    with pytest.raises(FrozenInstanceError):
        result.text = "Otro"
    with pytest.raises((AttributeError, TypeError)):
        result.extra = "value"


@pytest.mark.parametrize(
    ("field", "value", "exception"),
    [
        ("response_type", "unsupported", ValueError),
        ("language", "", ValueError),
        ("language", " ", ValueError),
        ("language", None, TypeError),
        ("text", "", ValueError),
        ("text", " \t", ValueError),
        ("text", None, TypeError),
        ("generation_method", "model", ValueError),
        ("generation_method", "", ValueError),
    ],
)
def test_invalid_field_is_rejected(
    field: str,
    value: object,
    exception: type[Exception],
) -> None:
    arguments = {
        "response_type": "intent_response",
        "language": "es",
        "text": "Texto",
        "generation_method": "deterministic_template",
    }
    arguments[field] = value

    with pytest.raises(exception):
        GeneratedConversationResponse(**arguments)


def test_language_and_text_are_preserved_exactly() -> None:
    result = GeneratedConversationResponse(
        "intent_response",
        "  es  ",
        "  Texto exacto.  ",
        "deterministic_template",
    )

    assert result.language == "  es  "
    assert result.text == "  Texto exacto.  "
