from dataclasses import FrozenInstanceError

import pytest

from mike_app.conversation.response_planning import (
    ConversationResponseRequest,
)


@pytest.mark.parametrize(
    "arguments",
    [
        ("intent_response", "es", "greeting", (), None),
        (
            "missing_information",
            "es",
            "place_order",
            ("product",),
            None,
        ),
        ("clarification", "es", "unknown", (), None),
        (
            "human_handoff",
            "es",
            "human_assistance",
            (),
            "human_requested",
        ),
        (
            "human_handoff",
            "es",
            "complaint",
            (),
            "complaint_requires_human",
        ),
    ],
)
def test_valid_construction_for_every_response_type(
    arguments: tuple[object, ...],
) -> None:
    result = ConversationResponseRequest(*arguments)

    assert result.response_type == arguments[0]


def test_model_is_frozen_and_slotted() -> None:
    result = ConversationResponseRequest(
        "intent_response",
        "es",
        "greeting",
        (),
        None,
    )

    with pytest.raises(FrozenInstanceError):
        result.intent = "unknown"
    with pytest.raises((AttributeError, TypeError)):
        result.extra = "value"


@pytest.mark.parametrize(
    "language",
    ["", " ", "\t"],
)
def test_invalid_language_is_rejected(language: str) -> None:
    with pytest.raises(ValueError, match="target_language"):
        ConversationResponseRequest(
            "intent_response",
            language,
            "greeting",
            (),
            None,
        )


def test_language_is_preserved_exactly() -> None:
    result = ConversationResponseRequest(
        "intent_response",
        "  Español (AR)  ",
        "greeting",
        (),
        None,
    )

    assert result.target_language == "  Español (AR)  "


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("response_type", "unsupported", "canonical response"),
        ("intent", "hello", "canonical normalized"),
        ("handoff_reason", "unsupported", "handoff_reason"),
    ],
)
def test_invalid_canonical_value_is_rejected(
    field: str,
    value: object,
    match: str,
) -> None:
    arguments = {
        "response_type": "intent_response",
        "target_language": "es",
        "intent": "greeting",
        "requested_entities": (),
        "handoff_reason": None,
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=match):
        ConversationResponseRequest(**arguments)


@pytest.mark.parametrize(
    "requested_entities",
    [
        ("unsupported",),
        ("",),
        (" ",),
        (1,),
        ("product", "product"),
    ],
)
def test_invalid_requested_entities_are_rejected(
    requested_entities: tuple[object, ...],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ConversationResponseRequest(
            "missing_information",
            "es",
            "place_order",
            requested_entities,
            None,
        )


def test_requested_entity_order_is_preserved_and_input_is_copied() -> None:
    supplied = ["quantity", "product"]

    result = ConversationResponseRequest(
        "missing_information",
        "es",
        "place_order",
        supplied,
        None,
    )
    supplied.reverse()

    assert result.requested_entities == ("quantity", "product")


@pytest.mark.parametrize(
    "arguments",
    [
        ("intent_response", "es", "greeting", ("product",), None),
        (
            "intent_response",
            "es",
            "greeting",
            (),
            "human_requested",
        ),
        ("missing_information", "es", "place_order", (), None),
        (
            "missing_information",
            "es",
            "place_order",
            ("product",),
            "human_requested",
        ),
        ("clarification", "es", "unknown", ("product",), None),
        (
            "clarification",
            "es",
            "unknown",
            (),
            "human_requested",
        ),
        ("human_handoff", "es", "complaint", ("product",), None),
        ("human_handoff", "es", "complaint", (), None),
    ],
)
def test_inconsistent_combinations_are_rejected(
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        ConversationResponseRequest(*arguments)
