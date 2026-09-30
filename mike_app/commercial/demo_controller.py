"""Shared interactive controller for synthetic and external local demos."""
from __future__ import annotations

from .cart import CartProposalError
from .catalog_resolution import CatalogResolution, ResolutionStatus
from .language_interpreter import interpret


class DemoController:
    def __init__(self, catalog_client, cart, quote_fn, input_fn=input, output_fn=print):
        self.catalog_client = catalog_client
        self.cart = cart
        self.quote_fn = quote_fn
        self.input_fn = input_fn
        self.output_fn = output_fn

    def _language(self, text):
        interpretation = interpret(text)
        if interpretation.status.value != "interpretable":
            self.output_fn(f"Aclaración: {interpretation.reason}. Ejemplo: lenguaje quiero 6 de Producto A")
            return
        resolution = CatalogResolution.from_interpretation(interpretation)
        for index, mention in enumerate(resolution.mentions):
            resolution = resolution.search(self.catalog_client, index, limit=10)
            while True:
                current = resolution.mentions[index]
                if current.status is ResolutionStatus.RECOVERABLE_ERROR:
                    self.output_fn("Error recuperable de catálogo; el carrito se conserva")
                    return
                if current.status is ResolutionStatus.NO_RESULTS:
                    self.output_fn(f"Sin resultados para: {mention.query}")
                    return
                page = current.page
                assert page is not None
                self.output_fn(f"Mención: {mention.mention.product_text} | cantidad: {mention.mention.quantity} ({mention.mention.quantity_text})")
                self.output_fn("Candidatos: " + ", ".join(f"{p.product_id}={p.name} [{p.unit}]" for p in page.products))
                if page.next_cursor:
                    self.output_fn("Escriba ID o pagina para ver la página siguiente")
                choice = self.input_fn("seleccionar> ").strip()
                if choice.lower() == "pagina" and page.next_cursor:
                    resolution = resolution.next_page(self.catalog_client, index, limit=10)
                    continue
                try:
                    resolution = resolution.select(index, int(choice))
                    break
                except (ValueError, TypeError):
                    self.output_fn("ID inválido para la página vigente")
        try:
            proposal = self.cart.prepare(resolution)
        except CartProposalError as exc:
            self.output_fn(f"No se puede preparar la propuesta: {exc}")
            return
        self.output_fn(f"Propuesta {proposal.proposal_id}: revisar y confirmar")
        for line in proposal.lines:
            previous = f" anterior={line.previous_quantity}" if line.previous_quantity is not None else ""
            self.output_fn(f"{line.operation} {line.product_id} {line.name}: {line.quantity} {line.unit}{previous}")
        if self.input_fn("confirmar propuesta? [s/N] ").strip().lower() != "s":
            self.cart.cancel(proposal.proposal_id)
            self.output_fn("Propuesta cancelada; carrito conservado")
            return
        try:
            self.cart.confirm(proposal.proposal_id, proposal.cart_revision)
        except CartProposalError as exc:
            self.output_fn(f"Propuesta desactualizada: {exc}")
            return
        self.output_fn(f"Carrito actualizado: {self.cart.items()}. Use cotizar para consultar")

    def process(self, command):
        command = command.strip()
        if command.startswith("lenguaje "):
            self._language(command[9:].strip())
            return True
        if command == "carrito":
            self.output_fn(f"Carrito: {self.cart.items()}")
            return True
        if command == "cotizar":
            if self.cart.lines:
                self.quote_fn(self.cart.items())
            else:
                self.output_fn("Carrito vacío: no se envía cotización")
            return True
        if command.startswith("agregar ") or command.startswith("modificar "):
            verb, raw = command.split(" ", 1)
            try:
                product_id, quantity = (int(part) for part in raw.split())
                if verb == "agregar" and product_id in self.cart.lines:
                    if self.input_fn(f"Cantidad actual {self.cart.lines[product_id]}; reemplazar? [s/N] ").strip().lower() != "s":
                        return True
                    self.cart.add(product_id, quantity, replace=True)
                elif verb == "agregar":
                    self.cart.add(product_id, quantity)
                else:
                    self.cart.modify(product_id, quantity)
            except (ValueError, KeyError):
                self.output_fn("Formato o línea inválida")
            return True
        if command.startswith("quitar "):
            try:
                self.cart.remove(int(command.split()[1]))
            except (ValueError, IndexError):
                self.output_fn("Formato: quitar ID")
            return True
        return False
