from __future__ import annotations

from mike_app.commercial.cart import TerminalCart
from mike_app.commercial.catalog_resolution import CatalogPage, CatalogProduct
from tools.gestar_demo import DemoController


class Catalog:
    def list_products(self, query, limit=50, cursor=None):
        products = {
            "Producto A": CatalogProduct(1, "Producto A", "A", "unidad"),
            "Producto B": CatalogProduct(2, "Producto B", "B", "unidad"),
        }
        return CatalogPage("i", "b", (products[query],), None)


def controller(inputs, cart=None, quotes=None, output=None):
    cart = cart or TerminalCart([1, 2])
    quotes = quotes if quotes is not None else []
    output = output if output is not None else []
    values = iter(inputs)
    return DemoController(Catalog(), cart, lambda items: quotes.append(items), lambda _: next(values), output.append), cart, quotes, output


def test_language_flow_requires_selection_proposes_then_confirms_without_auto_quote():
    demo, cart, quotes, output = controller(["1", "2", "s"])
    assert demo.process("lenguaje quiero 6 de Producto A y 12 de Producto B") is True
    assert cart.items() == [{"product_id": 1, "quantity": 6}, {"product_id": 2, "quantity": 12}]
    assert quotes == []
    assert any("Propuesta" in line for line in output)
    demo.process("cotizar")
    assert quotes == [[{"product_id": 1, "quantity": 6}, {"product_id": 2, "quantity": 12}]]


def test_language_cancel_and_invalid_input_preserve_cart():
    cart = TerminalCart([1]); cart.add(1, 3)
    demo, _, quotes, output = controller(["1", "n"], cart=cart)
    demo.process("lenguaje quiero 6 de Producto A")
    assert cart.items() == [{"product_id": 1, "quantity": 3}]
    demo.process("lenguaje quiero Producto A")
    assert cart.items() == [{"product_id": 1, "quantity": 3}]
    assert quotes == []
    assert any("Aclaración" in line for line in output)


def test_language_replacement_shows_previous_quantity_and_old_confirmation_is_not_reused():
    cart = TerminalCart([1]); cart.add(1, 3)
    demo, _, _, output = controller(["1", "s"], cart=cart)
    demo.process("lenguaje quiero 6 de Producto A")
    assert cart.items() == [{"product_id": 1, "quantity": 6}]
    assert any("anterior=3" in line and "replace" in line for line in output)
