import uuid

import pytest

from mike_app.runtime.context import RuntimeContext


app = None
client = None


@pytest.fixture(scope="module", autouse=True)
def bind_memory_app(memory_app, memory_client):
    global app, client
    app = memory_app
    client = memory_client
    yield


def post_message(
    tenant_id: object = "la-sandwicheria",
    text: object = "Hola, quiero pedir dos docenas",
):
    return client.post(
        "/dev/messages",
        json={"tenant_id": tenant_id, "text": text},
    )


def test_post_dev_messages_returns_required_success_response() -> None:
    response = post_message()

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["event_id"])
    assert uuid.UUID(body["episode_id"])
    assert body == {
        "event_id": body["event_id"],
        "episode_id": body["episode_id"],
        "event_type": "message.received",
        "tenant_id": "la-sandwicheria",
        "dispatched": True,
    }


def test_valid_text_is_preserved_without_inferred_behavior() -> None:
    text = "  Hola, quiero pedir dos docenas  "

    response = post_message(tenant_id="tenant-preserve", text=text)

    assert response.status_code == 201
    event_id = uuid.UUID(response.json()["event_id"])
    stored_event = app.state.event_store.get_by_id("tenant-preserve", event_id)
    assert stored_event is not None
    payload = stored_event.to_dict()["payload"]
    assert payload["text"] == text
    assert payload["channel"] == "development"
    assert uuid.UUID(payload["external_message_id"])
    assert uuid.UUID(payload["external_conversation_id"])
    assert payload["sender_id"] == "development-user"
    assert payload["recipient_id"] == "tenant-preserve"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", ""),
        ("tenant_id", "   "),
        ("tenant_id", 123),
        ("text", ""),
        ("text", "   "),
        ("text", 123),
    ],
)
def test_invalid_field_values_are_rejected_without_persistence(
    field: str,
    value: object,
) -> None:
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()
    payload = {
        "tenant_id": "tenant-validation",
        "text": "valid text",
    }
    payload[field] = value

    response = client.post("/dev/messages", json=payload)

    assert response.status_code == 422
    assert app.state.event_store.total_count() == event_count
    assert app.state.episode_store.total_count() == episode_count


@pytest.mark.parametrize("missing_field", ["tenant_id", "text"])
def test_missing_fields_are_rejected_without_persistence(
    missing_field: str,
) -> None:
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()
    payload = {
        "tenant_id": "tenant-missing",
        "text": "valid text",
    }
    payload.pop(missing_field)

    response = client.post("/dev/messages", json=payload)

    assert response.status_code == 422
    assert app.state.event_store.total_count() == event_count
    assert app.state.episode_store.total_count() == episode_count


def test_one_request_stores_received_and_accepted_events_in_one_episode() -> None:
    tenant_id = "tenant-storage"
    event_count = app.state.event_store.count_for_tenant(tenant_id)
    episode_count = app.state.episode_store.count_for_tenant(tenant_id)

    response = post_message(tenant_id=tenant_id, text="Only this text")

    body = response.json()
    event_id = uuid.UUID(body["event_id"])
    episode_id = uuid.UUID(body["episode_id"])
    stored_events = app.state.event_store.list_for_tenant(tenant_id)
    stored_episode = app.state.episode_store.get_by_id(tenant_id, episode_id)
    new_events = stored_events[event_count:]
    assert app.state.event_store.count_for_tenant(tenant_id) == event_count + 2
    assert app.state.episode_store.count_for_tenant(tenant_id) == episode_count + 1
    assert len(new_events) == 2
    assert new_events[0].event_id == event_id
    assert new_events[0].tenant_id == tenant_id
    assert new_events[0].event_type == "message.received"
    source_payload = new_events[0].to_dict()["payload"]
    assert source_payload == {
        "text": "Only this text",
        "channel": "development",
        "external_message_id": source_payload["external_message_id"],
        "external_conversation_id": (
            source_payload["external_conversation_id"]
        ),
        "sender_id": "development-user",
        "recipient_id": tenant_id,
    }
    assert uuid.UUID(source_payload["external_message_id"])
    assert uuid.UUID(source_payload["external_conversation_id"])
    assert new_events[1].tenant_id == tenant_id
    assert new_events[1].event_type == "message.accepted"
    assert new_events[1].to_dict()["payload"] == {
        "source_event_id": str(event_id),
    }
    assert stored_episode is not None
    assert stored_episode.event_ids == (
        new_events[0].event_id,
        new_events[1].event_id,
    )


def test_repeated_requests_create_distinct_events_and_episodes() -> None:
    first = post_message(tenant_id="tenant-repeated").json()
    second = post_message(tenant_id="tenant-repeated").json()

    assert first["event_id"] != second["event_id"]
    assert first["episode_id"] != second["episode_id"]
    first_episode = app.state.episode_store.get_by_id(
        "tenant-repeated",
        uuid.UUID(first["episode_id"]),
    )
    second_episode = app.state.episode_store.get_by_id(
        "tenant-repeated",
        uuid.UUID(second["episode_id"]),
    )
    assert first_episode is not None
    assert second_episode is not None
    assert len(first_episode.event_ids) == 2
    assert len(second_episode.event_ids) == 2
    assert set(first_episode.event_ids).isdisjoint(second_episode.event_ids)
    first_source = app.state.event_store.get_by_id(
        "tenant-repeated",
        uuid.UUID(first["event_id"]),
    )
    second_source = app.state.event_store.get_by_id(
        "tenant-repeated",
        uuid.UUID(second["event_id"]),
    )
    assert first_source is not None
    assert second_source is not None
    assert (
        first_source.payload["external_message_id"]
        != second_source.payload["external_message_id"]
    )
    assert (
        first_source.payload["external_conversation_id"]
        != second_source.payload["external_conversation_id"]
    )


def test_requests_from_different_tenants_remain_isolated() -> None:
    first = post_message(tenant_id="tenant-isolated-one").json()
    second = post_message(tenant_id="tenant-isolated-two").json()

    first_event_id = uuid.UUID(first["event_id"])
    second_event_id = uuid.UUID(second["event_id"])
    assert app.state.event_store.get_by_id("tenant-isolated-one", first_event_id) is not None
    assert app.state.event_store.get_by_id("tenant-isolated-one", second_event_id) is None
    assert app.state.event_store.get_by_id("tenant-isolated-two", first_event_id) is None
    assert app.state.event_store.get_by_id("tenant-isolated-two", second_event_id) is not None


def test_registered_handler_receives_context_with_response_event_once() -> None:
    seen: list[RuntimeContext] = []

    def handler(context: RuntimeContext) -> None:
        seen.append(context)

    app.state.runtime_handler_registry.register("message.received", handler)
    try:
        response = post_message(tenant_id="tenant-handler")
    finally:
        app.state.runtime_handler_registry.unregister("message.received", handler)

    assert response.status_code == 201
    assert len(seen) == 1
    event_id = uuid.UUID(response.json()["event_id"])
    stored_event = app.state.event_store.get_by_id("tenant-handler", event_id)
    assert seen[0].event is stored_event


def test_multiple_handlers_execute_in_registration_order() -> None:
    calls: list[str] = []

    def first_handler(context: RuntimeContext) -> None:
        calls.append("first")

    def second_handler(context: RuntimeContext) -> None:
        calls.append("second")

    registry = app.state.runtime_handler_registry
    registry.register("message.received", first_handler)
    registry.register("message.received", second_handler)
    try:
        response = post_message(tenant_id="tenant-order")
    finally:
        registry.unregister("message.received", first_handler)
        registry.unregister("message.received", second_handler)

    assert response.status_code == 201
    assert calls == ["first", "second"]


def test_dispatch_failure_propagates_and_keeps_event_and_episode() -> None:
    tenant_id = "tenant-failure"
    event_count = app.state.event_store.count_for_tenant(tenant_id)
    episode_count = app.state.episode_store.count_for_tenant(tenant_id)
    error = RuntimeError("dispatch failed")

    def failing_handler(context: RuntimeContext) -> None:
        raise error

    registry = app.state.runtime_handler_registry
    registry.register("message.received", failing_handler)
    try:
        with pytest.raises(RuntimeError, match="dispatch failed") as exc_info:
            post_message(tenant_id=tenant_id)
    finally:
        registry.unregister("message.received", failing_handler)

    assert exc_info.value is error
    assert app.state.event_store.count_for_tenant(tenant_id) == event_count + 2
    assert app.state.episode_store.count_for_tenant(tenant_id) == episode_count + 1


def test_health_behavior_remains_unchanged() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mike",
        "version": "0.1.0",
    }
