from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from mike_app.perception.model import PerceptionResult


class _StructuredPerception(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    intent: str
    confidence: float
    entities: dict[str, Any]


class _ResponsesAPI(Protocol):
    def parse(self, **kwargs: Any) -> Any:
        ...


class _OpenAIClient(Protocol):
    responses: _ResponsesAPI


class OpenAIPerceptionClient:
    def __init__(
        self,
        client: _OpenAIClient,
        model: str,
    ) -> None:
        if not hasattr(client, "responses") or not callable(
            getattr(client.responses, "parse", None)
        ):
            raise TypeError("client must provide responses.parse")
        if not isinstance(model, str):
            raise TypeError("model must be a string")
        if not model or model.strip() == "":
            raise ValueError("model must be non-empty")
        self._client = client
        self._model = model

    def perceive(
        self,
        text: str,
    ) -> PerceptionResult:
        response = self._client.responses.parse(
            model=self._model,
            instructions=(
                "Analyze the message's primary communicative intent. "
                "Detect its language, provide a stable machine-readable "
                "intent label, assign confidence from 0 to 1, and extract "
                "only explicitly supported entities. Do not invent facts."
            ),
            input=text,
            temperature=0,
            text_format=_StructuredPerception,
        )
        parsed = response.output_parsed
        if not isinstance(parsed, _StructuredPerception):
            raise TypeError(
                "OpenAI response did not contain structured perception"
            )
        return PerceptionResult(
            language=parsed.language,
            intent=parsed.intent,
            confidence=parsed.confidence,
            entities=parsed.entities,
        )
