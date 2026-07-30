import uuid

import pytest

from mike_app.handlers.message_perception import MessagePerceptionHandler
from mike_app.perception.model import PerceptionResult
from mike_app.perception.service import PerceptionService
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore


class FakePerceptionClient:
    def __init__(self) -> None:
        self.result = PerceptionResult(
            language="es",
            intent="greeting",
            confidence=0.9,
            entities={"name": "Ana"},
        )
        self.calls: list[str] = []
        self.error: Exception | None = None

    def perceive(self, text: str) -> PerceptionResult:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.result


def make_components() -> tuple[
    InMemoryEventStore,
    InMemoryEpisodeStore,
    EpisodeCoordinator,
    FakePerceptionClient,
    MessagePerceptionHandler,
]:
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    client = FakePerceptionClient()
    service = PerceptionService(client)
    handler = MessagePerceptionHandler(coordinator, service)
    return event_store, episode_store, coordinator, client, handler


def append_accepted(
    coordinator: EpisodeCoordinator,
    source_event: Event,
    source_event_id: str | None = None,
) -> tuple[object, Event]:
    episode = coordinator.start_episode(source_event)
    accepted_event = Event.create(
        tenant_id=source_event.tenant_id,
        event_type="message.accepted",
        payload={
            "source_event_id": (
                source_event_id
                if source_event_id is not None
                else str(source_event.event_id)
            )
        },
    )
    coordinator.append_to_episode(episode.episode_id, accepted_event)
    return episode, accepted_event


def test_constructor_accepts_dependencies_and_handler_is_callable() -> None:
    _, _, coordinator, client, _ = make_components()
    service = PerceptionService(client)

    handler = MessagePerceptionHandler(coordinator, service)

    assert handler._episode_coordinator is coordinator
    assert handler._perception_service is service
    assert callable(handler)


@pytest.mark.parametrize("invalid_coordinator", [None, object()])
def test_constructor_rejects_invalid_coordinator(
    invalid_coordinator: object,
) -> None:
    client = FakePerceptionClient()

    with pytest.raises(TypeError, match="EpisodeCoordinator"):
        MessagePerceptionHandler(
            invalid_coordinator,
            PerceptionService(client),
        )


@pytest.mark.parametrize("invalid_service", [None, object()])
def test_constructor_rejects_invalid_service(
    invalid_service: object,
) -> None:
    coordinator = EpisodeCoordinator(
        InMemoryEventStore(),
        InMemoryEpisodeStore(),
    )

    with pytest.raises(TypeError, match="PerceptionService"):
        MessagePerceptionHandler(coordinator, invalid_service)


@pytest.mark.parametrize("invalid_context", [None, object()])
def test_rejects_invalid_context(invalid_context: object) -> None:
    _, _, _, _, handler = make_components()

    with pytest.raises(TypeError, match="RuntimeContext"):
        handler(invalid_context)


def test_rejects_wrong_event_type() -> None:
    _, _, _, _, handler = make_components()
    event = Event.create(
        tenant_id="tenant-1",
        event_type="message.accepted.related",
    )

    with pytest.raises(ValueError, match="message.accepted"):
        handler(RuntimeContext.create(event))


def test_unknown_accepted_episode_is_rejected_before_perception() -> None:
    event_store, _, _, client, handler = make_components()
    accepted = Event.create(
        tenant_id="tenant-1",
        event_type="message.accepted",
        payload={"source_event_id": str(uuid.uuid4())},
    )

    with pytest.raises(ValueError, match="Episode"):
        handler(RuntimeContext.create(accepted))

    assert client.calls == []
    assert event_store.total_count() == 0


@pytest.mark.parametrize(
    "source_event_id",
    [None, 123, "", "not-a-uuid"],
)
def test_malformed_source_event_id_is_rejected(
    source_event_id: object,
) -> None:
    _, _, coordinator, client, handler = make_components()
    source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": "Hola"},
    )
    episode = coordinator.start_episode(source)
    accepted = Event.create(
        tenant_id="tenant-1",
        event_type="message.accepted",
        payload={"source_event_id": source_event_id},
    )
    coordinator.append_to_episode(episode.episode_id, accepted)

    with pytest.raises(ValueError, match="source_event_id"):
        handler(RuntimeContext.create(accepted))

    assert client.calls == []


def test_cross_tenant_source_is_not_resolved() -> None:
    _, _, coordinator, client, handler = make_components()
    other_tenant_source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": "Hola"},
    )
    coordinator.start_episode(other_tenant_source)
    accepted_source = Event.create(
        tenant_id="tenant-2",
        event_type="message.received",
        payload={"text": "placeholder"},
    )
    episode = coordinator.start_episode(accepted_source)
    accepted = Event.create(
        tenant_id="tenant-2",
        event_type="message.accepted",
        payload={"source_event_id": str(other_tenant_source.event_id)},
    )
    coordinator.append_to_episode(episode.episode_id, accepted)

    with pytest.raises(ValueError, match="accepted Episode"):
        handler(RuntimeContext.create(accepted))

    assert client.calls == []


def test_source_event_must_be_message_received() -> None:
    _, _, coordinator, client, handler = make_components()
    source = Event.create(
        tenant_id="tenant-1",
        event_type="other.event",
        payload={"text": "Hola"},
    )
    _, accepted = append_accepted(coordinator, source)

    with pytest.raises(ValueError, match="message.received"):
        handler(RuntimeContext.create(accepted))

    assert client.calls == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"text": ""}, {"text": "   "}, {"text": 123}],
)
def test_source_text_must_be_non_empty_string(
    payload: object,
) -> None:
    _, _, coordinator, client, handler = make_components()
    source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload=payload,
    )
    _, accepted = append_accepted(coordinator, source)

    with pytest.raises(ValueError, match="text"):
        handler(RuntimeContext.create(accepted))

    assert client.calls == []


def test_creates_exact_perceived_event_in_same_episode() -> None:
    event_store, episode_store, coordinator, client, handler = (
        make_components()
    )
    text = "  Hola Ana  "
    source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": text},
    )
    episode, accepted = append_accepted(coordinator, source)

    result = handler(RuntimeContext.create(accepted))

    events = event_store.list_for_tenant("tenant-1")
    updated_episode = episode_store.get_by_id(
        "tenant-1",
        episode.episode_id,
    )
    perceived = events[2]
    assert result is None
    assert client.calls == [text]
    assert [event.event_type for event in events] == [
        "message.received",
        "message.accepted",
        "message.perceived",
    ]
    assert perceived.to_dict()["payload"] == {
        "source_event_id": str(source.event_id),
        "accepted_event_id": str(accepted.event_id),
        "language": "es",
        "intent": "greeting",
        "confidence": 0.9,
        "entities": {"name": "Ana"},
    }
    assert "text" not in perceived.payload
    assert "model" not in perceived.payload
    assert "raw_response" not in perceived.payload
    assert updated_episode is not None
    assert updated_episode.episode_id == episode.episode_id
    assert updated_episode.event_ids == tuple(
        event.event_id for event in events
    )


def test_service_exception_adds_no_perceived_event() -> None:
    event_store, _, coordinator, client, handler = make_components()
    source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": "Hola"},
    )
    _, accepted = append_accepted(coordinator, source)
    error = RuntimeError("provider failed")
    client.error = error

    with pytest.raises(RuntimeError, match="provider failed") as exc_info:
        handler(RuntimeContext.create(accepted))

    assert exc_info.value is error
    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )] == ["message.received", "message.accepted"]


def test_repeated_explicit_invocation_adds_one_perceived_event_each() -> None:
    event_store, _, coordinator, client, handler = make_components()
    source = Event.create(
        tenant_id="tenant-1",
        event_type="message.received",
        payload={"text": "Hola"},
    )
    _, accepted = append_accepted(coordinator, source)
    context = RuntimeContext.create(accepted)

    handler(context)
    handler(context)

    assert client.calls == ["Hola", "Hola"]
    assert [event.event_type for event in event_store.list_for_tenant(
        "tenant-1"
    )] == [
        "message.received",
        "message.accepted",
        "message.perceived",
        "message.perceived",
    ]
