from __future__ import annotations

import uuid

from mike_app.runtime.event import Event


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events_by_id: dict[uuid.UUID, Event] = {}
        self._tenant_events: dict[str, list[Event]] = {}

    def append(self, event: Event) -> None:
        if not isinstance(event, Event):
            raise TypeError("append expects an Event instance")
        if event.event_id in self._events_by_id:
            raise ValueError("duplicate event_id")

        self._events_by_id[event.event_id] = event
        self._tenant_events.setdefault(event.tenant_id, []).append(event)

    def get_by_id(self, tenant_id: str, event_id: uuid.UUID) -> Event | None:
        self._validate_tenant_id(tenant_id)
        event = self._events_by_id.get(event_id)
        if event is None:
            return None
        if event.tenant_id != tenant_id:
            return None
        return event

    def list_for_tenant(
        self,
        tenant_id: str,
        event_type: str | None = None,
    ) -> tuple[Event, ...]:
        self._validate_tenant_id(tenant_id)
        if event_type is not None:
            self._validate_event_type(event_type)

        tenant_events = self._tenant_events.get(tenant_id, [])
        if event_type is None:
            return tuple(tenant_events)
        return tuple(event for event in tenant_events if event.event_type == event_type)

    def count_for_tenant(self, tenant_id: str) -> int:
        self._validate_tenant_id(tenant_id)
        return len(self._tenant_events.get(tenant_id, []))

    def total_count(self) -> int:
        return len(self._events_by_id)

    def _validate_tenant_id(self, tenant_id: str) -> None:
        if not tenant_id or tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")

    def _validate_event_type(self, event_type: str) -> None:
        if not event_type or event_type.strip() == "":
            raise ValueError("event_type is required and must be non-empty")
