from __future__ import annotations

from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


class RuntimeDispatcher:
    def __init__(
        self,
        handler_registry: RuntimeHandlerRegistry,
    ) -> None:
        if not isinstance(handler_registry, RuntimeHandlerRegistry):
            raise TypeError("handler_registry must be a RuntimeHandlerRegistry")
        self._handler_registry = handler_registry

    def dispatch(self, event: Event) -> None:
        if not isinstance(event, Event):
            raise TypeError("dispatch expects an Event instance")

        handlers = self._handler_registry.handlers_for(event)

        for handler in handlers:
            handler(event)
