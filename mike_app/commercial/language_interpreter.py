"""Pure, deterministic interpretation of explicit commercial phrases."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

MAX_TEXT_LENGTH = 500
MAX_MENTIONS = 10
MAX_QUANTITY = 10_000

_NUMBER_WORDS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12,
}
_QUANTITY = r"(?:media\s+docena|una\s+docena|\d+|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)"
_PREFIX = re.compile(r"^\s*(?:quiero\s+)?", re.IGNORECASE)
_CLAUSE = re.compile(
    rf"^(?P<quantity>{_QUANTITY})\s+de\s+(?P<product>.+?)\s*$",
    re.IGNORECASE,
)
_UNSUPPORTED = re.compile(
    r"\b(?:sumame|sumáme|otros\s+seis|seis\s+m[aá]s|ese|esa|eso|el\s+anterior|lo\s+de\s+siempre)\b",
    re.IGNORECASE,
)


class InterpretationStatus(StrEnum):
    INTERPRETABLE = "interpretable"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass(frozen=True, slots=True)
class ProductMention:
    product_text: str
    quantity: int
    quantity_text: str
    unit_text: str | None


@dataclass(frozen=True, slots=True)
class Interpretation:
    original_text: str
    status: InterpretationStatus
    mentions: tuple[ProductMention, ...]
    reason: str | None = None


def _quantity(value: str) -> int | None:
    token = " ".join(value.lower().split())
    if token == "media docena":
        return 6
    if token == "una docena":
        return 12
    if token.isdigit():
        number = int(token)
        return number if 1 <= number <= MAX_QUANTITY else None
    return _NUMBER_WORDS.get(token)


def _invalid(original: str, reason: str) -> Interpretation:
    return Interpretation(original, InterpretationStatus.NEEDS_CLARIFICATION, (), reason)


def interpret(text: str) -> Interpretation:
    """Interpret only explicit product/quantity clauses; never performs I/O."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not text.strip():
        return _invalid(text, "empty_text")
    if len(text) > MAX_TEXT_LENGTH:
        return _invalid(text, "text_too_long")
    if _UNSUPPORTED.search(text):
        return _invalid(text, "contextual_reference_or_sum_not_supported")

    normalized = _PREFIX.sub("", text.strip())
    pieces = re.split(r"\s*;\s*", normalized)
    clauses: list[str] = []
    for piece in pieces:
        if not piece.strip():
            return _invalid(text, "empty_clause")
        # A conjunction is a separator only if the following token is a quantity.
        parts = re.split(rf"\s+y\s+(?={_QUANTITY}(?:\s+de)?\s+)", piece, flags=re.IGNORECASE)
        clauses.extend(parts)
    if len(clauses) > MAX_MENTIONS:
        return _invalid(text, "too_many_mentions")

    mentions: list[ProductMention] = []
    for clause in clauses:
        match = _CLAUSE.fullmatch(clause.strip())
        if match is None:
            return _invalid(text, "uninterpretable_clause")
        if len(re.findall(r"\s+y\s+", match.group("product"), re.IGNORECASE)) > 1:
            return _invalid(text, "ambiguous_product_conjunction")
        quantity_text = " ".join(match.group("quantity").split())
        quantity = _quantity(quantity_text)
        product = " ".join(match.group("product").split())
        if quantity is None:
            return _invalid(text, "invalid_quantity")
        if not product:
            return _invalid(text, "invalid_product_text")
        mentions.append(ProductMention(product, quantity, quantity_text, None))
    return Interpretation(text, InterpretationStatus.INTERPRETABLE, tuple(mentions))
