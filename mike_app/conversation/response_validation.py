from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


GENERATION_METHOD = "deterministic_template"
VALIDATION_METHOD = "deterministic_contract"
_ALLOWED_CONTROL_CHARACTERS = frozenset({"\t", "\n", "\r"})


class ConversationEvent(Protocol):
    event_id: uuid.UUID
    tenant_id: str
    event_type: str
    payload: object


class ConversationEpisode(Protocol):
    tenant_id: str
    event_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class ValidatedConversationResponse:
    response_type: str
    language: str
    text: str
    generation_method: str
    validation_method: str

    def __post_init__(self) -> None:
        if not isinstance(self.response_type, str):
            raise TypeError("response_type must be a string")
        if not self.response_type:
            raise ValueError("response_type must be non-empty")
        if not isinstance(self.language, str):
            raise TypeError("language must be a string")
        if self.language != "es":
            raise ValueError("language must be exactly es")
        _validate_text(self.text)
        if self.generation_method != GENERATION_METHOD:
            raise ValueError(
                "generation_method must be deterministic_template"
            )
        if self.validation_method != VALIDATION_METHOD:
            raise ValueError(
                "validation_method must be deterministic_contract"
            )


class ConversationResponseValidator:
    def validate(
        self,
        *,
        episode: ConversationEpisode,
        source_event: ConversationEvent,
        accepted_event: ConversationEvent,
        perceived_event: ConversationEvent,
        normalized_event: ConversationEvent,
        next_action_event: ConversationEvent,
        response_request_event: ConversationEvent,
        response_generated_event: ConversationEvent,
    ) -> ValidatedConversationResponse:
        events = (
            source_event,
            accepted_event,
            perceived_event,
            normalized_event,
            next_action_event,
            response_request_event,
            response_generated_event,
        )
        expected_types = (
            "message.received",
            "message.accepted",
            "message.perceived",
            "perception.normalized",
            "conversation.next_action",
            "conversation.response_request",
            "conversation.response_generated",
        )
        for event, expected_type in zip(events, expected_types, strict=True):
            if event.event_type != expected_type:
                raise ValueError(f"Event must be {expected_type}")
            if event.tenant_id != episode.tenant_id:
                raise ValueError("Event tenant does not match Episode tenant")
            if event.event_id not in episode.event_ids:
                raise ValueError("Event is not contained in the Episode")
        if episode.event_ids != tuple(event.event_id for event in events):
            raise ValueError(
                "Episode must contain exactly the complete event chain"
            )

        payloads = {
            "accepted": self._require_mapping(accepted_event),
            "perceived": self._require_mapping(perceived_event),
            "normalized": self._require_mapping(normalized_event),
            "next-action": self._require_mapping(next_action_event),
            "response-request": self._require_mapping(
                response_request_event
            ),
            "response-generated": self._require_mapping(
                response_generated_event
            ),
        }
        expected_references = {
            "source_event_id": str(source_event.event_id),
            "accepted_event_id": str(accepted_event.event_id),
            "perceived_event_id": str(perceived_event.event_id),
            "normalized_event_id": str(normalized_event.event_id),
            "next_action_event_id": str(next_action_event.event_id),
            "response_request_event_id": str(
                response_request_event.event_id
            ),
        }
        reference_chain = {
            "accepted": ("source_event_id",),
            "perceived": (
                "source_event_id",
                "accepted_event_id",
            ),
            "normalized": (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
            ),
            "next-action": (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
                "normalized_event_id",
            ),
            "response-request": (
                "source_event_id",
                "accepted_event_id",
                "perceived_event_id",
                "normalized_event_id",
                "next_action_event_id",
            ),
            "response-generated": tuple(expected_references),
        }
        for event_name, field_names in reference_chain.items():
            payload = payloads[event_name]
            for field_name in field_names:
                if payload.get(field_name) != expected_references[field_name]:
                    raise ValueError(
                        f"{event_name} Event {field_name} does not match"
                    )

        request_payload = payloads["response-request"]
        generated_payload = payloads["response-generated"]
        for field_name in (
            "response_type",
            "target_language",
        ):
            if field_name not in request_payload:
                raise ValueError(
                    "response-request Event payload is missing fields"
                )
        for field_name in (
            "response_type",
            "language",
            "text",
            "generation_method",
        ):
            if field_name not in generated_payload:
                raise ValueError(
                    "response-generated Event payload is missing fields"
                )

        if (
            generated_payload["response_type"]
            != request_payload["response_type"]
        ):
            raise ValueError("response_type does not match response request")
        if (
            generated_payload["language"]
            != request_payload["target_language"]
        ):
            raise ValueError("language does not match target_language")

        return ValidatedConversationResponse(
            response_type=generated_payload["response_type"],
            language=generated_payload["language"],
            text=generated_payload["text"],
            generation_method=generated_payload["generation_method"],
            validation_method=VALIDATION_METHOD,
        )

    @staticmethod
    def _require_mapping(event: ConversationEvent) -> Mapping[str, object]:
        if not isinstance(event.payload, Mapping):
            raise ValueError("Event payload must be a mapping")
        return event.payload


def _validate_text(text: object) -> None:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if text == "":
        raise ValueError("text must be non-empty")
    for character in text:
        if (
            unicodedata.category(character) == "Cc"
            and character not in _ALLOWED_CONTROL_CHARACTERS
        ):
            raise ValueError("text contains an invalid control character")
