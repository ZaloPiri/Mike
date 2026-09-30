from __future__ import annotations

import pytest

from mike_app.commercial.catalog_resolution import CatalogResolution, ResolutionStatus
from mike_app.commercial.gestar_client import CatalogPage, CatalogProduct, CommercialIdentityError, CommercialTimeoutError
from mike_app.commercial.language_interpreter import interpret


class FakeCatalog:
    def __init__(self):
        self.calls = []
        self.pages = {
            ("jamón y queso", None): CatalogPage("i", "b", (CatalogProduct(1, "Jamón y queso", "JQ", "unidad"),), "next"),
            ("jamón y queso", "next"): CatalogPage("i", "b", (CatalogProduct(2, "Jamón y queso especial", None, "unidad"),), None),
            ("pollo", None): CatalogPage("i", "b", (CatalogProduct(3, "Pollo", None, "unidad"),), None),
            ("docena", None): CatalogPage("i", "b", (CatalogProduct(4, "Caja", None, "caja"),), None),
        }

    def list_products(self, query, limit=50, cursor=None):
        self.calls.append((query, limit, cursor))
        return self.pages[(query, cursor)]


def _resolution(text):
    parsed = interpret(text)
    assert parsed.mentions
    return CatalogResolution.from_interpretation(parsed)


def test_resolves_multiple_mentions_without_losing_association_or_auto_selecting():
    client = FakeCatalog()
    result = _resolution("quiero 24 de jamón y queso y 6 de pollo")
    result = result.search(client, 0, limit=1)
    result = result.search(client, 1, limit=1)
    assert [item.status for item in result.mentions] == [ResolutionStatus.PENDING_SELECTION, ResolutionStatus.PENDING_SELECTION]
    assert result.mentions[0].mention.quantity == 24
    assert result.mentions[1].mention.quantity == 6
    assert result.mentions[0].selected is None
    result = result.select(0, 1).select(1, 3)
    assert [item.selected_product_id for item in result.mentions] == [1, 3]
    assert [item.status for item in result.mentions] == [ResolutionStatus.RESOLVED, ResolutionStatus.RESOLVED]


def test_selection_requires_current_page_and_explicit_integer_id():
    client = FakeCatalog()
    result = _resolution("quiero 6 de jamón y queso").search(client, 0)
    with pytest.raises(TypeError):
        result.select(0, True)
    with pytest.raises(TypeError):
        result.select(0, "1")
    with pytest.raises(ValueError):
        result.select(0, 2)
    result = result.next_page(client, 0)
    with pytest.raises(ValueError):
        result.select(0, 1)
    assert result.select(0, 2).mentions[0].status is ResolutionStatus.RESOLVED


def test_query_error_invalidates_only_its_own_options_and_empty_results_are_explicit():
    class Failing(FakeCatalog):
        def list_products(self, query, limit=50, cursor=None):
            if query == "pollo":
                raise CommercialTimeoutError()
            if query == "inexistente":
                return CatalogPage("i", "b", (), None)
            return super().list_products(query, limit, cursor)

    client = Failing()
    result = _resolution("quiero 6 de jamón y queso y 6 de pollo")
    result = result.search(client, 0).search(client, 1)
    assert result.mentions[0].status is ResolutionStatus.PENDING_SELECTION
    assert result.mentions[1].status is ResolutionStatus.RECOVERABLE_ERROR
    empty = CatalogResolution.from_interpretation(interpret("quiero 6 de inexistente")).search(client, 0)
    assert empty.mentions[0].status is ResolutionStatus.NO_RESULTS


def test_docena_requires_the_contractual_individual_unit_and_duplicate_ids_are_reported():
    result = _resolution("quiero media docena de docena").search(FakeCatalog(), 0)
    assert result.select(0, 4).mentions[0].status is ResolutionStatus.UNIT_INCOMPATIBLE
    result = _resolution("quiero 6 de jamón y queso y 6 de pollo")
    client = FakeCatalog()
    client.pages[("pollo", None)] = CatalogPage("i", "b", (CatalogProduct(1, "Pollo", None, "unidad"),), None)
    result = result.search(client, 0).search(client, 1)
    result = result.select(0, 1).select(1, 1)
    assert result.mentions[1].status is ResolutionStatus.CONFLICT
    assert result.mentions[0].selected_product_id == result.mentions[1].selected_product_id == 1


def test_docena_converts_only_the_approved_individual_unit():
    client = FakeCatalog()
    client.pages[("docena", None)] = CatalogPage(
        "i", "b", (CatalogProduct(4, "Docena individual", None, "unidad"),), None
    )
    result = _resolution("quiero media docena de docena").search(client, 0).select(0, 4)
    assert result.mentions[0].status is ResolutionStatus.RESOLVED
    assert result.mentions[0].mention.quantity == 6
    assert result.mentions[0].mention.quantity_text == "media docena"
