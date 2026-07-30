from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any


def _freeze_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    "entities must contain only JSON-compatible values"
                )
            frozen[key] = _freeze_json_compatible(item)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return tuple(_freeze_json_compatible(item) for item in value)
    raise ValueError("entities must contain only JSON-compatible values")


@dataclass(frozen=True, slots=True)
class PerceptionResult:
    language: str
    intent: str
    confidence: float
    entities: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.language, str):
            raise TypeError("language must be a string")
        if not self.language or self.language.strip() == "":
            raise ValueError("language must be non-empty")
        if not isinstance(self.intent, str):
            raise TypeError("intent must be a string")
        if not self.intent or self.intent.strip() == "":
            raise ValueError("intent must be non-empty")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence,
            Real,
        ):
            raise TypeError("confidence must be a real number")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not isinstance(self.entities, Mapping):
            raise TypeError("entities must be a mapping")

        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(
            self,
            "entities",
            _freeze_json_compatible(self.entities),
        )
