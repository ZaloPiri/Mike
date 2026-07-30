from dataclasses import FrozenInstanceError

import pytest

from mike_app.perception.normalization import (
    CANONICAL_ENTITIES,
    CANONICAL_INTENTS,
    NormalizedPerception,
    PerceptionNormalizer,
)


INTENT_ALIASES = {
    "hello": "greeting",
    "greet": "greeting",
    "salutation": "greeting",
    "ask_product": "product_inquiry",
    "product_question": "product_inquiry",
    "product_query": "product_inquiry",
    "menu_inquiry": "product_inquiry",
    "ask_price": "price_inquiry",
    "price_question": "price_inquiry",
    "pricing_inquiry": "price_inquiry",
    "cost_inquiry": "price_inquiry",
    "ask_availability": "availability_inquiry",
    "availability_query": "availability_inquiry",
    "stock_inquiry": "availability_inquiry",
    "product_availability": "availability_inquiry",
    "create_order": "place_order",
    "order_request": "place_order",
    "purchase_intent": "place_order",
    "order_creation": "place_order",
    "change_order": "modify_order",
    "edit_order": "modify_order",
    "update_order": "modify_order",
    "order_cancellation": "cancel_order",
    "cancel_purchase": "cancel_order",
    "complaint_request": "complaint",
    "customer_complaint": "complaint",
    "dissatisfaction": "complaint",
    "request_human": "human_assistance",
    "human_help": "human_assistance",
    "agent_request": "human_assistance",
    "talk_to_person": "human_assistance",
    "unclear": "unknown",
    "unsupported": "unknown",
    "other": "unknown",
}

ENTITY_ALIASES = {
    "item": "product",
    "product_name": "product",
    "menu_item": "product",
    "service": "product",
    "service_name": "product",
    "amount": "quantity",
    "count": "quantity",
    "qty": "quantity",
    "quantity_value": "quantity",
    "unit": "quantity_unit",
    "amount_unit": "quantity_unit",
    "qty_unit": "quantity_unit",
    "requested_datetime": "requested_datetime_text",
    "requested_time": "requested_datetime_text",
    "requested_date": "requested_datetime_text",
    "date_time": "requested_datetime_text",
    "delivery_time": "requested_datetime_text",
    "pickup_time": "requested_datetime_text",
    "name": "customer_name",
    "client_name": "customer_name",
    "buyer_name": "customer_name",
    "phone_number": "phone",
    "telephone": "phone",
    "mobile": "phone",
    "contact_phone": "phone",
    "address": "delivery_address",
    "shipping_address": "delivery_address",
    "destination": "delivery_address",
    "payment": "payment_method",
    "pay_method": "payment_method",
    "payment_type": "payment_method",
    "note": "notes",
    "comment": "notes",
    "comments": "notes",
    "special_instructions": "notes",
    "observations": "notes",
}


def test_normalized_perception_is_valid_frozen_and_slotted() -> None:
    result = NormalizedPerception(
        language="Spanish",
        intent="place_order",
        confidence=0.8,
        entities={"product": "sandwich"},
    )

    assert result.language == "Spanish"
    assert result.intent == "place_order"
    assert result.confidence == 0.8
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.intent = "unknown"


@pytest.mark.parametrize("intent", sorted(CANONICAL_INTENTS))
def test_all_canonical_intents_are_valid(intent: str) -> None:
    assert NormalizedPerception("es", intent, 0.5, {}).intent == intent


def test_unknown_normalized_intent_is_rejected() -> None:
    with pytest.raises(ValueError, match="canonical intent"):
        NormalizedPerception("es", "new_intent", 0.5, {})


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_confidence_boundaries_are_valid(confidence: float) -> None:
    assert NormalizedPerception(
        "es", "unknown", confidence, {}
    ).confidence == confidence


@pytest.mark.parametrize("confidence", [True, False])
def test_bool_confidence_is_rejected(confidence: bool) -> None:
    with pytest.raises(TypeError, match="confidence"):
        NormalizedPerception("es", "unknown", confidence, {})


@pytest.mark.parametrize("language", ["", "   "])
def test_invalid_language_is_rejected(language: str) -> None:
    with pytest.raises(ValueError, match="language"):
        NormalizedPerception(language, "unknown", 0.5, {})


def test_invalid_entities_and_unknown_keys_are_rejected() -> None:
    with pytest.raises(TypeError, match="mapping"):
        NormalizedPerception("es", "unknown", 0.5, [])
    with pytest.raises(ValueError, match="unknown canonical"):
        NormalizedPerception("es", "unknown", 0.5, {"other": "value"})


def test_entities_are_defensively_copied_and_deeply_immutable() -> None:
    original = {"notes": {"values": [1, 2]}}
    result = NormalizedPerception("es", "unknown", 0.5, original)
    original["notes"]["values"][0] = 9

    assert result.entities["notes"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        result.entities["notes"]["values"][0] = 9


def test_non_json_compatible_entity_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        NormalizedPerception(
            "es",
            "unknown",
            0.5,
            {"notes": object()},
        )


@pytest.mark.parametrize("intent", sorted(CANONICAL_INTENTS))
def test_canonical_intent_maps_to_itself(intent: str) -> None:
    result = PerceptionNormalizer().normalize(
        language="es",
        intent=intent,
        confidence=0.5,
        entities={},
    )

    assert result.intent == intent


@pytest.mark.parametrize(
    ("intent", "expected"),
    list(INTENT_ALIASES.items()),
)
def test_every_intent_alias_is_supported(
    intent: str,
    expected: str,
) -> None:
    result = PerceptionNormalizer().normalize(
        language="es",
        intent=intent,
        confidence=0.5,
        entities={},
    )

    assert result.intent == expected


@pytest.mark.parametrize(
    "intent",
    [" Place Order ", "PLACE ORDER", "place-order", "place___order"],
)
def test_intent_token_normalization(intent: str) -> None:
    result = PerceptionNormalizer().normalize(
        language="es",
        intent=intent,
        confidence=0.5,
        entities={},
    )

    assert result.intent == "place_order"


@pytest.mark.parametrize(
    "intent",
    ["something_unrecognized", "place_orders", "prefix_place_order_suffix"],
)
def test_unknown_intent_has_no_fuzzy_or_substring_matching(
    intent: str,
) -> None:
    result = PerceptionNormalizer().normalize(
        language="Spanish",
        intent=intent,
        confidence=0.01,
        entities={},
    )

    assert result.intent == "unknown"
    assert result.language == "Spanish"
    assert result.confidence == 0.01


@pytest.mark.parametrize("entity", sorted(CANONICAL_ENTITIES))
def test_canonical_entity_maps_to_itself(entity: str) -> None:
    result = PerceptionNormalizer().normalize(
        language="es",
        intent="unknown",
        confidence=0.5,
        entities={entity: "value"},
    )

    assert dict(result.entities) == {entity: "value"}


@pytest.mark.parametrize(
    ("entity", "expected"),
    list(ENTITY_ALIASES.items()),
)
def test_every_entity_alias_is_supported(
    entity: str,
    expected: str,
) -> None:
    result = PerceptionNormalizer().normalize(
        language="es",
        intent="unknown",
        confidence=0.5,
        entities={entity: "value"},
    )

    assert dict(result.entities) == {expected: "value"}


def test_entity_normalization_preserves_values_and_omits_unknowns() -> None:
    entities = {
        " QTY ": "dos",
        "delivery-time": "mañana",
        "amount unit": "docenas",
        "unsupported_key": {"unchanged": True},
    }
    original = {
        " QTY ": "dos",
        "delivery-time": "mañana",
        "amount unit": "docenas",
        "unsupported_key": {"unchanged": True},
    }

    result = PerceptionNormalizer().normalize(
        language="es",
        intent="unknown",
        confidence=0.5,
        entities=entities,
    )

    assert dict(result.entities) == {
        "quantity": "dos",
        "requested_datetime_text": "mañana",
        "quantity_unit": "docenas",
    }
    assert entities == original


def test_empty_entities_and_deterministic_equality() -> None:
    normalizer = PerceptionNormalizer()
    arguments = {
        "language": "es",
        "intent": "hello",
        "confidence": 0.5,
        "entities": {},
    }

    assert normalizer.normalize(**arguments) == normalizer.normalize(
        **arguments
    )


def test_duplicate_canonical_entity_collision_raises() -> None:
    with pytest.raises(ValueError, match="duplicate canonical"):
        PerceptionNormalizer().normalize(
            language="es",
            intent="unknown",
            confidence=0.5,
            entities={"item": "sandwich", "product": "empanada"},
        )


def test_non_string_source_entity_key_is_rejected() -> None:
    with pytest.raises(TypeError, match="entity keys"):
        PerceptionNormalizer().normalize(
            language="es",
            intent="unknown",
            confidence=0.5,
            entities={1: "value"},
        )
