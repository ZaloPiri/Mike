import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from mike_app.perception.model import PerceptionResult
from mike_app.perception.openai_client import OpenAIPerceptionClient


class StubResponses:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        text_format = kwargs["text_format"]
        parsed = text_format(**self.payload)
        return SimpleNamespace(output_parsed=parsed, raw_secret="not exposed")


class StubOpenAI:
    def __init__(self, payload: object) -> None:
        self.responses = StubResponses(payload)


def valid_payload() -> dict[str, object]:
    return {
        "language": "es",
        "intent": "greeting",
        "confidence": 0.95,
        "entities": {"name": "Ana"},
    }


def test_adapter_constructs_confirmed_structured_output_request() -> None:
    sdk_client = StubOpenAI(valid_payload())
    adapter = OpenAIPerceptionClient(sdk_client, "test-model")

    result = adapter.perceive("Hola")

    assert isinstance(result, PerceptionResult)
    assert result.language == "es"
    assert result.intent == "greeting"
    assert result.confidence == 0.95
    assert dict(result.entities) == {"name": "Ana"}
    assert len(sdk_client.responses.calls) == 1
    call = sdk_client.responses.calls[0]
    assert call["model"] == "test-model"
    assert call["input"] == "Hola"
    assert call["temperature"] == 0
    schema = call["text_format"].model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "language",
        "intent",
        "confidence",
        "entities",
    }
    assert "not exposed" not in repr(result)


def test_installed_sdk_uses_strict_json_schema_without_network() -> None:
    captured_requests: list[dict[str, object]] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "test-model",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(valid_payload()),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(transport_handler)
    )
    sdk_client = OpenAI(
        api_key="test-key",
        http_client=http_client,
        max_retries=0,
    )
    adapter = OpenAIPerceptionClient(sdk_client, "test-model")

    result = adapter.perceive("Hola")

    assert result.intent == "greeting"
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request["model"] == "test-model"
    assert request["input"] == "Hola"
    assert request["temperature"] == 0
    structured_format = request["text"]["format"]
    assert structured_format["type"] == "json_schema"
    assert structured_format["strict"] is True
    assert set(structured_format["schema"]["required"]) == {
        "language",
        "intent",
        "confidence",
        "entities",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"language": "es"},
        {**valid_payload(), "extra": "forbidden"},
        {**valid_payload(), "confidence": "invalid"},
    ],
)
def test_adapter_rejects_malformed_structured_response(
    payload: object,
) -> None:
    adapter = OpenAIPerceptionClient(StubOpenAI(payload), "test-model")

    with pytest.raises(ValidationError):
        adapter.perceive("Hola")


def test_adapter_rejects_absent_parsed_output() -> None:
    sdk_client = StubOpenAI(valid_payload())

    def parse_without_output(**kwargs: object) -> object:
        return SimpleNamespace(output_parsed=None)

    sdk_client.responses.parse = parse_without_output
    adapter = OpenAIPerceptionClient(sdk_client, "test-model")

    with pytest.raises(TypeError, match="structured perception"):
        adapter.perceive("Hola")


def test_adapter_propagates_sdk_exception_unchanged() -> None:
    sdk_client = StubOpenAI(valid_payload())
    error = RuntimeError("sdk failure")
    sdk_client.responses.error = error
    adapter = OpenAIPerceptionClient(sdk_client, "test-model")

    with pytest.raises(RuntimeError, match="sdk failure") as exc_info:
        adapter.perceive("Hola")

    assert exc_info.value is error
    assert len(sdk_client.responses.calls) == 1


def test_adapter_constructor_validates_client_and_model() -> None:
    with pytest.raises(TypeError, match="responses.parse"):
        OpenAIPerceptionClient(object(), "test-model")
    with pytest.raises(TypeError, match="model"):
        OpenAIPerceptionClient(StubOpenAI(valid_payload()), None)
    with pytest.raises(ValueError, match="model"):
        OpenAIPerceptionClient(StubOpenAI(valid_payload()), "   ")
