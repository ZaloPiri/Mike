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
        self.language = "es"
        self.intent = "greeting"
        self.entities: dict[str, object] = {"explicit": "value"}

    def perceive(self, text: str) -> PerceptionResult:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return PerceptionResult(
            language=self.language,
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
    ) == 1
    assert app.state.runtime_handler_registry.count_for_type(
        "conversation.next_action"
    ) == 1
    assert app.state.runtime_handler_registry.count_for_type(
        "conversation.response_request"
    ) == 1
    assert app.state.runtime_handler_registry.count_for_type(
        "conversation.response_generated"
    ) == 1
    assert app.state.perception_normalizer is not None
    assert app.state.perception_normalization_handler is not None
    assert app.state.conversation_action_planner is not None
    assert app.state.conversation_next_action_handler is not None
    assert (
        app.state.conversation_next_action_handler
        ._conversation_action_planner
        is app.state.conversation_action_planner
    )
    assert app.state.response_request_planner is not None
    assert app.state.conversation_response_request_handler is not None
    assert (
        app.state.conversation_response_request_handler
        ._response_request_planner
        is app.state.response_request_planner
    )
    assert app.state.deterministic_response_generator is not None
    assert app.state.conversation_response_generated_handler is not None
    assert (
        app.state.conversation_response_generated_handler
        ._response_generator
        is app.state.deterministic_response_generator
    )
    assert app.state.conversation_response_validator is not None
    assert app.state.conversation_response_validated_handler is not None
    assert (
        app.state.conversation_response_validated_handler
        ._response_validator
        is app.state.conversation_response_validator
    )
    assert app.state.runtime_handler_registry.count_for_type(
        "conversation.response_validated"
    ) == 1
    assert app.state.conversation_response_target_resolver is not None
    assert app.state.conversation_response_target_resolved_handler is not None
    assert app.state.runtime_handler_registry.count_for_type(
        "communication.response_target_resolved"
    ) == 0


def test_successful_perception_preserves_response_and_stores_nine_events() -> None:
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
        "conversation.next_action",
        "conversation.response_request",
        "conversation.response_generated",
        "conversation.response_validated",
        "communication.response_target_resolved",
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
    assert events[4].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "accepted_event_id": str(events[1].event_id),
        "perceived_event_id": str(events[2].event_id),
        "normalized_event_id": str(events[3].event_id),
        "action": "respond",
        "reason": "intent_understood",
        "can_continue": True,
        "missing_entities": [],
    }
    assert events[5].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "accepted_event_id": str(events[1].event_id),
        "perceived_event_id": str(events[2].event_id),
        "normalized_event_id": str(events[3].event_id),
        "next_action_event_id": str(events[4].event_id),
        "response_type": "intent_response",
        "target_language": "es",
        "intent": "greeting",
        "requested_entities": [],
        "handoff_reason": None,
    }
    assert events[6].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "accepted_event_id": str(events[1].event_id),
        "perceived_event_id": str(events[2].event_id),
        "normalized_event_id": str(events[3].event_id),
        "next_action_event_id": str(events[4].event_id),
        "response_request_event_id": str(events[5].event_id),
        "response_type": "intent_response",
        "language": "es",
        "text": "¡Hola! ¿En qué puedo ayudarte?",
        "generation_method": "deterministic_template",
    }
    assert events[7].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "accepted_event_id": str(events[1].event_id),
        "perceived_event_id": str(events[2].event_id),
        "normalized_event_id": str(events[3].event_id),
        "next_action_event_id": str(events[4].event_id),
        "response_request_event_id": str(events[5].event_id),
        "response_generated_event_id": str(events[6].event_id),
        "response_type": "intent_response",
        "language": "es",
        "text": "¡Hola! ¿En qué puedo ayudarte?",
        "generation_method": "deterministic_template",
        "validation_method": "deterministic_contract",
    }
    source_payload = events[0].to_dict()["payload"]
    assert events[8].to_dict()["payload"] == {
        "source_event_id": str(events[0].event_id),
        "response_validated_event_id": str(events[7].event_id),
        "channel": "development",
        "external_message_id": source_payload["external_message_id"],
        "external_conversation_id": (
            source_payload["external_conversation_id"]
        ),
        "outbound_sender_id": tenant_id,
        "outbound_recipient_id": "development-user",
        "resolution_method": "reply_to_source",
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
    assert len(first_episode.event_ids) == 9
    assert len(second_episode.event_ids) == 9
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
    assert len(first_events) == 9
    assert len(second_events) == 9
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


def test_invalid_request_does_not_call_perception_or_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = unique_tenant("perception-invalid")
    fake, handler = register_fake_perception()
    event_count = app.state.event_store.total_count()
    episode_count = app.state.episode_store.total_count()
    planner_calls: list[dict[str, object]] = []
    response_planner_calls: list[dict[str, object]] = []
    generator_calls: list[dict[str, object]] = []
    original_plan = app.state.conversation_action_planner.plan
    original_response_plan = app.state.response_request_planner.plan
    original_generate = app.state.deterministic_response_generator.generate

    def record_plan(**kwargs: object):
        planner_calls.append(kwargs)
        return original_plan(**kwargs)

    def record_response_plan(**kwargs: object):
        response_planner_calls.append(kwargs)
        return original_response_plan(**kwargs)

    def record_generate(**kwargs: object):
        generator_calls.append(kwargs)
        return original_generate(**kwargs)

    monkeypatch.setattr(
        app.state.conversation_action_planner,
        "plan",
        record_plan,
    )
    monkeypatch.setattr(
        app.state.response_request_planner,
        "plan",
        record_response_plan,
    )
    monkeypatch.setattr(
        app.state.deterministic_response_generator,
        "generate",
        record_generate,
    )
    try:
        response = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "   "},
        )
    finally:
        unregister_fake_perception(handler)

    assert response.status_code == 422
    assert fake.calls == []
    assert planner_calls == []
    assert response_planner_calls == []
    assert generator_calls == []
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


def test_inspection_exposes_nine_events_and_health_is_unchanged() -> None:
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
        "conversation.next_action",
        "conversation.response_request",
        "conversation.response_generated",
        "conversation.response_validated",
        "communication.response_target_resolved",
    ]
    assert [event["event_type"] for event in detail["events"]] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
        "conversation.response_request",
        "conversation.response_generated",
        "conversation.response_validated",
        "communication.response_target_resolved",
    ]
    assert health.json() == {
        "status": "ok",
        "service": "mike",
        "version": "0.1.0",
    }


@pytest.mark.parametrize(
    (
        "intent",
        "entities",
        "action",
        "response_type",
        "handoff_reason",
        "requested",
        "expected_text",
    ),
    [
        (
            "greeting",
            {},
            "respond",
            "intent_response",
            None,
            [],
            "¡Hola! ¿En qué puedo ayudarte?",
        ),
        (
            "product_inquiry",
            {},
            "respond",
            "intent_response",
            None,
            [],
            "Para ayudarte con los productos necesito consultar la "
            "información del comercio.",
        ),
        (
            "price_inquiry",
            {},
            "respond",
            "intent_response",
            None,
            [],
            "Para informarte el precio necesito consultar la información "
            "del comercio.",
        ),
        (
            "availability_inquiry",
            {},
            "respond",
            "intent_response",
            None,
            [],
            "Para confirmarte la disponibilidad necesito consultar la "
            "información del comercio.",
        ),
        (
            "place_order",
            {"product": "sandwich", "quantity": 2},
            "respond",
            "intent_response",
            None,
            [],
            "Entendí que querés realizar un pedido. Antes de confirmarlo "
            "necesito consultar la información del comercio.",
        ),
        (
            "place_order",
            {"quantity": 2},
            "request_missing_information",
            "missing_information",
            None,
            ["product"],
            "¿Qué producto necesitás?",
        ),
        (
            "place_order",
            {"product": "sandwich"},
            "request_missing_information",
            "missing_information",
            None,
            ["quantity"],
            "¿Qué cantidad necesitás?",
        ),
        (
            "place_order",
            {},
            "request_missing_information",
            "missing_information",
            None,
            ["product", "quantity"],
            "¿Qué producto y qué cantidad necesitás?",
        ),
        (
            "complaint",
            {},
            "handoff_human",
            "human_handoff",
            "complaint_requires_human",
            [],
            "Lamento lo ocurrido. Voy a derivarte con una persona para "
            "que pueda ayudarte.",
        ),
        (
            "human_assistance",
            {},
            "handoff_human",
            "human_handoff",
            "human_requested",
            [],
            "Voy a derivarte con una persona para que pueda ayudarte.",
        ),
        (
            "unknown",
            {},
            "request_clarification",
            "clarification",
            None,
            [],
            "No terminé de entender tu mensaje. ¿Podés reformularlo?",
        ),
    ],
)
def test_generated_response_policy_through_api(
    intent: str,
    entities: dict[str, object],
    action: str,
    response_type: str,
    handoff_reason: str | None,
    requested: list[str],
    expected_text: str,
) -> None:
    tenant_id = unique_tenant(f"generated-{intent}")
    fake, handler = register_fake_perception()
    fake.intent = intent
    fake.entities = entities
    try:
        response = client.post(
            "/dev/messages",
            json={"tenant_id": tenant_id, "text": "Test"},
        )
    finally:
        unregister_fake_perception(handler)

    assert response.status_code == 201
    events = app.state.event_store.list_for_tenant(tenant_id)
    next_action_payload = events[-5].to_dict()["payload"]
    response_payload = events[-4].to_dict()["payload"]
    generated_payload = events[-3].to_dict()["payload"]
    validated_payload = events[-2].to_dict()["payload"]
    target_payload = events[-1].to_dict()["payload"]
    assert next_action_payload["action"] == action
    assert response_payload["response_type"] == response_type
    assert response_payload["target_language"] == "es"
    assert response_payload["intent"] == intent
    assert response_payload["handoff_reason"] == handoff_reason
    assert response_payload["requested_entities"] == requested
    assert generated_payload["response_type"] == response_type
    assert generated_payload["language"] == "es"
    assert generated_payload["text"] == expected_text
    assert (
        generated_payload["generation_method"]
        == "deterministic_template"
    )
    assert validated_payload["response_type"] == response_type
    assert validated_payload["language"] == "es"
    assert validated_payload["text"] == expected_text
    assert validated_payload["validation_method"] == (
        "deterministic_contract"
    )
    assert target_payload["resolution_method"] == "reply_to_source"


def test_planning_failure_preserves_first_four_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = unique_tenant("planning-failure")
    fake, handler = register_fake_perception()
    calls = 0
    error = RuntimeError("planning failed")

    def fail_plan(**kwargs: object):
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(
        app.state.conversation_action_planner,
        "plan",
        fail_plan,
    )
    try:
        with pytest.raises(RuntimeError, match="planning failed") as exc_info:
            client.post(
                "/dev/messages",
                json={"tenant_id": tenant_id, "text": "Hola"},
            )
    finally:
        unregister_fake_perception(handler)

    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in
            app.state.event_store.list_for_tenant(tenant_id)] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
    ]


def test_response_request_planning_failure_preserves_first_five_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = unique_tenant("response-planning-failure")
    fake, handler = register_fake_perception()
    calls = 0
    error = RuntimeError("response planning failed")

    def fail_plan(**kwargs: object):
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(
        app.state.response_request_planner,
        "plan",
        fail_plan,
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="response planning failed",
        ) as exc_info:
            client.post(
                "/dev/messages",
                json={"tenant_id": tenant_id, "text": "Hola"},
            )
    finally:
        unregister_fake_perception(handler)

    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in
            app.state.event_store.list_for_tenant(tenant_id)] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
    ]


def test_generation_failure_preserves_first_six_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = unique_tenant("generation-failure")
    fake, handler = register_fake_perception()
    calls = 0
    error = RuntimeError("generation failed")

    def fail_generate(**kwargs: object):
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr(
        app.state.deterministic_response_generator,
        "generate",
        fail_generate,
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="generation failed",
        ) as exc_info:
            client.post(
                "/dev/messages",
                json={"tenant_id": tenant_id, "text": "Hola"},
            )
    finally:
        unregister_fake_perception(handler)

    assert exc_info.value is error
    assert calls == 1
    assert [event.event_type for event in
            app.state.event_store.list_for_tenant(tenant_id)] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "perception.normalized",
        "conversation.next_action",
        "conversation.response_request",
    ]
