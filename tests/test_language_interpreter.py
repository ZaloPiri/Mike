from __future__ import annotations

import pytest

from mike_app.commercial.language_interpreter import (
    MAX_MENTIONS,
    MAX_QUANTITY,
    MAX_TEXT_LENGTH,
    InterpretationStatus,
    interpret,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("quiero 6 de jamón y queso", [("jamón y queso", 6, "6")]),
        (
            "quiero media docena de jamón y queso; una docena de pollo",
            [("jamón y queso", 6, "media docena"), ("pollo", 12, "una docena")],
        ),
        (
            "quiero 6 de jamón y queso y 6 de pollo",
            [("jamón y queso", 6, "6"), ("pollo", 6, "6")],
        ),
        ("dos de uno 2", [("uno 2", 2, "dos")]),
        ("tres de especial; doce de pollo", [("especial", 3, "tres"), ("pollo", 12, "doce")]),
    ],
)
def test_interprets_approved_explicit_grammar(text, expected):
    result = interpret(text)
    assert result.status is InterpretationStatus.INTERPRETABLE
    assert [(m.product_text, m.quantity, m.quantity_text) for m in result.mentions] == expected
    assert result.original_text == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "quiero jamón y queso",
        "quiero 0 de jamón",
        "quiero -1 de jamón",
        "quiero 1.5 de jamón",
        f"quiero {MAX_QUANTITY + 1} de jamón",
        "quiero 6 de",
        "quiero seis jamón y queso y pollo",
        "quiero seis de jamón; ???",
        "quiero seis de jamón y queso; ???",
        "sumame seis de jamón",
        "quiero otros seis de jamón",
        "quiero seis de ese",
    ],
)
def test_invalid_or_unsupported_input_has_no_partial_result(text):
    result = interpret(text)
    assert result.status is InterpretationStatus.NEEDS_CLARIFICATION
    assert result.mentions == ()
    assert result.original_text == text
    assert result.reason


def test_quantity_words_one_to_twelve_and_names_with_y():
    result = interpret("uno de pan y queso; doce de jamón y queso")
    assert [m.quantity for m in result.mentions] == [1, 12]
    assert [m.product_text for m in result.mentions] == ["pan y queso", "jamón y queso"]


def test_digit_quantities_use_cart_limit_and_associate_multiple_products():
    result = interpret("quiero 24 de jamón y queso y 6 de pollo")
    assert result.status is InterpretationStatus.INTERPRETABLE
    assert [(m.product_text, m.quantity) for m in result.mentions] == [
        ("jamón y queso", 24),
        ("pollo", 6),
    ]
    assert interpret(f"quiero {MAX_QUANTITY} de jamón").mentions[0].quantity == MAX_QUANTITY
    assert interpret(f"quiero {MAX_QUANTITY + 1} de jamón").status is InterpretationStatus.NEEDS_CLARIFICATION


def test_valid_clause_followed_by_invalid_clause_has_no_partial_result():
    result = interpret("quiero 24 de jamón y queso; quiero 0 de pollo")
    assert result.status is InterpretationStatus.NEEDS_CLARIFICATION
    assert result.mentions == ()


def test_limits_include_borders_and_reject_excess():
    product = "producto"
    one = interpret("1 de " + product)
    assert one.status is InterpretationStatus.INTERPRETABLE
    assert interpret("x" * (MAX_TEXT_LENGTH + 1)).reason == "text_too_long"
    ten = "; ".join(f"{i} de producto{i}" for i in range(1, MAX_MENTIONS + 1))
    assert interpret(ten).status is InterpretationStatus.INTERPRETABLE
    eleven = ten + "; 1 de producto11"
    assert interpret(eleven).reason == "too_many_mentions"


def test_parser_is_pure_and_does_not_call_external_services():
    result = interpret("quiero 6 de jamón y queso")
    assert result.mentions[0].unit_text is None
    assert result.mentions[0].quantity == 6
