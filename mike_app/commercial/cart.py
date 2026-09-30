"""Temporary local cart and single-use cart proposals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from mike_app.commercial.catalog_resolution import CatalogResolution

MAX_CART_LINES = 50
MAX_LINE_QUANTITY = 10_000


class CartProposalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProposalLine:
    product_id: int
    name: str
    unit: str
    quantity: int
    operation: str
    previous_quantity: int | None


@dataclass(frozen=True, slots=True)
class CartProposal:
    proposal_id: UUID
    cart_id: UUID
    cart_revision: int
    original_text: str
    lines: tuple[ProposalLine, ...]


class TerminalCart:
    def __init__(self, allowed_ids):
        self.allowed_ids = set(allowed_ids)
        self._lines: dict[int, int] = {}
        self._revision = 0
        self._cart_id = uuid4()
        self._active_proposal: CartProposal | None = None

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def cart_id(self) -> UUID:
        return self._cart_id

    @property
    def lines(self) -> dict[int, int]:
        return dict(self._lines)

    def _validate_line(self, product_id, quantity) -> None:
        if (product_id not in self.allowed_ids or isinstance(quantity, bool)
                or not isinstance(quantity, int) or not 1 <= quantity <= MAX_LINE_QUANTITY):
            raise ValueError("línea inválida")

    def _changed(self) -> None:
        self._revision += 1
        self._active_proposal = None

    def add(self, product_id, quantity, replace=False):
        self._validate_line(product_id, quantity)
        if product_id in self._lines and not replace:
            return False
        if self._lines.get(product_id) == quantity:
            return True
        self._lines[product_id] = quantity
        self._changed()
        return True

    def modify(self, product_id, quantity):
        if product_id not in self._lines:
            raise KeyError(product_id)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_LINE_QUANTITY:
            raise ValueError("línea inválida")
        if self._lines[product_id] != quantity:
            self._lines[product_id] = quantity
            self._changed()
        return True

    def remove(self, product_id):
        if product_id in self._lines:
            del self._lines[product_id]
            self._changed()
            return True
        return False

    def items(self):
        return [{"product_id": p, "quantity": q} for p, q in self._lines.items()]

    def clear(self):
        if self._lines:
            self._lines.clear()
            self._changed()

    def prepare(self, resolution: "CatalogResolution") -> CartProposal:
        if not resolution.mentions:
            raise CartProposalError("empty resolution")
        lines: list[ProposalLine] = []
        seen: set[int] = set()
        for item in resolution.mentions:
            if item.status.value != "resolved" or item.selected is None:
                raise CartProposalError("all mentions must be resolved")
            product = item.selected
            if product.product_id in seen:
                raise CartProposalError("duplicate product mention")
            seen.add(product.product_id)
            if product.product_id not in self.allowed_ids:
                raise CartProposalError("product is not allowed in this cart")
            previous = self._lines.get(product.product_id)
            operation = "replace" if previous is not None else "add"
            lines.append(ProposalLine(product.product_id, product.name, product.unit,
                                      item.mention.quantity, operation, previous))
        resulting = dict(self._lines)
        for line in lines:
            if line.quantity < 1 or line.quantity > MAX_LINE_QUANTITY:
                raise CartProposalError("invalid proposed quantity")
            resulting[line.product_id] = line.quantity
        if len(resulting) > MAX_CART_LINES:
            raise CartProposalError("cart line limit exceeded")
        proposal = CartProposal(uuid4(), self._cart_id, self._revision,
                                resolution.original_text, tuple(lines))
        self._active_proposal = proposal
        return proposal

    def confirm(self, proposal_id: UUID, revision: int) -> bool:
        proposal = self._active_proposal
        if proposal is None or proposal.proposal_id != proposal_id:
            raise CartProposalError("proposal is not active")
        if proposal.cart_id != self._cart_id or proposal.cart_revision != revision or revision != self._revision:
            raise CartProposalError("proposal is stale")
        resulting = dict(self._lines)
        for line in proposal.lines:
            if line.product_id not in self.allowed_ids or not 1 <= line.quantity <= MAX_LINE_QUANTITY:
                raise CartProposalError("invalid proposed cart")
            resulting[line.product_id] = line.quantity
        if len(resulting) > MAX_CART_LINES:
            raise CartProposalError("cart line limit exceeded")
        changed = resulting != self._lines
        if changed:
            self._lines = resulting
            self._revision += 1
        self._active_proposal = None
        return changed

    def cancel(self, proposal_id: UUID) -> None:
        if self._active_proposal is None or self._active_proposal.proposal_id != proposal_id:
            raise CartProposalError("proposal is not active")
        self._active_proposal = None


__all__ = ["CartProposal", "CartProposalError", "ProposalLine", "TerminalCart"]
