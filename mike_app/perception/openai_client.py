from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from mike_app.perception.model import PerceptionResult


class _StructuredEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    value: str | int | float | bool | None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value or value.strip() == "":
            raise ValueError("entity name must be non-empty")
        return value


class _StructuredPerception(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    language: str
    intent: str
    confidence: float
    entities: list[_StructuredEntity]


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
                "intent label, and assign confidence from 0 to 1. Return "
                "entities as name/value entries. Extract only explicitly "
                "stated information, use stable snake_case entity names, "
                "avoid duplicate names, use an empty entities array when "
                "there are no entities, and do not invent missing values."
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
        entities: dict[str, str | int | float | bool | None] = {}
        for entity in parsed.entities:
            if entity.name in entities:
                raise ValueError(
                    f"duplicate entity name: {entity.name}"
                )
            entities[entity.name] = entity.value

        return PerceptionResult(
            language=parsed.language,
            intent=parsed.intent,
            confidence=parsed.confidence,
            entities=entities,
        )
