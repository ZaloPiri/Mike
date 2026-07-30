from copy import deepcopy

import pytest

from mike_app.conversation.response_planning import ResponseRequestPlanner


@pytest.mark.parametrize(
    ("state", "response_type", "handoff_reason"),
    [
        (
            {
                "action": "respond",
                "reason": "intent_understood",
                "can_continue": True,
                "missing_entities": (),
            },
            "intent_response",
            None,
        ),
        (
            {
                "action": "request_missing_information",
                "reason": "missing_required_entities",
                "can_continue": False,
                "missing_entities": ("product", "quantity"),
            },
            "missing_information",
            None,
        ),
        (
            {
                "action": "request_clarification",
                "reason": "intent_unclear",
                "can_continue": False,
                "missing_entities": (),
            },
            "clarification",
            None,
        ),
        (
            {
                "action": "handoff_human",
                "reason": "human_requested",
                "can_continue": False,
                "missing_entities": (),
            },
            "human_handoff",
            "human_requested",
        ),
        (
            {
                "action": "handoff_human",
                "reason": "complaint_requires_human",
                "can_continue": False,
                "missing_entities": (),
            },
            "human_handoff",
            "complaint_requires_human",
        ),
    ],
)
def test_exact_action_mapping(
    state: dict[str, object],
    response_type: str,
    handoff_reason: str | None,
) -> None:
    result = ResponseRequestPlanner().plan(
        **state,
        language="es",
        intent="place_order",
        entities={"product": "sandwich"},
    )

    assert result.response_type == response_type
    assert result.handoff_reason == handoff_reason
    assert result.requested_entities == tuple(
        state["missing_entities"]
    )
    assert not hasattr(result, "text")


def test_language_intent_and_requested_entity_order_are_preserved() -> None:
    result = ResponseRequestPlanner().plan(
        action="request_missing_information",
        reason="missing_required_entities",
        can_continue=False,
        missing_entities=["quantity", "product"],
        language="  Español (AR)  ",
        intent="place_order",
        entities={},
    )

    assert result.target_language == "  Español (AR)  "
    assert result.intent == "place_order"
    assert result.requested_entities == ("quantity", "product")


def test_entities_and_inputs_are_not_transformed_or_mutated() -> None:
    entities = {
        "product": {"name": "sandwich"},
        "quantity": [2],
    }
    missing_entities = ["product", "quantity"]
    original_entities = deepcopy(entities)

    ResponseRequestPlanner().plan(
        action="request_missing_information",
        reason="missing_required_entities",
        can_continue=False,
        missing_entities=missing_entities,
        language="es",
        intent="place_order",
        entities=entities,
    )

    assert entities == original_entities
    assert missing_entities == ["product", "quantity"]


@pytest.mark.parametrize(
    ("override", "exception"),
    [
        ({"action": "unsupported"}, ValueError),
        ({"reason": "unsupported"}, ValueError),
        ({"can_continue": 1}, TypeError),
        ({"missing_entities": "product"}, TypeError),
        ({"missing_entities": None}, TypeError),
        ({"missing_entities": ("unsupported",)}, ValueError),
        ({"missing_entities": ("product", "product")}, ValueError),
        ({"language": ""}, ValueError),
        ({"intent": "hello"}, ValueError),
        ({"entities": {"item": "sandwich"}}, ValueError),
    ],
)
def test_invalid_input_is_rejected(
    override: dict[str, object],
    exception: type[Exception],
) -> None:
    arguments = {
        "action": "request_missing_information",
        "reason": "missing_required_entities",
        "can_continue": False,
        "missing_entities": ("product",),
        "language": "es",
        "intent": "place_order",
        "entities": {},
    }
    arguments.update(override)

    with pytest.raises(exception):
        ResponseRequestPlanner().plan(**arguments)


@pytest.mark.parametrize(
    "override",
    [
        {"reason": "human_requested"},
        {"can_continue": False},
        {"missing_entities": ("product",)},
        {
            "action": "request_missing_information",
            "reason": "missing_required_entities",
            "can_continue": False,
            "missing_entities": (),
        },
        {
            "action": "request_clarification",
            "reason": "intent_unclear",
            "can_continue": True,
        },
        {
            "action": "handoff_human",
            "reason": "human_requested",
            "can_continue": False,
            "missing_entities": ("product",),
        },
    ],
)
def test_inconsistent_next_action_state_is_rejected(
    override: dict[str, object],
) -> None:
    arguments = {
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": (),
        "language": "es",
        "intent": "greeting",
        "entities": {},
    }
    arguments.update(override)

    with pytest.raises(ValueError, match="inconsistent"):
        ResponseRequestPlanner().plan(**arguments)


def test_deterministic_equality() -> None:
    planner = ResponseRequestPlanner()
    arguments = {
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": (),
        "language": "es",
        "intent": "greeting",
        "entities": {},
    }

    assert planner.plan(**arguments) == planner.plan(**arguments)
