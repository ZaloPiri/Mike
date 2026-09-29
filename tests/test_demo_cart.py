import pytest

from tools.gestar_demo import TerminalCart


def test_cart_add_modify_remove_and_empty():
    cart = TerminalCart([1, 2])
    assert cart.add(1, 2) is True
    assert cart.add(1, 3) is False
    assert cart.items() == [{"product_id": 1, "quantity": 2}]
    assert cart.modify(1, 3) is True
    cart.remove(1)
    assert cart.items() == []


def test_cart_rejects_invalid_without_partial_mutation():
    cart = TerminalCart([1])
    with pytest.raises(ValueError): cart.add(2, 1)
    with pytest.raises(ValueError): cart.add(1, True)
    with pytest.raises(ValueError): cart.add(1, 10001)
    assert cart.items() == []


def test_cart_modify_remove_do_not_depend_on_current_catalog_page():
    cart = TerminalCart([1, 2]); cart.add(1, 2)
    cart.allowed_ids = {2}
    cart.modify(1, 4); cart.remove(1)
    assert cart.items() == []
