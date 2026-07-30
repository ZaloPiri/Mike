import uuid

import pytest
from fastapi.testclient import TestClient

from mike_app.handlers.message_perception import MessagePerceptionHandler
from mike_app.main import app
from mike_app.perception.model import PerceptionResult
from mike_app.perception.service import PerceptionService


client = TestClient(app)


class FakePerceptionClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.intent = "greeting"
        self.entities: dict[str, object] = {"explicit": "value"}

    def perceive(self, text: str) -> PerceptionResult:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return PerceptionResult(
            language="es",
            intent=self.intent,
            confidence=0.91,
            entities=self.entities,
        )


def unique_tenant(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def register_fake_perception() -> tuple[
    FakePerceptionClient,
    MessagePerceptionHandler,
]:
    fake = FakePerceptionClient()
    handler = MessagePerceptionHandler(
        app.state.episode_coordinator,
        PerceptionService(fake),
        app.state.runtime_dispatcher,
    )
    app.state.runtime_handler_registry.register(
        "message.accepted",
        handler,
    )
    return fake, handler


def unregister_fake_perception(
    handler: MessagePerceptionHandler,
) -> None:
    app.state.runtime_handler_registry.unregister(
        "message.accepted",
        handler,
    )


def test_missing_configuration_is_explicit_and_import_is_network_free() -> None:
    assert app.state.perception_enabled is False
    assert app.state.openai_sdk_client is None
    assert app.state.openai_perception_client is None
    assert app.state.perception_service is None
    assert app.state.message_perception_handler is None
    assert app.state.runtime_handler_registry.count_for_type(
        "message.received"
    ) == 1
    assert app.state.runtime_handler_registry.count_for_type(
        "message.accepted"
    ) == 0
    assert app.state.runtime_handler_registry.count_for_type(
        "message.perceived"
    ) == 1
    assert app.state.runtime_handler_registry.count_for_type(
        "perception.normalized"
    ) == 0
    assert app.state.perception_normalizer is not None
    assert app.state.perception_normalization_handler is not None


def test_successful_perception_preserves_response_and_stores_four_events() -> None:
    tenant_id = unique_tenant("perception-success")
    fake, handler = register_fake_perception()
    try:
        response = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "Hola"},
        )
    finally:
        unregister_fake_perception(handler)

    assert response.status_code == 201
    body = response.json()
    assert body["event_type"] == "message.received"
    assert body["tenant_id"] == tenant_id
    assert body["dispatched"] is True
    events = app.state.event_store.list_for_tenant(tenant_id)
    episodes = app.state.episode_store.list_for_tenant(tenant_id)
    assert fake.calls == ["Hola"]
    assert len(episodes) == 1
    assert [event.event_type for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
    ]
    assert episodes[0].event_ids == tuple(
        event.event_id for event in events
    )
    assert events[2].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "accepted_event_id": str(events[1].event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.91,
        "entities": {"explicit": "value"},
    }
    assert events[3].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "accepted_event_id": str(events[1].event_id),
        "perceived_event_id": str(events[2].event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.91,
        "entities": {},
    }


def test_repeated_requests_create_independent_perceived_episodes() -> None:
    tenant_id = unique_tenant("perception-repeat")
    fake, handler = register_fake_perception()
    try:
        first = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "First"},
        ).json()
        second = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "Second"},
        ).json()
    finally:
        unregister_fake_perception(handler)

    first_episode = app.state.episode_store.get_by_id(
        tenant_id,
        uuid.UUID(first["episode_id"]),
    )
    second_episode = app.state.episode_store.get_by_id(
        tenant_id,
        uuid.UUID(second["episode_id"]),
    )
    assert fake.calls == ["First", "Second"]
    assert first_episode is not None
    assert second_episode is not None
    assert len(first_episode.event_ids) == 4
    assert len(second_episode.event_ids) == 4
    assert set(first_episode.event_ids).isdisjoint(
        second_episode.event_ids
    )


def test_perception_remains_tenant_isolated() -> None:
    first_tenant = unique_tenant("perception-one")
    second_tenant = unique_tenant("perception-two")
    _, handler = register_fake_perception()
    try:
        client.post(
            "/dev/messages",
            json={"tenant_id": first_tenant, "text": "First"},
        )
        client.post(
            "/dev/messages",
            json={"tenant_id": second_tenant, "text": "Second"},
        )
    finally:
        unregister_fake_perception(handler)

    first_events = app.state.event_store.list_for_tenant(first_tenant)
    second_events = app.state.event_store.list_for_tenant(second_tenant)
    assert len(first_events) == 4
    assert len(second_events) == 4
    assert all(event.tenant_id == first_tenant for event in first_events)
    assert all(event.tenant_id == second_tenant for event in second_events)


def test_perception_failure_preserves_accepted_without_perceived() -> None:
    tenant_id = unique_tenant("perception-failure")
    fake, handler = register_fake_perception()
    error = RuntimeError("provider failed")
    fake.error = error
    try:
        with pytest.raises(RuntimeError, match="provider failed") as exc_info:
            client.post(
                "/dev/messages",
                json={"tenant_id": tenant_id, "text": "Hola"},
            )
    finally:
        unregister_fake_perception(handler)

    assert exc_info.value is error
    assert fake.calls == ["Hola"]
    assert [event.event_type for event in
            app.state.event_store.list_for_tenant(tenant_id)] == [
        "message.received",
        "message.accepted",
    ]
    assert len(
        app.state.episode_store.list_for_tenant(tenant_id)[0].event_ids
    ) == 2


def test_invalid_request_does_not_call_perception() -> None:
    tenant_id = unique_tenant("perception-invalid")
    fake, handler = register_fake_perception()
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()
    try:
        response = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "   "},
        )
    finally:
        unregister_fake_perception(handler)

    assert response.status_code == 422
    assert fake.calls == []
    assert app.state.event_store.total_count() == event_count
    assert app.state.episode_store.total_count() == episode_count


def test_normalization_failure_preserves_perceived_without_normalized() -> None:
    tenant_id = unique_tenant("normalization-failure")
    fake, handler = register_fake_perception()
    fake.entities = {
        "item": "sandwich",
        "product": "empanada",
    }
    try:
        with pytest.raises(ValueError, match="duplicate canonical"):
            client.post(
                "/dev/messages",
                json={"tenant_id": tenant_id, "text": "Hola"},
            )
    finally:
        unregister_fake_perception(handler)

    assert fake.calls == ["Hola"]
    assert [event.event_type for event in
            app.state.event_store.list_for_tenant(tenant_id)] == [
        "message.received",
        "message.accepted",
        "message.perceived",
    ]


def test_inspection_exposes_four_events_and_health_is_unchanged() -> None:
    tenant_id = unique_tenant("perception-inspection")
    _, handler = register_fake_perception()
    try:
        message = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "Hola"},
        ).json()
    finally:
        unregister_fake_perception(handler)

    events = client.get(
        f"/dev/tenants/{tenant_id}/events"
    ).json()
    detail = client.get(
        f"/dev/tenants/{tenant_id}/episodes/{message['episode_id']}"
    ).json()
    health = client.get("/health")
    assert [event["event_type"] for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
    ]
    assert [event["event_type"] for event in detail["events"]] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
    ]
    assert health.json() == {
        "status": "ok",
        "service": "mike",
        "version": "0.1.0",
    }
