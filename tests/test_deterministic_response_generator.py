import pytest

from mike_app.conversation.response_generation import (
    DeterministicResponseGenerator,
)


@pytest.mark.parametrize(
    (
        "response_type",
        "intent",
        "requested_entities",
        "handoff_reason",
        "expected_text",
    ),
    [
        (
            "intent_response",
            "greeting",
            (),
            None,
            "¡Hola! ¿En qué puedo ayudarte?",
        ),
        (
            "intent_response",
            "product_inquiry",
            (),
            None,
            "Para ayudarte con los productos necesito consultar la "
            "información del comercio.",
        ),
        (
            "intent_response",
            "price_inquiry",
            (),
            None,
            "Para informarte el precio necesito consultar la información "
            "del comercio.",
        ),
        (
            "intent_response",
            "availability_inquiry",
            (),
            None,
            "Para confirmarte la disponibilidad necesito consultar la "
            "información del comercio.",
        ),
        (
            "intent_response",
            "place_order",
            (),
            None,
            "Entendí que querés realizar un pedido. Antes de confirmarlo "
            "necesito consultar la información del comercio.",
        ),
        (
            "missing_information",
            "place_order",
            ("product",),
            None,
            "¿Qué producto necesitás?",
        ),
        (
            "missing_information",
            "place_order",
            ("quantity",),
            None,
            "¿Qué cantidad necesitás?",
        ),
        (
            "missing_information",
            "place_order",
            ("product", "quantity"),
            None,
            "¿Qué producto y qué cantidad necesitás?",
        ),
        (
            "clarification",
            "modify_order",
            (),
            None,
            "No terminé de entender tu mensaje. ¿Podés reformularlo?",
        ),
        (
            "clarification",
            "cancel_order",
            (),
            None,
            "No terminé de entender tu mensaje. ¿Podés reformularlo?",
        ),
        (
            "clarification",
            "unknown",
            (),
            None,
            "No terminé de entender tu mensaje. ¿Podés reformularlo?",
        ),
        (
            "human_handoff",
            "human_assistance",
            (),
            "human_requested",
            "Voy a derivarte con una persona para que pueda ayudarte.",
        ),
        (
            "human_handoff",
            "complaint",
            (),
            "complaint_requires_human",
            "Lamento lo ocurrido. Voy a derivarte con una persona para "
            "que pueda ayudarte.",
        ),
    ],
)
def test_exact_supported_templates(
    response_type: str,
    intent: str,
    requested_entities: tuple[str, ...],
    handoff_reason: str | None,
    expected_text: str,
) -> None:
    result = DeterministicResponseGenerator().generate(
        response_type=response_type,
        language="es",
        intent=intent,
        requested_entities=requested_entities,
        handoff_reason=handoff_reason,
    )

    assert result.text == expected_text
    assert result.response_type == response_type
    assert result.language == "es"
    assert result.generation_method == "deterministic_template"


@pytest.mark.parametrize("language", ["ES", "es-AR", "Spanish", "español"])
def test_unsupported_language_is_rejected(language: str) -> None:
    with pytest.raises(ValueError, match="exactly es"):
        DeterministicResponseGenerator().generate(
            response_type="intent_response",
            language=language,
            intent="greeting",
            requested_entities=(),
            handoff_reason=None,
        )


def test_unsupported_response_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="canonical response"):
        DeterministicResponseGenerator().generate(
            response_type="fallback_response",
            language="es",
            intent="greeting",
            requested_entities=(),
            handoff_reason=None,
        )


@pytest.mark.parametrize(
    "intent",
    [
        "modify_order",
        "cancel_order",
        "complaint",
        "human_assistance",
        "unknown",
    ],
)
def test_unsupported_intent_response_intent_is_rejected(
    intent: str,
) -> None:
    with pytest.raises(ValueError, match="intent_response"):
        DeterministicResponseGenerator().generate(
            response_type="intent_response",
            language="es",
            intent=intent,
            requested_entities=(),
            handoff_reason=None,
        )


@pytest.mark.parametrize(
    ("intent", "requested_entities"),
    [
        ("greeting", ("product",)),
        ("place_order", ()),
        ("place_order", ("quantity", "product")),
        ("place_order", ("notes",)),
        ("place_order", ("product", "quantity", "notes")),
    ],
)
def test_invalid_missing_information_combination_is_rejected(
    intent: str,
    requested_entities: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        DeterministicResponseGenerator().generate(
            response_type="missing_information",
            language="es",
            intent=intent,
            requested_entities=requested_entities,
            handoff_reason=None,
        )


def test_duplicate_requested_entities_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DeterministicResponseGenerator().generate(
            response_type="missing_information",
            language="es",
            intent="place_order",
            requested_entities=("product", "product"),
            handoff_reason=None,
        )


@pytest.mark.parametrize("intent", ["greeting", "place_order", "complaint"])
def test_invalid_clarification_intent_is_rejected(intent: str) -> None:
    with pytest.raises(ValueError, match="clarification"):
        DeterministicResponseGenerator().generate(
            response_type="clarification",
            language="es",
            intent=intent,
            requested_entities=(),
            handoff_reason=None,
        )


@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        ("complaint", "human_requested"),
        ("human_assistance", "complaint_requires_human"),
        ("greeting", "human_requested"),
    ],
)
def test_invalid_handoff_combination_is_rejected(
    intent: str,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match="human_handoff"):
        DeterministicResponseGenerator().generate(
            response_type="human_handoff",
            language="es",
            intent=intent,
            requested_entities=(),
            handoff_reason=reason,
        )


@pytest.mark.parametrize("container", ["product", b"product", None])
def test_invalid_requested_entities_container_is_rejected(
    container: object,
) -> None:
    with pytest.raises(TypeError, match="sequence"):
        DeterministicResponseGenerator().generate(
            response_type="missing_information",
            language="es",
            intent="place_order",
            requested_entities=container,
            handoff_reason=None,
        )


def test_input_collection_is_not_mutated_and_result_is_deterministic() -> None:
    requested_entities = ["product", "quantity"]
    generator = DeterministicResponseGenerator()
    arguments = {
        "response_type": "missing_information",
        "language": "es",
        "intent": "place_order",
        "requested_entities": requested_entities,
        "handoff_reason": None,
    }

    first = generator.generate(**arguments)
    second = generator.generate(**arguments)

    assert first == second
    assert requested_entities == ["product", "quantity"]
    assert first.text == "¿Qué producto y qué cantidad necesitás?"
