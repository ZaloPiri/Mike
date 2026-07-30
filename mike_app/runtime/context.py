from __future__ import annotations

from dataclasses import dataclass

from mike_app.runtime.event import Event


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    event: Event

    def __post_init__(self) -> None:
        if not isinstance(self.event, Event):
            raise TypeError("event must be an Event instance")

    @classmethod
    def create(
        cls,
        event: Event,
    ) -> RuntimeContext:
        return cls(event=event)
