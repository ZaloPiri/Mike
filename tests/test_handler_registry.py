import pytest

from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.event import Event
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry


class EqualCallable:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def __call__(self, context: RuntimeContext) -> None:
        self.calls += 1

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EqualCallable) and self.name == other.name


def test_registry_starts_empty() -> None:
    registry = RuntimeHandlerRegistry()

    assert registry.total_count() == 0
    assert registry.handlers_for_type("test.event") == ()
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    assert registry.handlers_for(RuntimeContext.create(event)) == ()


def test_register_one_handler() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event", handler)

    assert registry.handlers_for_type("test.event") == (handler,)
    assert registry.count_for_type("test.event") == 1
    assert registry.total_count() == 1


def test_register_multiple_handlers_for_same_event_type() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)

    assert registry.handlers_for_type("test.event") == (first_handler, second_handler)
    assert registry.count_for_type("test.event") == 2
    assert registry.total_count() == 2


def test_registration_order_is_preserved() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None
    third_handler = lambda: None

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    registry.register("test.event", third_handler)

    assert registry.handlers_for_type("test.event") == (first_handler, second_handler, third_handler)


def test_one_handler_can_be_registered_for_different_event_types() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event.one", handler)
    registry.register("test.event.two", handler)

    assert registry.handlers_for_type("test.event.one") == (handler,)
    assert registry.handlers_for_type("test.event.two") == (handler,)
    assert registry.total_count() == 2


def test_exact_event_type_lookup_only() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event", handler)

    assert registry.handlers_for_type("test.event") == (handler,)
    assert registry.handlers_for_type("other.event") == ()


def test_unknown_event_type_returns_empty_tuple() -> None:
    registry = RuntimeHandlerRegistry()

    assert registry.handlers_for_type("unknown.event") == ()


def test_handlers_for_accepts_runtime_context_and_uses_its_event_type() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    registry.register("test.event", handler)

    assert registry.handlers_for(context) == (handler,)


def test_handlers_for_rejects_bare_event() -> None:
    registry = RuntimeHandlerRegistry()
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    with pytest.raises(TypeError, match="RuntimeContext"):
        registry.handlers_for(event)


def test_handlers_for_rejects_none() -> None:
    registry = RuntimeHandlerRegistry()

    with pytest.raises(TypeError, match="RuntimeContext"):
        registry.handlers_for(None)


def test_empty_event_type_is_rejected() -> None:
    registry = RuntimeHandlerRegistry()

    with pytest.raises(ValueError, match="non-empty"):
        registry.register("", lambda: None)


def test_whitespace_only_event_type_is_rejected() -> None:
    registry = RuntimeHandlerRegistry()

    with pytest.raises(ValueError, match="non-empty"):
        registry.register("   ", lambda: None)


def test_non_string_event_type_is_rejected() -> None:
    registry = RuntimeHandlerRegistry()

    with pytest.raises(TypeError, match="string"):
        registry.register(object(), lambda: None)


def test_non_callable_handler_registration_is_rejected() -> None:
    registry = RuntimeHandlerRegistry()

    with pytest.raises(TypeError, match="callable"):
        registry.register("test.event", object())


def test_duplicate_handler_for_same_event_type_is_rejected() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event", handler)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("test.event", handler)


def test_distinct_handlers_for_one_event_type_are_accepted() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)

    assert registry.handlers_for_type("test.event") == (first_handler, second_handler)


def test_returned_tuples_cannot_mutate_registry_state() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None
    registry.register("test.event", handler)

    result = registry.handlers_for_type("test.event")
    result = result + (lambda: None,)

    assert registry.handlers_for_type("test.event") == (handler,)


def test_unregister_removes_exact_handler() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)

    registry.unregister("test.event", first_handler)

    assert registry.handlers_for_type("test.event") == (second_handler,)
    assert registry.count_for_type("test.event") == 1


def test_unregister_preserves_remaining_order() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None
    third_handler = lambda: None

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)
    registry.register("test.event", third_handler)

    registry.unregister("test.event", second_handler)

    assert registry.handlers_for_type("test.event") == (first_handler, third_handler)


def test_unregister_unknown_registration_raises_value_error() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event", handler)

    with pytest.raises(ValueError, match="not registered"):
        registry.unregister("test.event", lambda: None)


def test_unregister_rejects_non_callable_handler() -> None:
    registry = RuntimeHandlerRegistry()

    with pytest.raises(TypeError, match="callable"):
        registry.unregister("test.event", object())


def test_unregistering_from_one_event_type_does_not_affect_another() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event.one", handler)
    registry.register("test.event.two", handler)

    registry.unregister("test.event.one", handler)

    assert registry.handlers_for_type("test.event.one") == ()
    assert registry.handlers_for_type("test.event.two") == (handler,)


def test_empty_internal_event_type_entries_are_removed() -> None:
    registry = RuntimeHandlerRegistry()
    handler = lambda: None

    registry.register("test.event", handler)
    registry.unregister("test.event", handler)

    assert registry.handlers_for_type("test.event") == ()
    assert registry.count_for_type("test.event") == 0
    assert registry.total_count() == 0


def test_count_for_type_is_correct() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)

    assert registry.count_for_type("test.event") == 2
    assert registry.count_for_type("other.event") == 0


def test_total_count_counts_registrations() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = lambda: None
    second_handler = lambda: None
    third_handler = lambda: None

    registry.register("test.event.one", first_handler)
    registry.register("test.event.one", second_handler)
    registry.register("test.event.two", third_handler)

    assert registry.total_count() == 3


def test_lookup_does_not_execute_handlers() -> None:
    registry = RuntimeHandlerRegistry()
    handler = EqualCallable("handler")
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    context = RuntimeContext.create(event)

    registry.register("test.event", handler)

    assert registry.handlers_for(context) == (handler,)
    assert handler.calls == 0


def test_callables_compare_equal_but_identity_is_used() -> None:
    registry = RuntimeHandlerRegistry()
    first_handler = EqualCallable("same")
    second_handler = EqualCallable("same")

    registry.register("test.event", first_handler)
    registry.register("test.event", second_handler)

    assert registry.handlers_for_type("test.event") == (first_handler, second_handler)
    assert registry.count_for_type("test.event") == 2
