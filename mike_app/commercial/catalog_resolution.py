"""Resolve parsed product mentions against explicit Gestar catalog pages."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from mike_app.commercial.gestar_client import CatalogPage, CatalogProduct
from mike_app.commercial.language_interpreter import Interpretation, ProductMention


class CatalogLookup(Protocol):
    def list_products(self, query: str, limit: int = 50, cursor: str | None = None) -> CatalogPage:
        ...


class ResolutionStatus(StrEnum):
    PENDING_SEARCH = "pending_search"
    PENDING_SELECTION = "pending_selection"
    NO_RESULTS = "no_results"
    UNIT_INCOMPATIBLE = "unit_incompatible"
    RECOVERABLE_ERROR = "recoverable_error"
    RESOLVED = "resolved"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class MentionResolution:
    mention: ProductMention
    query: str
    page: CatalogPage | None = None
    selected: CatalogProduct | None = None
    status: ResolutionStatus = ResolutionStatus.PENDING_SEARCH
    error: Exception | None = None

    @property
    def selected_product_id(self) -> int | None:
        return self.selected.product_id if self.selected else None


@dataclass(frozen=True, slots=True)
class CatalogResolution:
    original_text: str
    mentions: tuple[MentionResolution, ...]

    @classmethod
    def from_interpretation(cls, interpretation: Interpretation) -> "CatalogResolution":
        return cls(
            interpretation.original_text,
            tuple(MentionResolution(mention, mention.product_text) for mention in interpretation.mentions),
        )

    def _at(self, index: int) -> MentionResolution:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self.mentions):
            raise IndexError("mention index out of range")
        return self.mentions[index]

    def _replace_at(self, index: int, value: MentionResolution) -> "CatalogResolution":
        updated = list(self.mentions)
        updated[index] = value
        return replace(self, mentions=tuple(updated))

    def search(self, client: CatalogLookup, index: int, *, limit: int = 50) -> "CatalogResolution":
        current = self._at(index)
        try:
            page = client.list_products(current.query, limit=limit)
        except Exception as exc:
            return self._replace_at(index, replace(current, page=None, selected=None,
                                                   status=ResolutionStatus.RECOVERABLE_ERROR, error=exc))
        status = ResolutionStatus.PENDING_SELECTION if page.products else ResolutionStatus.NO_RESULTS
        return self._replace_at(index, replace(current, page=page, selected=None, status=status, error=None))

    def next_page(self, client: CatalogLookup, index: int, *, limit: int = 50) -> "CatalogResolution":
        current = self._at(index)
        if current.page is None or current.page.next_cursor is None:
            raise ValueError("no next catalog page")
        try:
            page = client.list_products(current.query, limit=limit, cursor=current.page.next_cursor)
        except Exception as exc:
            return self._replace_at(index, replace(current, page=None, selected=None,
                                                   status=ResolutionStatus.RECOVERABLE_ERROR, error=exc))
        status = ResolutionStatus.PENDING_SELECTION if page.products else ResolutionStatus.NO_RESULTS
        return self._replace_at(index, replace(current, page=page, selected=None, status=status, error=None))

    def select(self, index: int, product_id: object) -> "CatalogResolution":
        current = self._at(index)
        if current.page is None or current.status is not ResolutionStatus.PENDING_SELECTION:
            raise ValueError("selection is not available for this mention")
        if isinstance(product_id, bool) or not isinstance(product_id, int):
            raise TypeError("product_id must be an integer")
        product = next((item for item in current.page.products if item.product_id == product_id), None)
        if product is None:
            raise ValueError("product_id is not on the current page")
        if current.mention.quantity_text in {"media docena", "una docena"} and product.unit != "unidad":
            return self._replace_at(index, replace(current, selected=None, status=ResolutionStatus.UNIT_INCOMPATIBLE, error=None))
        status = ResolutionStatus.RESOLVED
        for other_index, other in enumerate(self.mentions):
            if other_index != index and other.selected_product_id == product.product_id:
                status = ResolutionStatus.CONFLICT
                break
        return self._replace_at(index, replace(current, selected=product, status=status, error=None))
