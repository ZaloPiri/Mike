import pytest

from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


def make_context(event_type: str = "test.event") -> RuntimeContext:
    event = Event.create(tenant_id="tenant-1", event_type=event_type)
    return RuntimeContext.create(event)


def test_constructor_accepts_runtime_handler_registry() -> None:
    registry = RuntimeHandlerRegistry()

    dispatcher = RuntimeDispatcher(registry)

    assert dispatcher._handler_registry is registry


@pytest.mark.parametrize("invalid_registry", [None, object()])
def test_constructor_rejects_invalid_registry(invalid_registry: object) -> None:
    with pytest.raises(TypeError, match="RuntimeHandlerRegistry"):
        RuntimeDispatcher(invalid_registry)


def test_dispatch_accepts_runtime_context_with_no_handlers() -> None:
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())

    assert dispatcher.dispatch(make_context()) is None


def test_dispatch_rejects_bare_event() -> None:
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(TypeError, match="RuntimeContext"):
        dispatcher.dispatch(event)


def test_dispatch_rejects_none() -> None:
    dispatcher = RuntimeDispatcher(RuntimeHandlerRegistry())

    with pytest.raises(TypeError, match="RuntimeContext"):
        dispatcher.dispatch(None)


def test_handlers_run_once_in_registration_order_and_dispatch_returns_none() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []

    def first_handler(context: RuntimeContext) -> None:
        calls.append("first")

    def second_handler(context: RuntimeContext) -> None:
        calls.append("second")

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)

    assert dispatcher.dispatch(make_context()) is None
    assert calls == ["first", "second"]


def test_exact_same_context_and_event_reach_every_handler() -> None:
    registry = RuntimeHandlerRegistry()
    seen_contexts: list[RuntimeContext] = []
    seen_events: list[Event] = []

    def first_handler(context: RuntimeContext) -> None:
        seen_contexts.append(context)
        seen_events.append(context.event)

    def second_handler(context: RuntimeContext) -> None:
        seen_contexts.append(context)
        seen_events.append(context.event)

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    dispatcher.dispatch(context)

    assert seen_contexts[0] is context
    assert seen_contexts[1] is context
    assert seen_events[0] is event
    assert seen_events[1] is event


def test_only_handlers_for_exact_event_type_are_invoked() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    registry.register("test.event", lambda context: calls.append("matching"))
    registry.register("other.event", lambda context: calls.append("unrelated"))
    dispatcher = RuntimeDispatcher(registry)

    dispatcher.dispatch(make_context())

    assert calls == ["matching"]


def test_handler_exception_is_propagated_unchanged_and_stops_dispatch() -> None:
    registry = RuntimeHandlerRegistry()
    error = ValueError("boom")
    calls: list[str] = []

    def failing_handler(context: RuntimeContext) -> None:
        calls.append("first")
        raise error

    def later_handler(context: RuntimeContext) -> None:
        calls.append("second")

    registry.register("test.event", failing_handler)
    registry.register("test.event", later_handler)
    dispatcher = RuntimeDispatcher(registry)

    with pytest.raises(ValueError, match="boom") as exc_info:
        dispatcher.dispatch(make_context())

    assert exc_info.value is error
    assert calls == ["first"]


def test_failed_handler_is_not_retried() -> None:
    registry = RuntimeHandlerRegistry()
    calls = 0

    def failing_handler(context: RuntimeContext) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("stop")

    registry.register("test.event", failing_handler)
    dispatcher = RuntimeDispatcher(registry)
    context = make_context()

    with pytest.raises(RuntimeError, match="stop"):
        dispatcher.dispatch(context)

    assert calls == 1


def test_registry_remains_usable_after_handler_failure() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    attempts = 0

    def failing_once(context: RuntimeContext) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("stop")

    def later_handler(context: RuntimeContext) -> None:
        calls.append("ok")

    registry.register("test.event", failing_once)
    registry.register("test.event", later_handler)
    dispatcher = RuntimeDispatcher(registry)
    context = make_context()

    with pytest.raises(RuntimeError, match="stop"):
        dispatcher.dispatch(context)
    dispatcher.dispatch(context)

    assert calls == ["ok"]


def test_dispatch_does_not_modify_registration_counts() -> None:
    registry = RuntimeHandlerRegistry()
    registry.register("test.event", lambda context: None)
    dispatcher = RuntimeDispatcher(registry)

    dispatcher.dispatch(make_context())

    assert registry.count_for_type("test.event") == 1
    assert registry.total_count() == 1


def test_dispatch_does_not_construct_replacement_context_or_event() -> None:
    registry = RuntimeHandlerRegistry()
    seen: list[RuntimeContext] = []
    registry.register("test.event", seen.append)
    dispatcher = RuntimeDispatcher(registry)
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    dispatcher.dispatch(context)

    assert seen == [context]
    assert seen[0] is context
    assert seen[0].event is event


def test_registering_during_dispatch_affects_only_next_dispatch() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    registered = False

    def first_handler(context: RuntimeContext) -> None:
        nonlocal registered
        calls.append("first")
        if not registered:
            registry.register("test.event", second_handler)
            registered = True

    def second_handler(context: RuntimeContext) -> None:
        calls.append("second")

    registry.register("test.event", first_handler)
    dispatcher = RuntimeDispatcher(registry)
    context = make_context()

    dispatcher.dispatch(context)
    dispatcher.dispatch(context)

    assert calls == ["first", "first", "second"]


def test_unregistering_during_dispatch_affects_only_next_dispatch() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[str] = []
    removed = False

    def first_handler(context: RuntimeContext) -> None:
        nonlocal removed
        calls.append("first")
        if not removed:
            registry.unregister("test.event", second_handler)
            removed = True

    def second_handler(context: RuntimeContext) -> None:
        calls.append("second")

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)
    context = make_context()

    dispatcher.dispatch(context)
    dispatcher.dispatch(context)

    assert calls == ["first", "second", "first"]


def test_handler_can_explicitly_create_and_dispatch_second_context() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[tuple[str, RuntimeContext]] = []
    outer_context = make_context()
    nested_context = make_context()
    nested_started = False

    def first_handler(context: RuntimeContext) -> None:
        nonlocal nested_started
        calls.append(("first", context))
        if context is outer_context and not nested_started:
            nested_started = True
            dispatcher.dispatch(nested_context)

    def second_handler(context: RuntimeContext) -> None:
        calls.append(("second", context))

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)

    dispatcher.dispatch(outer_context)

    assert calls == [
        ("first", outer_context),
        ("first", nested_context),
        ("second", nested_context),
        ("second", outer_context),
    ]
    assert outer_context.event is not nested_context.event


def test_nested_dispatch_does_not_replace_or_mutate_outer_context() -> None:
    registry = RuntimeHandlerRegistry()
    outer_context = make_context()
    outer_event_state = outer_context.event.to_dict()
    observed_after_nested: list[RuntimeContext] = []

    def handler(context: RuntimeContext) -> None:
        if context is outer_context:
            dispatcher.dispatch(make_context("nested.event"))
            observed_after_nested.append(context)

    registry.register("test.event", handler)
    dispatcher = RuntimeDispatcher(registry)

    dispatcher.dispatch(outer_context)

    assert observed_after_nested == [outer_context]
    assert observed_after_nested[0] is outer_context
    assert outer_context.event.to_dict() == outer_event_state


def test_nested_dispatch_uses_independent_handler_snapshot() -> None:
    registry = RuntimeHandlerRegistry()
    calls: list[tuple[str, RuntimeContext]] = []
    outer_context = make_context()
    nested_context = make_context()
    registered = False

    def first_handler(context: RuntimeContext) -> None:
        nonlocal registered
        calls.append(("first", context))
        if context is outer_context and not registered:
            registry.register("test.event", third_handler)
            registered = True
            dispatcher.dispatch(nested_context)

    def second_handler(context: RuntimeContext) -> None:
        calls.append(("second", context))

    def third_handler(context: RuntimeContext) -> None:
        calls.append(("third", context))

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    dispatcher = RuntimeDispatcher(registry)

    dispatcher.dispatch(outer_context)

    assert calls == [
        ("first", outer_context),
        ("first", nested_context),
        ("second", nested_context),
        ("third", nested_context),
        ("second", outer_context),
    ]
