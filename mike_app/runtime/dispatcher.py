from __future__ import annotations

from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


class RuntimeDispatcher:
    def __init__(
        self,
        handler_registry: RuntimeHandlerRegistry,
    ) -> None:
        if not isinstance(handler_registry, RuntimeHandlerRegistry):
            raise TypeError("handler_registry must be a RuntimeHandlerRegistry")
        self._handler_registry = handler_registry

    def dispatch(self, context: RuntimeContext) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("dispatch expects a RuntimeContext instance")

        handlers = self._handler_registry.handlers_for(context)

        for handler in handlers:
            handler(context)
