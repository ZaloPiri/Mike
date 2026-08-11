from dataclasses import FrozenInstanceError, replace
import uuid

import pytest

from mike_app.conversation.response_validation import (
    ConversationResponseValidator,
    ValidatedConversationResponse,
)
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event import Event
from mike_app.runtime.event_store import InMemoryEventStore


def build_chain(
    *,
    tenant_id: str = "tenant-1",
    text: object = "  ¡Hola!\n¿En qué puedo ayudarte?  ",
    language: object = "es",
    target_language: object = "es",
    response_type: object = "intent_response",
    request_response_type: object = "intent_response",
    generation_method: object = "deterministic_template",
    communication_context_values: dict[str, object] | None = None,
):
    event_store = InMemoryEventStore()
    episode_store = InMemoryEpisodeStore()
    coordinator = EpisodeCoordinator(event_store, episode_store)
    communication_context = {
        "channel": "development",
        "external_message_id": "message-id",
        "external_conversation_id": "conversation-id",
        "sender_id": "development-user",
        "recipient_id": tenant_id,
    }
    communication_context.update(communication_context_values or {})
    source = Event.create(
        tenant_id=tenant_id,
        event_type="message.received",
        payload={"text": "Hola", **communication_context},
    )
    initial_episode = coordinator.start_episode(source)
    accepted = Event.create(
        tenant_id=tenant_id,
        event_type="message.accepted",
        payload={"source_event_id": str(source.event_id)},
    )
    coordinator.append_to_episode(initial_episode.episode_id, accepted)
    perceived = Event.create(
        tenant_id=tenant_id,
        event_type="message.perceived",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
        },
    )
    coordinator.append_to_episode(initial_episode.episode_id, perceived)
    normalized = Event.create(
        tenant_id=tenant_id,
        event_type="perception.normalized",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "language": "es",
        },
    )
    coordinator.append_to_episode(initial_episode.episode_id, normalized)
    next_action = Event.create(
        tenant_id=tenant_id,
        event_type="conversation.next_action",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
        },
    )
    coordinator.append_to_episode(initial_episode.episode_id, next_action)
    response_request = Event.create(
        tenant_id=tenant_id,
        event_type="conversation.response_request",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "next_action_event_id": str(next_action.event_id),
            "response_type": request_response_type,
            "target_language": target_language,
        },
    )
    coordinator.append_to_episode(
        initial_episode.episode_id,
        response_request,
    )
    generated = Event.create(
        tenant_id=tenant_id,
        event_type="conversation.response_generated",
        payload={
            "source_event_id": str(source.event_id),
            "accepted_event_id": str(accepted.event_id),
            "perceived_event_id": str(perceived.event_id),
            "normalized_event_id": str(normalized.event_id),
            "next_action_event_id": str(next_action.event_id),
            "response_request_event_id": str(response_request.event_id),
            "response_type": response_type,
            "language": language,
            "text": text,
            "generation_method": generation_method,
        },
    )
    coordinator.append_to_episode(initial_episode.episode_id, generated)
    episode = episode_store.get_by_id(tenant_id, initial_episode.episode_id)
    assert episode is not None
    return (
        event_store,
        episode_store,
        coordinator,
        episode,
        source,
        accepted,
        perceived,
        normalized,
        next_action,
        response_request,
        generated,
    )


def validate_chain(chain):
    (
        _,
        _,
        _,
        episode,
        source,
        accepted,
        perceived,
        normalized,
        next_action,
        response_request,
        generated,
    ) = chain
    return ConversationResponseValidator().validate(
        episode=episode,
        source_event=source,
        accepted_event=accepted,
        perceived_event=perceived,
        normalized_event=normalized,
        next_action_event=next_action,
        response_request_event=response_request,
        response_generated_event=generated,
    )


def test_validated_model_is_created_with_exact_values_and_is_immutable() -> None:
    model = ValidatedConversationResponse(
        response_type="intent_response",
        language="es",
        text="  texto preservado  ",
        generation_method="deterministic_template",
        validation_method="deterministic_contract",
    )

    assert model.text == "  texto preservado  "
    assert model.validation_method == "deterministic_contract"
    with pytest.raises(FrozenInstanceError):
        model.text = "changed"


def test_complete_chain_is_validated_and_text_is_preserved_exactly() -> None:
    text = "  Línea uno\n\tLínea dos\r\n  "

    result = validate_chain(build_chain(text=text))

    assert result == ValidatedConversationResponse(
        response_type="intent_response",
        language="es",
        text=text,
        generation_method="deterministic_template",
        validation_method="deterministic_contract",
    )


@pytest.mark.parametrize("position", range(7))
def test_tenant_mismatch_is_rejected_at_every_event_position(
    position: int,
) -> None:
    chain = list(build_chain())
    event_index = 4 + position
    chain[event_index] = replace(
        chain[event_index],
        tenant_id="tenant-other",
    )

    with pytest.raises(ValueError, match="tenant"):
        validate_chain(tuple(chain))


@pytest.mark.parametrize("position", range(7))
def test_wrong_referenced_event_type_is_rejected(position: int) -> None:
    chain = list(build_chain())
    event_index = 4 + position
    chain[event_index] = replace(
        chain[event_index],
        event_type="wrong.event",
    )

    with pytest.raises(ValueError, match="Event must be"):
        validate_chain(tuple(chain))


def test_generated_event_type_must_be_exact() -> None:
    chain = list(build_chain())
    chain[-1] = replace(
        chain[-1],
        event_type="conversation.response_ready",
    )

    with pytest.raises(ValueError, match="response_generated"):
        validate_chain(tuple(chain))


def test_event_outside_episode_is_rejected() -> None:
    chain = list(build_chain())
    chain[3] = replace(
        chain[3],
        event_ids=chain[3].event_ids[:-1],
    )

    with pytest.raises(ValueError, match="Episode"):
        validate_chain(tuple(chain))


@pytest.mark.parametrize("mutation", ["additional", "reordered"])
def test_episode_must_contain_exactly_the_ordered_seven_event_chain(
    mutation: str,
) -> None:
    chain = list(build_chain())
    event_ids = chain[3].event_ids
    if mutation == "additional":
        event_ids = event_ids + (uuid.uuid4(),)
    else:
        event_ids = event_ids[:5] + (event_ids[6], event_ids[5])
    chain[3] = replace(chain[3], event_ids=event_ids)

    with pytest.raises(ValueError, match="exactly the complete event chain"):
        validate_chain(tuple(chain))


@pytest.mark.parametrize(
    ("event_index", "field_name"),
    [
        (5, "source_event_id"),
        (6, "accepted_event_id"),
        (7, "perceived_event_id"),
        (8, "normalized_event_id"),
        (9, "next_action_event_id"),
        (10, "response_request_event_id"),
    ],
)
def test_missing_or_crossed_reference_is_rejected(
    event_index: int,
    field_name: str,
) -> None:
    chain = list(build_chain())
    payload = chain[event_index].to_dict()["payload"]
    payload[field_name] = str(uuid.uuid4())
    chain[event_index] = replace(chain[event_index], payload=payload)

    with pytest.raises(ValueError, match=field_name):
        validate_chain(tuple(chain))

    payload.pop(field_name)
    chain[event_index] = replace(chain[event_index], payload=payload)
    with pytest.raises(ValueError, match=field_name):
        validate_chain(tuple(chain))


def test_response_type_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="response_type"):
        validate_chain(build_chain(response_type="clarification"))


def test_language_mismatch_with_target_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_language"):
        validate_chain(build_chain(language="es", target_language="en"))


@pytest.mark.parametrize("language", ["en", "ES", "es-AR", ""])
def test_only_exact_spanish_language_is_accepted(language: str) -> None:
    with pytest.raises(ValueError, match="exactly es"):
        validate_chain(
            build_chain(language=language, target_language=language)
        )


@pytest.mark.parametrize("text", [None, 123, [], {}])
def test_non_string_text_is_rejected(text: object) -> None:
    with pytest.raises(TypeError, match="text must be a string"):
        validate_chain(build_chain(text=text))


def test_empty_text_is_rejected_without_trimming_valid_spaces() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        validate_chain(build_chain(text=""))

    assert validate_chain(build_chain(text="   ")).text == "   "


@pytest.mark.parametrize("text", ["before\x00after", "bad\x01", "bad\x7f"])
def test_nul_and_invalid_control_characters_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="control character"):
        validate_chain(build_chain(text=text))


def test_wrong_generation_method_is_rejected() -> None:
    with pytest.raises(ValueError, match="deterministic_template"):
        validate_chain(build_chain(generation_method="provider"))
