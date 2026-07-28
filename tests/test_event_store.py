import uuid

import pytest

from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore


def test_append_and_retrieve_by_id() -> None:
    store = InMemoryEventStore()
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    store.append(event)

    assert store.get_by_id("tenant-1", event.event_id) is event


def test_list_for_tenant_preserves_insertion_order() -> None:
    store = InMemoryEventStore()
    first = Event.create(tenant_id="tenant-1", event_type="test.event.a")
    second = Event.create(tenant_id="tenant-1", event_type="test.event.b")

    store.append(first)
    store.append(second)

    assert store.list_for_tenant("tenant-1") == (first, second)


def test_tenant_isolation_by_id() -> None:
    store = InMemoryEventStore()
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    store.append(event)

    assert store.get_by_id("tenant-2", event.event_id) is None


def test_tenant_isolation_in_listing() -> None:
    store = InMemoryEventStore()
    tenant_one_event = Event.create(tenant_id="tenant-1", event_type="test.event")
    tenant_two_event = Event.create(tenant_id="tenant-2", event_type="test.event")

    store.append(tenant_one_event)
    store.append(tenant_two_event)

    assert store.list_for_tenant("tenant-1") == (tenant_one_event,)
    assert store.list_for_tenant("tenant-2") == (tenant_two_event,)


def test_filter_by_event_type() -> None:
    store = InMemoryEventStore()
    first = Event.create(tenant_id="tenant-1", event_type="alpha")
    second = Event.create(tenant_id="tenant-1", event_type="beta")

    store.append(first)
    store.append(second)

    assert store.list_for_tenant("tenant-1", event_type="alpha") == (first,)


def test_tenant_count_and_total_count() -> None:
    store = InMemoryEventStore()
    first = Event.create(tenant_id="tenant-1", event_type="test.event")
    second = Event.create(tenant_id="tenant-1", event_type="test.event")
    third = Event.create(tenant_id="tenant-2", event_type="test.event")

    store.append(first)
    store.append(second)
    store.append(third)

    assert store.count_for_tenant("tenant-1") == 2
    assert store.count_for_tenant("tenant-2") == 1
    assert store.total_count() == 3


def test_duplicate_event_id_rejected() -> None:
    store = InMemoryEventStore()
    event = Event.create(tenant_id="tenant-1", event_type="test.event")

    store.append(event)

    with pytest.raises(ValueError, match="duplicate event_id"):
        store.append(event)


def test_non_event_append_rejected() -> None:
    store = InMemoryEventStore()

    with pytest.raises(TypeError, match="Event"):
        store.append(object())


def test_empty_tenant_id_rejected_for_retrieval() -> None:
    store = InMemoryEventStore()

    with pytest.raises(ValueError, match="tenant_id"):
        store.get_by_id("", uuid.uuid4())


def test_whitespace_only_tenant_id_rejected_for_retrieval() -> None:
    store = InMemoryEventStore()

    with pytest.raises(ValueError, match="tenant_id"):
        store.list_for_tenant("   ")


def test_empty_event_type_filter_rejected() -> None:
    store = InMemoryEventStore()

    with pytest.raises(ValueError, match="event_type"):
        store.list_for_tenant("tenant-1", event_type="")


def test_whitespace_only_event_type_filter_rejected() -> None:
    store = InMemoryEventStore()

    with pytest.raises(ValueError, match="event_type"):
        store.list_for_tenant("tenant-1", event_type="   ")


def test_returned_collection_cannot_mutate_store_state() -> None:
    store = InMemoryEventStore()
    event = Event.create(tenant_id="tenant-1", event_type="test.event")
    store.append(event)

    result = store.list_for_tenant("tenant-1")

    assert isinstance(result, tuple)
    with pytest.raises(AttributeError):
        result.append(Event.create(tenant_id="tenant-1", event_type="test.event"))


def test_unknown_event_returns_none() -> None:
    store = InMemoryEventStore()

    assert store.get_by_id("tenant-1", uuid.uuid4()) is None


def test_empty_tenant_returns_empty_tuple() -> None:
    store = InMemoryEventStore()

    assert store.list_for_tenant("tenant-9") == ()
