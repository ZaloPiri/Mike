from __future__ import annotations

import pytest

from mike_app.commercial.cart import CartProposalError, TerminalCart
from mike_app.commercial.catalog_resolution import CatalogResolution, MentionResolution, ResolutionStatus
from mike_app.commercial.gestar_client import CatalogPage, CatalogProduct
from mike_app.commercial.language_interpreter import ProductMention, Interpretation, InterpretationStatus


def resolved(*items):
    mentions = tuple(
        ProductMention(name, quantity, str(quantity), None) for name, quantity in items
    )
    interpretation = Interpretation("texto original", InterpretationStatus.INTERPRETABLE, mentions)
    products = tuple(CatalogProduct(index + 1, name, None, "unidad") for index, (name, _) in enumerate(items))
    return CatalogResolution("texto original", tuple(
        MentionResolution(
            mention, mention.product_text, CatalogPage("i", "b", products, None), product,
            ResolutionStatus.RESOLVED,
        ) for mention, product in zip(mentions, products)
    ))


def test_prepare_add_and_replace_does_not_mutate_and_preserves_unaffected_lines():
    cart = TerminalCart([1, 2, 3]); cart.add(1, 2); cart.add(3, 9)
    revision = cart.revision
    proposal = cart.prepare(resolved(("Producto 1", 4), ("Producto 2", 5)))
    assert [(line.product_id, line.operation, line.previous_quantity, line.quantity) for line in proposal.lines] == [
        (1, "replace", 2, 4), (2, "add", None, 5)
    ]
    assert cart.items() == [{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 9}]
    assert cart.revision == revision
    assert cart.confirm(proposal.proposal_id, revision) is True
    assert cart.items() == [{"product_id": 1, "quantity": 4}, {"product_id": 3, "quantity": 9}, {"product_id": 2, "quantity": 5}]
    assert cart.revision == revision + 1


def test_cancel_and_repeated_confirmation_have_no_effect():
    cart = TerminalCart([1]); proposal = cart.prepare(resolved(("Producto", 2)))
    revision = cart.revision
    cart.cancel(proposal.proposal_id)
    assert cart.items() == [] and cart.revision == revision
    with pytest.raises(CartProposalError): cart.confirm(proposal.proposal_id, revision)
    proposal = cart.prepare(resolved(("Producto", 2)))
    assert cart.confirm(proposal.proposal_id, cart.revision) is True
    with pytest.raises(CartProposalError): cart.confirm(proposal.proposal_id, cart.revision)


def test_proposals_are_scoped_replaced_and_resolution_changes_do_not_mutate_them():
    cart = TerminalCart([1]); other = TerminalCart([1])
    resolution = resolved(("Producto", 2)); first = cart.prepare(resolution)
    second = cart.prepare(resolved(("Producto", 5)))
    with pytest.raises(CartProposalError): cart.confirm(first.proposal_id, first.cart_revision)
    with pytest.raises(CartProposalError): other.confirm(second.proposal_id, second.cart_revision)
    assert first.lines[0].quantity == 2
    assert cart.confirm(second.proposal_id, second.cart_revision) is True


def test_returning_to_old_content_does_not_restore_revision_or_proposal():
    cart = TerminalCart([1]); cart.add(1, 2)
    proposal = cart.prepare(resolved(("Producto", 3)))
    cart.modify(1, 4); cart.modify(1, 2)
    assert cart.revision == proposal.cart_revision + 2
    with pytest.raises(CartProposalError): cart.confirm(proposal.proposal_id, proposal.cart_revision)


def test_manual_changes_invalidate_and_rejected_changes_do_not_increment():
    cart = TerminalCart([1, 2]); cart.add(1, 2); proposal = cart.prepare(resolved(("Producto", 3)))
    revision = cart.revision
    assert cart.add(2, 4) is True
    assert cart.revision == revision + 1
    with pytest.raises(CartProposalError): cart.confirm(proposal.proposal_id, proposal.cart_revision)
    revision = cart.revision
    with pytest.raises(ValueError): cart.modify(1, 0)
    assert cart.revision == revision


@pytest.mark.parametrize("resolution", [
    CatalogResolution("", ()),
    CatalogResolution("incompleta", ()),
])
def test_empty_or_unresolved_resolution_never_applies(resolution):
    cart = TerminalCart([1]); revision = cart.revision
    with pytest.raises(CartProposalError): cart.prepare(resolution)
    assert cart.items() == [] and cart.revision == revision


def test_duplicate_product_mentions_are_rejected_without_partial_application():
    cart = TerminalCart([1])
    first = resolved(("Producto", 2)); duplicate = CatalogResolution(first.original_text, first.mentions + first.mentions)
    with pytest.raises(CartProposalError): cart.prepare(duplicate)
    assert cart.items() == [] and cart.revision == 0


def test_invalid_last_line_and_more_than_fifty_resulting_lines_are_atomic():
    cart = TerminalCart([1, 2]); invalid = resolved(("Uno", 2), ("Dos", 0))
    with pytest.raises(CartProposalError): cart.prepare(invalid)
    assert cart.items() == [] and cart.revision == 0
    full = TerminalCart(range(1, 52))
    for product_id in range(1, 51): full.add(product_id, 1)
    before = full.items(); revision = full.revision
    mention = ProductMention("Producto 51", 1, "1", None)
    extra = CatalogResolution("extra", (MentionResolution(
        mention, mention.product_text,
        CatalogPage("i", "b", (CatalogProduct(51, "Producto 51", None, "unidad"),), None),
        CatalogProduct(51, "Producto 51", None, "unidad"), ResolutionStatus.RESOLVED,
    ),))
    with pytest.raises(CartProposalError): full.prepare(extra)
    assert full.items() == before and full.revision == revision


def test_confirm_without_effect_consumes_proposal_without_incrementing():
    cart = TerminalCart([1]); cart.add(1, 2)
    proposal = cart.prepare(resolved(("Producto", 2)))
    revision = cart.revision
    assert cart.confirm(proposal.proposal_id, revision) is False
    assert cart.revision == revision
    with pytest.raises(CartProposalError): cart.confirm(proposal.proposal_id, revision)
