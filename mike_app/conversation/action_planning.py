from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mike_app.perception.normalization import (
    CANONICAL_ENTITIES,
    CANONICAL_INTENTS,
)


CANONICAL_ACTIONS = frozenset(
    {
        "respond",
        "request_missing_information",
        "request_clarification",
        "handoff_human",
    }
)

CANONICAL_REASONS = frozenset(
    {
        "intent_understood",
        "missing_required_entities",
        "intent_unclear",
        "human_requested",
        "complaint_requires_human",
    }
)


@dataclass(frozen=True, slots=True)
class ConversationNextAction:
    action: str
    reason: str
    can_continue: bool
    missing_entities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action, str):
            raise TypeError("action must be a string")
        if self.action not in CANONICAL_ACTIONS:
            raise ValueError("action must be a canonical action")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        if self.reason not in CANONICAL_REASONS:
            raise ValueError("reason must be a canonical reason")
        if not isinstance(self.can_continue, bool):
            raise TypeError("can_continue must be a bool")
        if not isinstance(self.missing_entities, Sequence) or isinstance(
            self.missing_entities,
            (str, bytes, bytearray),
        ):
            raise TypeError("missing_entities must be a sequence")

        missing_entities = tuple(self.missing_entities)
        for entity_name in missing_entities:
            if not isinstance(entity_name, str):
                raise TypeError("missing entities must be strings")
            if not entity_name or entity_name.strip() == "":
                raise ValueError("missing entities must be non-empty")
            if entity_name not in CANONICAL_ENTITIES:
                raise ValueError(
                    "missing entities must be canonical entity names"
                )
        if len(set(missing_entities)) != len(missing_entities):
            raise ValueError("duplicate missing entities are not allowed")

        object.__setattr__(self, "missing_entities", missing_entities)
        self._validate_consistency()

    def _validate_consistency(self) -> None:
        if self.action == "respond":
            valid = (
                self.reason == "intent_understood"
                and self.can_continue
                and not self.missing_entities
            )
        elif self.action == "request_missing_information":
            valid = (
                self.reason == "missing_required_entities"
                and not self.can_continue
                and bool(self.missing_entities)
            )
        elif self.action == "request_clarification":
            valid = (
                self.reason == "intent_unclear"
                and not self.can_continue
                and not self.missing_entities
            )
        else:
            valid = (
                self.reason
                in {"human_requested", "complaint_requires_human"}
                and not self.can_continue
                and not self.missing_entities
            )
        if not valid:
            raise ValueError("inconsistent conversation next action")


class ConversationActionPlanner:
    def plan(
        self,
        *,
        intent: str,
        entities: Mapping[str, Any],
    ) -> ConversationNextAction:
        if not isinstance(intent, str):
            raise TypeError("intent must be a string")
        if intent not in CANONICAL_INTENTS:
            raise ValueError("intent must be a canonical normalized intent")
        if not isinstance(entities, Mapping):
            raise TypeError("entities must be a mapping")
        for entity_name in entities:
            if not isinstance(entity_name, str):
                raise ValueError("entity keys must be canonical entity names")
            if entity_name not in CANONICAL_ENTITIES:
                raise ValueError("entity keys must be canonical entity names")

        if intent in {
            "greeting",
            "product_inquiry",
            "price_inquiry",
            "availability_inquiry",
        }:
            return self._respond()
        if intent == "place_order":
            missing_entities = tuple(
                entity_name
                for entity_name in ("product", "quantity")
                if self._is_missing(entities, entity_name)
            )
            if missing_entities:
                return ConversationNextAction(
                    action="request_missing_information",
                    reason="missing_required_entities",
                    can_continue=False,
                    missing_entities=missing_entities,
                )
            return self._respond()
        if intent in {"modify_order", "cancel_order", "unknown"}:
            return ConversationNextAction(
                action="request_clarification",
                reason="intent_unclear",
                can_continue=False,
                missing_entities=(),
            )
        if intent == "complaint":
            return ConversationNextAction(
                action="handoff_human",
                reason="complaint_requires_human",
                can_continue=False,
                missing_entities=(),
            )
        return ConversationNextAction(
            action="handoff_human",
            reason="human_requested",
            can_continue=False,
            missing_entities=(),
        )

    @staticmethod
    def _is_missing(
        entities: Mapping[str, Any],
        entity_name: str,
    ) -> bool:
        if entity_name not in entities:
            return True
        value = entities[entity_name]
        return value is None or (
            isinstance(value, str) and value.strip() == ""
        )

    @staticmethod
    def _respond() -> ConversationNextAction:
        return ConversationNextAction(
            action="respond",
            reason="intent_understood",
            can_continue=True,
            missing_entities=(),
        )
