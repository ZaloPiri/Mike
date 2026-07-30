import pytest

from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


def test_constructor_accepts_runtime_handler_registry() -> None:
    registry = RuntimeHandlerRegistry()

    dispatcher = RuntimeDispatcher(registry)

    assert dispatcher._handler_registry is registry


def test_constructor_rejects_none() -> None:
    with pytest.raises(TypeError, match="RuntimeHandlerRegistry"):
        RuntimeDispatcher(None)


def test_constructor_rejects_unrelated_objects() -> None:
    with pytest.raises(TypeError, match="RuntimeHandlerRegistry"):
        RuntimeDispatcher(object())


def test_dispatch_rejects_non_event_values() -> None:
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())

    with pytest.raises(TypeError, match="Event"):
        dispatcher.dispatch(object())


def test_dispatch_with_no_registered_handlers_returns_none() -> None:
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    assert dispatcher.dispatch(event) is None


def test_one_registered_handler_is_invoked_once() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[Event] = []

    def handler(event: Event) -> None:
        calls.append(event)

    registry.register("test.event", handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)

    assert calls == [event]


def test_multiple_handlers_are_invoked_in_registration_order() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []

    def first_handler(event: Event) -> None:
        calls.append("first")

    def second_handler(event: Event) -> None:
        calls.append("second")

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)

    assert calls == ["first", "second"]


def test_exact_same_event_object_is_passed_to_every_handler() -> None:
    registry = RuntimeHandlerRegistry()
    seen: list[Event] = []

    def first_handler(event: Event) -> None:
        seen.append(event)

    def second_handler(event: Event) -> None:
        seen.append(event)

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)

    assert seen == [event, event]
    assert seen[0] is event
    assert seen[1] is event


def test_dispatch_returns_none() -> None:
    registry = RuntimeHandlerRegistry()
    registry.register("test.event", lambda event: None)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    assert dispatcher.dispatch(event) is None


def test_only_handlers_for_exact_event_type_are_invoked() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []

    def matching_handler(event: Event) -> None:
        calls.append("matching")

    def unrelated_handler(event: Event) -> None:
        calls.append("unrelated")

    registry.register("test.event", matching_handler)
    registry.register("other.event", unrelated_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)

    assert calls == ["matching"]


def test_handler_exception_is_propagated_unchanged() -> None:
    registry = RuntimeHandlerRegistry()
    error = ValueError("boom")

    def failing_handler(event: Event) -> None:
        raise error

    def later_handler(event: Event) -> None:
        raise AssertionError("should not run")

    registry.register("test.event", failing_handler)
    registry.register("test.event", later_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(ValueError, match="boom") as exc_info:
        dispatcher.dispatch(event)

    assert exc_info.value is error


def test_later_handlers_are_not_invoked_after_failure() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []

    def failing_handler(event: Event) -> None:
        calls.append("first")
        raise RuntimeError("stop")

    def later_handler(event: Event) -> None:
        calls.append("second")

    registry.register("test.event", failing_handler)
    registry.register("test.event", later_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(RuntimeError, match="stop"):
        dispatcher.dispatch(event)

    assert calls == ["first"]


def test_failed_handler_is_not_retried() -> None:
    registry = RuntimeHandlerRegistry()
    calls = 0

    def failing_handler(event: Event) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("stop")

    registry.register("test.event", failing_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(RuntimeError, match="stop"):
        dispatcher.dispatch(event)

    with pytest.raises(RuntimeError, match="stop"):
        dispatcher.dispatch(event)

    assert calls == 2


def test_registry_remains_usable_after_handler_failure() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    attempts = 0

    def failing_handler(event: Event) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("stop")

    def later_handler(event: Event) -> None:
        calls.append("ok")

    registry.register("test.event", failing_handler)
    registry.register("test.event", later_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(RuntimeError, match="stop"):
        dispatcher.dispatch(event)

    dispatcher.dispatch(event)

    assert calls == ["ok"]


def test_dispatch_does_not_modify_handler_registration_counts() -> None:
    registry = RuntimeHandlerRegistry()
    calls = 0

    def handler(event: Event) -> None:
        nonlocal calls
        calls += 1

    registry.register("test.event", handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    assert registry.count_for_type("test.event") == 1
    dispatcher.dispatch(event)
    assert registry.count_for_type("test.event") == 1
    assert registry.total_count() == 1


def test_dispatch_does_not_create_or_replace_the_event() -> None:
    registry = RuntimeHandlerRegistry()
    seen: list[Event] = []

    def handler(event: Event) -> None:
        seen.append(event)

    registry.register("test.event", handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)

    assert seen == [event]
    assert seen[0] is event


def test_registering_a_handler_during_dispatch_affects_only_next_dispatch() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    registered_new_handler = False

    def first_handler(event: Event) -> None:
        calls.append("first")
        nonlocal registered_new_handler
        if not registered_new_handler:
            registry.register("test.event", second_handler)
            registered_new_handler = True

    def second_handler(event: Event) -> None:
        calls.append("second")

    registry.register("test.event", first_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)
    dispatcher.dispatch(event)

    assert calls == ["first", "first", "second"]


def test_unregistering_a_handler_during_dispatch_affects_only_next_dispatch() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    removed_handler = False

    def first_handler(event: Event) -> None:
        calls.append("first")
        nonlocal removed_handler
        if not removed_handler:
            registry.unregister("test.event", second_handler)
            removed_handler = True

    def second_handler(event: Event) -> None:
        calls.append("second")

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(event)
    dispatcher.dispatch(event)

    assert calls == ["first", "second", "first"]


def test_handler_can_dispatch_another_event_recursively() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[tuple[str, Event]] = []
    nested_event = Event.create(tenant_id="tenant-1", event_type="test.event")
    nested_dispatch_started = False

    def outer_handler(event: Event) -> None:
        calls.append(("outer", event))
        nonlocal nested_dispatch_started
        if event is initial_event and not nested_dispatch_started:
            nested_dispatch_started = True
            dispatcher.dispatch(nested_event)

    def inner_handler(event: Event) -> None:
        calls.append(("inner", event))

    registry.register("test.event", outer_handler)
    registry.register("test.event", inner_handler)
    dispatcher = RuntimeDispatcher(registry)
    initial_event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(initial_event)

    assert calls == [("outer", initial_event), ("outer", nested_event), ("inner", nested_event), ("inner", initial_event)]


def test_nested_dispatch_preserves_independent_handler_snapshots() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[tuple[str, Event]] = []
    registered_third_handler = False

    def first_handler(event: Event) -> None:
        calls.append(("first", event))
        nonlocal registered_third_handler
        if event is outer_event and not registered_third_handler:
            registry.register("test.event", third_handler)
            registered_third_handler = True
            dispatcher.dispatch(nested_event)

    def second_handler(event: Event) -> None:
        calls.append(("second", event))

    def third_handler(event: Event) -> None:
        calls.append(("third", event))

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)
    outer_event = Event.create(tenant_id="tenant-1", event_type="test.event")
    nested_event = Event.create(tenant_id="tenant-1", event_type="test.event")

    dispatcher.dispatch(outer_event)

    assert calls == [("first", outer_event), ("first", nested_event), ("second", nested_event), ("third", nested_event), ("second", outer_event)]
