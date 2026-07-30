from copy import deepcopy
from inspect import signature

import pytest

from mike_app.conversation.action_planning import ConversationActionPlanner


@pytest.mark.parametrize(
    ("intent", "action", "reason"),
    [
        ("greeting", "respond", "intent_understood"),
        ("product_inquiry", "respond", "intent_understood"),
        ("price_inquiry", "respond", "intent_understood"),
        ("availability_inquiry", "respond", "intent_understood"),
        ("place_order", "respond", "intent_understood"),
        ("modify_order", "request_clarification", "intent_unclear"),
        ("cancel_order", "request_clarification", "intent_unclear"),
        ("complaint", "handoff_human", "complaint_requires_human"),
        ("human_assistance", "handoff_human", "human_requested"),
        ("unknown", "request_clarification", "intent_unclear"),
    ],
)
def test_exact_policy_for_every_canonical_intent(
    intent: str,
    action: str,
    reason: str,
) -> None:
    entities = (
        {"product": "sandwich", "quantity": 2}
        if intent == "place_order"
        else {}
    )

    result = ConversationActionPlanner().plan(
        intent=intent,
        entities=entities,
    )

    assert result.action == action
    assert result.reason == reason
    assert result.can_continue is (action == "respond")
    assert result.missing_entities == ()


@pytest.mark.parametrize(
    ("entities", "missing"),
    [
        ({"quantity": 2}, ("product",)),
        ({"product": "sandwich"}, ("quantity",)),
        ({}, ("product", "quantity")),
        ({"product": None, "quantity": None}, ("product", "quantity")),
        ({"product": " ", "quantity": "\t"}, ("product", "quantity")),
    ],
)
def test_place_order_missing_entities(
    entities: dict[str, object],
    missing: tuple[str, ...],
) -> None:
    result = ConversationActionPlanner().plan(
        intent="place_order",
        entities=entities,
    )

    assert result.action == "request_missing_information"
    assert result.reason == "missing_required_entities"
    assert result.can_continue is False
    assert result.missing_entities == missing


@pytest.mark.parametrize(
    ("product", "quantity"),
    [
        (0, 0),
        (False, False),
        ([], {}),
    ],
)
def test_zero_false_and_empty_collections_are_present(
    product: object,
    quantity: object,
) -> None:
    result = ConversationActionPlanner().plan(
        intent="place_order",
        entities={"product": product, "quantity": quantity},
    )

    assert result.action == "respond"


def test_input_values_and_mapping_are_unchanged() -> None:
    entities = {
        "product": {"name": "sandwich"},
        "quantity": [2],
        "notes": " unchanged ",
    }
    original = deepcopy(entities)

    ConversationActionPlanner().plan(
        intent="place_order",
        entities=entities,
    )

    assert entities == original


def test_same_input_produces_equal_result() -> None:
    planner = ConversationActionPlanner()
    arguments = {
        "intent": "place_order",
        "entities": {"product": "sandwich"},
    }

    assert planner.plan(**arguments) == planner.plan(**arguments)


def test_planner_has_no_language_or_confidence_dependency() -> None:
    parameters = signature(ConversationActionPlanner.plan).parameters

    assert tuple(parameters) == ("self", "intent", "entities")


@pytest.mark.parametrize("intent", ["order_request", "OTHER", ""])
def test_noncanonical_intent_is_rejected(intent: str) -> None:
    with pytest.raises(ValueError, match="canonical"):
        ConversationActionPlanner().plan(intent=intent, entities={})


@pytest.mark.parametrize("entities", [None, [], "invalid"])
def test_invalid_entity_mapping_is_rejected(entities: object) -> None:
    with pytest.raises(TypeError, match="mapping"):
        ConversationActionPlanner().plan(
            intent="greeting",
            entities=entities,
        )


@pytest.mark.parametrize("entities", [{"item": "x"}, {1: "x"}])
def test_invalid_entity_key_is_rejected(
    entities: dict[object, object],
) -> None:
    with pytest.raises(ValueError, match="canonical"):
        ConversationActionPlanner().plan(
            intent="greeting",
            entities=entities,
        )
