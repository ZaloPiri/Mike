from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mike_app.runtime.event import Event

EventHandler = Callable[[Event], None]


class RuntimeHandlerRegistry:
    def __init__(self) -> None:
        self._handlers_by_event_type: dict[str, tuple[EventHandler, ...]] = {}

    def register(
        self,
        event_type: str,
        handler: EventHandler,
    ) -> None:
        self._validate_event_type(event_type)
        self._validate_handler(handler)

        existing_handlers = self._handlers_by_event_type.get(event_type, ())
        for existing_handler in existing_handlers:
            if existing_handler is handler:
                raise ValueError("handler is already registered for this event_type")

        self._handlers_by_event_type[event_type] = existing_handlers + (handler,)

    def unregister(
        self,
        event_type: str,
        handler: EventHandler,
    ) -> None:
        self._validate_event_type(event_type)
        self._validate_handler(handler)

        existing_handlers = self._handlers_by_event_type.get(event_type, ())
        updated_handlers = tuple(
            existing_handler
            for existing_handler in existing_handlers
            if existing_handler is not handler
        )

        if len(updated_handlers) == len(existing_handlers):
            raise ValueError("handler is not registered for this event_type")

        if updated_handlers:
            self._handlers_by_event_type[event_type] = updated_handlers
        else:
            self._handlers_by_event_type.pop(event_type, None)

    def handlers_for(self, event: Event) -> tuple[EventHandler, ...]:
        if not isinstance(event, Event):
            raise TypeError("handlers_for expects an Event instance")
        return self.handlers_for_type(event.event_type)

    def handlers_for_type(self, event_type: str) -> tuple[EventHandler, ...]:
        self._validate_event_type(event_type)
        return self._handlers_by_event_type.get(event_type, ())

    def count_for_type(self, event_type: str) -> int:
        self._validate_event_type(event_type)
        return len(self._handlers_by_event_type.get(event_type, ()))

    def total_count(self) -> int:
        return sum(len(handlers) for handlers in self._handlers_by_event_type.values())

    def _validate_event_type(self, event_type: str) -> None:
        if not isinstance(event_type, str):
            raise TypeError("event_type must be a string")
        if not event_type or event_type.strip() == "":
            raise ValueError("event_type must be a non-empty string")

    def _validate_handler(self, handler: EventHandler) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
