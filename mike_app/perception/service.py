from __future__ import annotations

from typing import Protocol, runtime_checkable

from mike_app.perception.model import PerceptionResult


@runtime_checkable
class PerceptionClient(Protocol):
    def perceive(
        self,
        text: str,
    ) -> PerceptionResult:
        ...


class PerceptionService:
    def __init__(
        self,
        client: PerceptionClient,
    ) -> None:
        if not isinstance(client, PerceptionClient):
            raise TypeError("client must implement PerceptionClient")
        self._client = client

    def perceive(
        self,
        text: str,
    ) -> PerceptionResult:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text or text.strip() == "":
            raise ValueError("text must be non-empty")

        result = self._client.perceive(text)
        if not isinstance(result, PerceptionResult):
            raise TypeError("client must return a PerceptionResult")
        return result
