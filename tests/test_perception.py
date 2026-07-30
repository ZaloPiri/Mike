from dataclasses import FrozenInstanceError

import pytest

from mike_app.perception.model import PerceptionResult
from mike_app.perception.service import PerceptionService


class FakePerceptionClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[str] = []
        self.error: Exception | None = None

    def perceive(self, text: str):
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.result


def test_perception_result_accepts_valid_values_and_is_frozen() -> None:
    result = PerceptionResult(
        language="es",
        intent="place_order",
        confidence=0.8,
        entities={"quantity": 2},
    )

    assert result.language == "es"
    assert result.intent == "place_order"
    assert result.confidence == 0.8
    assert result.entities["quantity"] == 2
    with pytest.raises(FrozenInstanceError):
        result.intent = "other"


@pytest.mark.parametrize("language", ["", "   "])
def test_perception_result_rejects_empty_language(language: str) -> None:
    with pytest.raises(ValueError, match="language"):
        PerceptionResult(language, "intent", 0.5, {})


def test_perception_result_rejects_non_string_language() -> None:
    with pytest.raises(TypeError, match="language"):
        PerceptionResult(None, "intent", 0.5, {})


@pytest.mark.parametrize("intent", ["", "   "])
def test_perception_result_rejects_empty_intent(intent: str) -> None:
    with pytest.raises(ValueError, match="intent"):
        PerceptionResult("es", intent, 0.5, {})


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_perception_result_accepts_confidence_boundaries(
    confidence: float,
) -> None:
    result = PerceptionResult("es", "intent", confidence, {})

    assert result.confidence == confidence


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_perception_result_rejects_out_of_range_confidence(
    confidence: float,
) -> None:
    with pytest.raises(ValueError, match="confidence"):
        PerceptionResult("es", "intent", confidence, {})


@pytest.mark.parametrize("confidence", [True, False])
def test_perception_result_rejects_bool_confidence(
    confidence: bool,
) -> None:
    with pytest.raises(TypeError, match="confidence"):
        PerceptionResult("es", "intent", confidence, {})


def test_perception_result_rejects_non_mapping_entities() -> None:
    with pytest.raises(TypeError, match="mapping"):
        PerceptionResult("es", "intent", 0.5, [])


def test_entities_are_defensively_copied_and_deeply_immutable() -> None:
    original = {"nested": {"values": [1, 2]}}
    result = PerceptionResult("es", "intent", 0.5, original)
    original["nested"]["values"][0] = 9

    assert result.entities["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        result.entities["new"] = "value"
    with pytest.raises(TypeError):
        result.entities["nested"]["other"] = "value"
    with pytest.raises(TypeError):
        result.entities["nested"]["values"][0] = 9


@pytest.mark.parametrize(
    "entities",
    [
        {1: "invalid-key"},
        {"value": object()},
        {"value": b"bytes"},
    ],
)
def test_entities_reject_non_json_compatible_values(
    entities: object,
) -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        PerceptionResult("es", "intent", 0.5, entities)


def test_service_accepts_client_calls_once_and_returns_exact_result() -> None:
    result = PerceptionResult("es", "greeting", 0.9, {})
    client = FakePerceptionClient(result)
    service = PerceptionService(client)
    text = "  Hola  "

    returned = service.perceive(text)

    assert returned is result
    assert client.calls == [text]


def test_service_rejects_invalid_client() -> None:
    with pytest.raises(TypeError, match="PerceptionClient"):
        PerceptionService(object())


@pytest.mark.parametrize("text", ["", "   "])
def test_service_rejects_empty_text_without_calling_client(
    text: str,
) -> None:
    client = FakePerceptionClient(
        PerceptionResult("es", "intent", 0.5, {})
    )
    service = PerceptionService(client)

    with pytest.raises(ValueError, match="text"):
        service.perceive(text)

    assert client.calls == []


def test_service_rejects_non_string_text() -> None:
    client = FakePerceptionClient(
        PerceptionResult("es", "intent", 0.5, {})
    )
    service = PerceptionService(client)

    with pytest.raises(TypeError, match="text"):
        service.perceive(None)


def test_service_propagates_client_exception_unchanged() -> None:
    client = FakePerceptionClient(
        PerceptionResult("es", "intent", 0.5, {})
    )
    error = RuntimeError("provider failed")
    client.error = error
    service = PerceptionService(client)

    with pytest.raises(RuntimeError, match="provider failed") as exc_info:
        service.perceive("Hola")

    assert exc_info.value is error
    assert client.calls == ["Hola"]


def test_service_rejects_invalid_client_return_type() -> None:
    client = FakePerceptionClient({"language": "es"})
    service = PerceptionService(client)

    with pytest.raises(TypeError, match="PerceptionResult"):
        service.perceive("Hola")
