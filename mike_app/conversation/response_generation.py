from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mike_app.conversation.response_planning import (
    CANONICAL_HANDOFF_REASONS,
    CANONICAL_RESPONSE_TYPES,
    ConversationResponseRequest,
)
from mike_app.perception.normalization import CANONICAL_ENTITIES


GENERATION_METHOD = "deterministic_template"

_INTENT_RESPONSE_TEXT = {
    "greeting": "¡Hola! ¿En qué puedo ayudarte?",
    "product_inquiry": (
        "Para ayudarte con los productos necesito consultar la información "
        "del comercio."
    ),
    "price_inquiry": (
        "Para informarte el precio necesito consultar la información del "
        "comercio."
    ),
    "availability_inquiry": (
        "Para confirmarte la disponibilidad necesito consultar la "
        "información del comercio."
    ),
    "place_order": (
        "Entendí que querés realizar un pedido. Antes de confirmarlo "
        "necesito consultar la información del comercio."
    ),
}

_MISSING_INFORMATION_TEXT = {
    ("product",): "¿Qué producto necesitás?",
    ("quantity",): "¿Qué cantidad necesitás?",
    (
        "product",
        "quantity",
    ): "¿Qué producto y qué cantidad necesitás?",
}

_CLARIFICATION_TEXT = (
    "No terminé de entender tu mensaje. ¿Podés reformularlo?"
)

_HUMAN_HANDOFF_TEXT = {
    (
        "human_assistance",
        "human_requested",
    ): "Voy a derivarte con una persona para que pueda ayudarte.",
    (
        "complaint",
        "complaint_requires_human",
    ): (
        "Lamento lo ocurrido. Voy a derivarte con una persona para que "
        "pueda ayudarte."
    ),
}


@dataclass(frozen=True, slots=True)
class GeneratedConversationResponse:
    response_type: str
    language: str
    text: str
    generation_method: str

    def __post_init__(self) -> None:
        if not isinstance(self.response_type, str):
            raise TypeError("response_type must be a string")
        if self.response_type not in CANONICAL_RESPONSE_TYPES:
            raise ValueError(
                "response_type must be a canonical response type"
            )
        if not isinstance(self.language, str):
            raise TypeError("language must be a string")
        if not self.language or self.language.strip() == "":
            raise ValueError("language must be non-empty")
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not self.text or self.text.strip() == "":
            raise ValueError("text must be non-empty")
        if self.generation_method != GENERATION_METHOD:
            raise ValueError(
                "generation_method must be deterministic_template"
            )


class DeterministicResponseGenerator:
    def generate(
        self,
        *,
        response_type: str,
        language: str,
        intent: str,
        requested_entities: Sequence[str],
        handoff_reason: str | None,
    ) -> GeneratedConversationResponse:
        request = ConversationResponseRequest(
            response_type=response_type,
            target_language=language,
            intent=intent,
            requested_entities=requested_entities,
            handoff_reason=handoff_reason,
        )
        if language != "es":
            raise ValueError("language must be exactly es")
        for entity_name in request.requested_entities:
            if entity_name not in CANONICAL_ENTITIES:
                raise ValueError(
                    "requested entities must be canonical entity names"
                )
        if (
            request.handoff_reason is not None
            and request.handoff_reason not in CANONICAL_HANDOFF_REASONS
        ):
            raise ValueError("handoff_reason must be canonical or None")

        if request.response_type == "intent_response":
            text = _INTENT_RESPONSE_TEXT.get(request.intent)
            if text is None:
                raise ValueError(
                    "unsupported intent_response intent"
                )
        elif request.response_type == "missing_information":
            if request.intent != "place_order":
                raise ValueError(
                    "missing_information requires place_order"
                )
            text = _MISSING_INFORMATION_TEXT.get(
                request.requested_entities
            )
            if text is None:
                raise ValueError(
                    "unsupported requested_entities combination"
                )
        elif request.response_type == "clarification":
            if request.intent not in {
                "modify_order",
                "cancel_order",
                "unknown",
            }:
                raise ValueError("unsupported clarification intent")
            text = _CLARIFICATION_TEXT
        else:
            text = _HUMAN_HANDOFF_TEXT.get(
                (request.intent, request.handoff_reason)
            )
            if text is None:
                raise ValueError(
                    "unsupported human_handoff combination"
                )

        return GeneratedConversationResponse(
            response_type=request.response_type,
            language=request.target_language,
            text=text,
            generation_method=GENERATION_METHOD,
        )
