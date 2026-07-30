from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mike_app.conversation.action_planning import ConversationNextAction
from mike_app.perception.normalization import (
    CANONICAL_ENTITIES,
    CANONICAL_INTENTS,
)


CANONICAL_RESPONSE_TYPES = frozenset(
    {
        "intent_response",
        "missing_information",
        "clarification",
        "human_handoff",
    }
)

CANONICAL_HANDOFF_REASONS = frozenset(
    {
        "human_requested",
        "complaint_requires_human",
    }
)


@dataclass(frozen=True, slots=True)
class ConversationResponseRequest:
    response_type: str
    target_language: str
    intent: str
    requested_entities: tuple[str, ...]
    handoff_reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.response_type, str):
            raise TypeError("response_type must be a string")
        if self.response_type not in CANONICAL_RESPONSE_TYPES:
            raise ValueError(
                "response_type must be a canonical response type"
            )
        if not isinstance(self.target_language, str):
            raise TypeError("target_language must be a string")
        if (
            not self.target_language
            or self.target_language.strip() == ""
        ):
            raise ValueError("target_language must be non-empty")
        if not isinstance(self.intent, str):
            raise TypeError("intent must be a string")
        if self.intent not in CANONICAL_INTENTS:
            raise ValueError("intent must be a canonical normalized intent")
        if not isinstance(self.requested_entities, Sequence) or isinstance(
            self.requested_entities,
            (str, bytes, bytearray),
        ):
            raise TypeError("requested_entities must be a sequence")

        requested_entities = tuple(self.requested_entities)
        for entity_name in requested_entities:
            if not isinstance(entity_name, str):
                raise TypeError("requested entities must be strings")
            if not entity_name or entity_name.strip() == "":
                raise ValueError("requested entities must be non-empty")
            if entity_name not in CANONICAL_ENTITIES:
                raise ValueError(
                    "requested entities must be canonical entity names"
                )
        if len(set(requested_entities)) != len(requested_entities):
            raise ValueError("duplicate requested entities are not allowed")
        if (
            self.handoff_reason is not None
            and self.handoff_reason not in CANONICAL_HANDOFF_REASONS
        ):
            raise ValueError("handoff_reason must be canonical or None")

        object.__setattr__(
            self,
            "requested_entities",
            requested_entities,
        )
        self._validate_consistency()

    def _validate_consistency(self) -> None:
        if self.response_type == "intent_response":
            valid = (
                not self.requested_entities
                and self.handoff_reason is None
            )
        elif self.response_type == "missing_information":
            valid = (
                bool(self.requested_entities)
                and self.handoff_reason is None
            )
        elif self.response_type == "clarification":
            valid = (
                not self.requested_entities
                and self.handoff_reason is None
            )
        else:
            valid = (
                not self.requested_entities
                and self.handoff_reason in CANONICAL_HANDOFF_REASONS
            )
        if not valid:
            raise ValueError("inconsistent conversation response request")


class ResponseRequestPlanner:
    def plan(
        self,
        *,
        action: str,
        reason: str,
        can_continue: bool,
        missing_entities: Sequence[str],
        language: str,
        intent: str,
        entities: Mapping[str, Any],
    ) -> ConversationResponseRequest:
        next_action = ConversationNextAction(
            action=action,
            reason=reason,
            can_continue=can_continue,
            missing_entities=missing_entities,
        )
        if not isinstance(language, str):
            raise TypeError("language must be a string")
        if not language or language.strip() == "":
            raise ValueError("language must be non-empty")
        if not isinstance(intent, str):
            raise TypeError("intent must be a string")
        if intent not in CANONICAL_INTENTS:
            raise ValueError("intent must be a canonical normalized intent")
        if not isinstance(entities, Mapping):
            raise TypeError("entities must be a mapping")
        for entity_name in entities:
            if (
                not isinstance(entity_name, str)
                or entity_name not in CANONICAL_ENTITIES
            ):
                raise ValueError(
                    "entity keys must be canonical entity names"
                )

        if next_action.action == "respond":
            return ConversationResponseRequest(
                response_type="intent_response",
                target_language=language,
                intent=intent,
                requested_entities=(),
                handoff_reason=None,
            )
        if next_action.action == "request_missing_information":
            return ConversationResponseRequest(
                response_type="missing_information",
                target_language=language,
                intent=intent,
                requested_entities=next_action.missing_entities,
                handoff_reason=None,
            )
        if next_action.action == "request_clarification":
            return ConversationResponseRequest(
                response_type="clarification",
                target_language=language,
                intent=intent,
                requested_entities=(),
                handoff_reason=None,
            )
        return ConversationResponseRequest(
            response_type="human_handoff",
            target_language=language,
            intent=intent,
            requested_entities=(),
            handoff_reason=next_action.reason,
        )
