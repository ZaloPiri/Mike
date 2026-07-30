from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any


CANONICAL_INTENTS = frozenset(
    {
        "greeting",
        "product_inquiry",
        "price_inquiry",
        "availability_inquiry",
        "place_order",
        "modify_order",
        "cancel_order",
        "complaint",
        "human_assistance",
        "unknown",
    }
)

CANONICAL_ENTITIES = frozenset(
    {
        "product",
        "quantity",
        "quantity_unit",
        "requested_datetime_text",
        "customer_name",
        "phone",
        "delivery_address",
        "payment_method",
        "notes",
    }
)

_INTENT_ALIASES = MappingProxyType(
    {
        "hello": "greeting",
        "greet": "greeting",
        "salutation": "greeting",
        "ask_product": "product_inquiry",
        "product_question": "product_inquiry",
        "product_query": "product_inquiry",
        "menu_inquiry": "product_inquiry",
        "ask_price": "price_inquiry",
        "price_question": "price_inquiry",
        "pricing_inquiry": "price_inquiry",
        "cost_inquiry": "price_inquiry",
        "ask_availability": "availability_inquiry",
        "availability_query": "availability_inquiry",
        "stock_inquiry": "availability_inquiry",
        "product_availability": "availability_inquiry",
        "create_order": "place_order",
        "order_request": "place_order",
        "purchase_intent": "place_order",
        "order_creation": "place_order",
        "change_order": "modify_order",
        "edit_order": "modify_order",
        "update_order": "modify_order",
        "order_cancellation": "cancel_order",
        "cancel_purchase": "cancel_order",
        "complaint_request": "complaint",
        "customer_complaint": "complaint",
        "dissatisfaction": "complaint",
        "request_human": "human_assistance",
        "human_help": "human_assistance",
        "agent_request": "human_assistance",
        "talk_to_person": "human_assistance",
        "unclear": "unknown",
        "unsupported": "unknown",
        "other": "unknown",
    }
)

_ENTITY_ALIASES = MappingProxyType(
    {
        "item": "product",
        "product_name": "product",
        "menu_item": "product",
        "service": "product",
        "service_name": "product",
        "amount": "quantity",
        "count": "quantity",
        "qty": "quantity",
        "quantity_value": "quantity",
        "unit": "quantity_unit",
        "amount_unit": "quantity_unit",
        "qty_unit": "quantity_unit",
        "requested_datetime": "requested_datetime_text",
        "requested_time": "requested_datetime_text",
        "requested_date": "requested_datetime_text",
        "date_time": "requested_datetime_text",
        "delivery_time": "requested_datetime_text",
        "pickup_time": "requested_datetime_text",
        "name": "customer_name",
        "client_name": "customer_name",
        "buyer_name": "customer_name",
        "phone_number": "phone",
        "telephone": "phone",
        "mobile": "phone",
        "contact_phone": "phone",
        "address": "delivery_address",
        "shipping_address": "delivery_address",
        "destination": "delivery_address",
        "payment": "payment_method",
        "pay_method": "payment_method",
        "payment_type": "payment_method",
        "note": "notes",
        "comment": "notes",
        "comments": "notes",
        "special_instructions": "notes",
        "observations": "notes",
    }
)


def _freeze_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    "entities must contain only JSON-compatible values"
                )
            frozen[key] = _freeze_json_compatible(item)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return tuple(_freeze_json_compatible(item) for item in value)
    raise ValueError("entities must contain only JSON-compatible values")


@dataclass(frozen=True, slots=True)
class NormalizedPerception:
    language: str
    intent: str
    confidence: float
    entities: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.language, str):
            raise TypeError("language must be a string")
        if not self.language or self.language.strip() == "":
            raise ValueError("language must be non-empty")
        if not isinstance(self.intent, str):
            raise TypeError("intent must be a string")
        if self.intent not in CANONICAL_INTENTS:
            raise ValueError("intent must be a canonical intent")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence,
            Real,
        ):
            raise TypeError("confidence must be a real number")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not isinstance(self.entities, Mapping):
            raise TypeError("entities must be a mapping")
        for key in self.entities:
            if key not in CANONICAL_ENTITIES:
                raise ValueError("entities contain an unknown canonical key")

        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(
            self,
            "entities",
            _freeze_json_compatible(self.entities),
        )


def _normalize_token(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return re.sub(r"_+", "_", normalized)


class PerceptionNormalizer:
    def normalize(
        self,
        *,
        language: str,
        intent: str,
        confidence: float,
        entities: Mapping[str, Any],
    ) -> NormalizedPerception:
        if not isinstance(intent, str):
            raise TypeError("intent must be a string")
        if not isinstance(entities, Mapping):
            raise TypeError("entities must be a mapping")

        intent_token = _normalize_token(intent)
        normalized_intent = _INTENT_ALIASES.get(
            intent_token,
            intent_token if intent_token in CANONICAL_INTENTS else "unknown",
        )

        normalized_entities: dict[str, Any] = {}
        for source_key, value in entities.items():
            if not isinstance(source_key, str):
                raise TypeError("entity keys must be strings")
            entity_token = _normalize_token(source_key)
            canonical_key = _ENTITY_ALIASES.get(
                entity_token,
                entity_token
                if entity_token in CANONICAL_ENTITIES
                else None,
            )
            if canonical_key is None:
                continue
            if canonical_key in normalized_entities:
                raise ValueError(
                    f"duplicate canonical entity: {canonical_key}"
                )
            normalized_entities[canonical_key] = value

        return NormalizedPerception(
            language=language,
            intent=normalized_intent,
            confidence=confidence,
            entities=normalized_entities,
        )
