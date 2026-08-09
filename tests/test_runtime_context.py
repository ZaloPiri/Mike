from dataclasses import FrozenInstanceError

import pytest

from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.event import Event


def test_create_accepts_event() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    context = RuntimeContext.create(event)

    assert context.event is event


def test_direct_construction_accepts_event() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    context = RuntimeContext(event=event)

    assert context.event is event


def test_create_rejects_none() -> None:
    with pytest.raises(TypeError, match="Event"):
        RuntimeContext.create(None)


def test_create_rejects_unrelated_objects() -> None:
    with pytest.raises(TypeError, match="Event"):
        RuntimeContext.create(object())


def test_direct_construction_rejects_none() -> None:
    with pytest.raises(TypeError, match="Event"):
        RuntimeContext(event=None)


def test_direct_construction_rejects_unrelated_objects() -> None:
    with pytest.raises(TypeError, match="Event"):
        RuntimeContext(event=object())


def test_exact_event_identity_is_retained() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    context = RuntimeContext.create(event)

    assert context.event is event


def test_context_is_immutable() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    with pytest.raises(FrozenInstanceError):
        context.event = event


def test_event_cannot_be_reassigned() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    with pytest.raises(FrozenInstanceError):
        context.event = Event.create(tenant_id="tenant-2", event_type="other.event")


def test_undeclared_attributes_cannot_be_added_because_slots_are_enabled() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    with pytest.raises((AttributeError, TypeError)):
        context.extra = "value"


def test_context_does_not_duplicate_event_fields() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    assert not hasattr(context, "tenant_id")
    assert not hasattr(context, "event_type")
    assert not hasattr(context, "event_id")
    assert not hasattr(context, "payload")
    assert not hasattr(context, "occurred_at")


def test_two_contexts_can_reference_the_same_event() -> None:
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    first_context = RuntimeContext.create(event)
    second_context = RuntimeContext.create(event)

    assert first_context.event is event
    assert second_context.event is event
    assert first_context.event is second_context.event


def test_creating_context_does_not_mutate_event() -> None:
    event = Event.create(
        tenant_id="tenant-1",
        event_type="test.event",
        payload={"items": [1, 2]},
    )
    original_state = event.to_dict()

    RuntimeContext.create(event)

    assert event.to_dict() == original_state
