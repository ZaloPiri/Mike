from dataclasses import FrozenInstanceError

import pytest

from mike_app.conversation.action_planning import ConversationNextAction


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "action": "respond",
            "reason": "intent_understood",
            "can_continue": True,
            "missing_entities": (),
        },
        {
            "action": "request_missing_information",
            "reason": "missing_required_entities",
            "can_continue": False,
            "missing_entities": ("product",),
        },
        {
            "action": "request_clarification",
            "reason": "intent_unclear",
            "can_continue": False,
            "missing_entities": (),
        },
        {
            "action": "handoff_human",
            "reason": "human_requested",
            "can_continue": False,
            "missing_entities": (),
        },
        {
            "action": "handoff_human",
            "reason": "complaint_requires_human",
            "can_continue": False,
            "missing_entities": (),
        },
    ],
)
def test_valid_construction_for_every_action(
    arguments: dict[str, object],
) -> None:
    result = ConversationNextAction(**arguments)

    assert result.action == arguments["action"]


def test_result_is_frozen_and_slotted() -> None:
    result = ConversationNextAction(
        "respond",
        "intent_understood",
        True,
        (),
    )

    with pytest.raises(FrozenInstanceError):
        result.action = "handoff_human"
    with pytest.raises((AttributeError, TypeError)):
        result.extra = "value"


@pytest.mark.parametrize(
    ("field", "value", "exception"),
    [
        ("action", "invalid", ValueError),
        ("reason", "invalid", ValueError),
        ("can_continue", 1, TypeError),
    ],
)
def test_invalid_scalar_fields_are_rejected(
    field: str,
    value: object,
    exception: type[Exception],
) -> None:
    arguments = {
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": (),
    }
    arguments[field] = value

    with pytest.raises(exception):
        ConversationNextAction(**arguments)


@pytest.mark.parametrize(
    "missing_entities",
    [
        ("unsupported",),
        ("",),
        (" ",),
        (1,),
        ("product", "product"),
    ],
)
def test_invalid_missing_entities_are_rejected(
    missing_entities: tuple[object, ...],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ConversationNextAction(
            "request_missing_information",
            "missing_required_entities",
            False,
            missing_entities,
        )


def test_missing_entity_order_is_preserved_and_input_is_copied() -> None:
    supplied = ["quantity", "product"]

    result = ConversationNextAction(
        "request_missing_information",
        "missing_required_entities",
        False,
        supplied,
    )
    supplied.reverse()

    assert result.missing_entities == ("quantity", "product")


@pytest.mark.parametrize(
    "arguments",
    [
        ("respond", "human_requested", True, ()),
        ("respond", "intent_understood", False, ()),
        ("respond", "intent_understood", True, ("product",)),
        (
            "request_missing_information",
            "intent_understood",
            False,
            ("product",),
        ),
        (
            "request_missing_information",
            "missing_required_entities",
            True,
            ("product",),
        ),
        (
            "request_missing_information",
            "missing_required_entities",
            False,
            (),
        ),
        ("request_clarification", "human_requested", False, ()),
        ("request_clarification", "intent_unclear", True, ()),
        (
            "request_clarification",
            "intent_unclear",
            False,
            ("product",),
        ),
        ("handoff_human", "intent_unclear", False, ()),
        ("handoff_human", "human_requested", True, ()),
        ("handoff_human", "human_requested", False, ("product",)),
    ],
)
def test_inconsistent_combinations_are_rejected(
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        ConversationNextAction(*arguments)
