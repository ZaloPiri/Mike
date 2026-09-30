"""Interactive local MIKE/Gestar demonstration with synthetic data only."""
from __future__ import annotations
import argparse, importlib.util, os, secrets, socket, sys, tempfile, threading, time, types
from datetime import date
from decimal import Decimal
from pathlib import Path
import httpx, uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from mike_app.commercial.cart import TerminalCart
from mike_app.commercial.catalog_resolution import CatalogResolution, ResolutionStatus
from mike_app.commercial.cart import CartProposalError
from mike_app.commercial.language_interpreter import interpret
from mike_app.commercial.demo_controller import DemoController as SharedDemoController

ROOT = Path(__file__).resolve().parents[1]
GESTAR = Path(r"C:\Users\Ana\Desktop\GESTAR-mike-base")
GESTAR_HEAD = "272a5bbd641b925adc3bd814ea2d486e64f15e8d"

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return sock.getsockname()[1]


class DemoController:
    """Command controller used by the interactive demo and its focused tests."""
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
        answer = self.input_fn("confirmar propuesta? [s/N] ").strip().lower()
        if answer != "s":
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

DemoController = SharedDemoController


def load_router():
    sys.path.insert(0, str(GESTAR))
    routes = types.ModuleType("app.routes"); routes.__path__ = [str(GESTAR / "app" / "routes")]
    sys.modules["app.routes"] = routes
    spec = importlib.util.spec_from_file_location("app.routes.commercial", GESTAR / "app/routes/commercial.py")
    module = importlib.util.module_from_spec(spec); sys.modules["app.routes.commercial"] = module
    assert spec.loader is not None; spec.loader.exec_module(module)
    return module.router, module.get_db

def seed_gestar():
    observed = __import__("subprocess").check_output(["git", "-C", str(GESTAR), "rev-parse", "HEAD"], text=True).strip()
    if observed != GESTAR_HEAD: raise RuntimeError(f"Gestar HEAD inesperado: {observed}")
    router, get_db = load_router()
    from app.database import Base
    from app.models import Category, MixedPriceGroup, MixedPriceGroupItem, PriceList, Product, ProductPrice, Promotion, PromotionItem
    temp = tempfile.TemporaryDirectory(prefix="mike-gestar-demo-")
    engine = create_engine(f"sqlite:///{Path(temp.name) / 'synthetic.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        category = Category(nombre="Demo ficticia"); price_list = PriceList(nombre="Demo", fecha_inicio=date(2020, 1, 1), activa=True)
        db.add_all([category, price_list]); db.flush()
        products = [Product(nombre=f"Producto {name}", categoria=category, activo=True, controla_stock=False) for name in "ABCDEFGH"]
        db.add_all(products); db.flush()
        db.add_all([ProductPrice(lista=price_list, producto=p, precio_unitario=Decimal("100"), precio_media_docena=Decimal("500"), precio_docena=Decimal("900")) for p in products])
        group = MixedPriceGroup(nombre="Grupo demo", precio_media_docena=Decimal("500"), precio_docena=Decimal("900"), activo=True)
        group.items = [MixedPriceGroupItem(product_id=p.id) for p in products[:6]]
        promo = Promotion(nombre="Promo demo repetible", precio_final=Decimal("100"), fecha_inicio=date(2020, 1, 1), activa=True, repetible=True, prioridad=1)
        promo.items = [PromotionItem(product_id=products[6].id, cantidad=2), PromotionItem(product_id=products[7].id, cantidad=1)]
        db.add_all([group, promo]); db.commit(); catalog = [(p.id, p.nombre) for p in products]
    os.environ.update({"GESTAR_COMMERCIAL_ENABLED":"true", "GESTAR_COMMERCIAL_BEARER_TOKEN":secrets.token_urlsafe(24), "GESTAR_COMMERCIAL_INSTALLATION_ID":"demo-installation", "GESTAR_COMMERCIAL_BUSINESS_ID":"demo-business", "GESTAR_COMMERCIAL_TENANT_ID":"demo-tenant", "GESTAR_COMMERCIAL_CURRENCY":"ARS", "GESTAR_COMMERCIAL_TIMEZONE":"America/Argentina/Buenos_Aires", "GESTAR_COMMERCIAL_ALLOW_HTTP_LOOPBACK":"true", "GESTAR_COMMERCIAL_SCOPES":"commercial.products.read commercial.quotes.read"})
    def override():
        db = Session(engine)
        try: yield db
        finally: db.close()
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_db] = override
    return temp, engine, app, catalog

def start(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")); thread = threading.Thread(target=server.run, daemon=True); thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline: time.sleep(.02)
    if not server.started: raise RuntimeError("servidor no inició")
    return server, thread

def quote(base, key, items):
    started = time.perf_counter(); response = httpx.post(base + "/dev/commercial/quote", headers={"X-MIKE-Development-Key":key}, json={"items":items}, timeout=5); elapsed = time.perf_counter() - started
    print(f"HTTP {response.status_code} | tiempo {elapsed:.3f}s")
    if response.is_success:
        body = response.json(); print(f"Total: ARS {body['total']} | reservado: {body['stock_reserved']} | disponibilidad garantizada: {body['availability_guaranteed']}"); print("Líneas:", [(x["product_id"], x["quantity"]) for x in body["lines"]]); print("Desglose:", body["pricing_breakdown"]); print("Promociones:", body["promotions_applied"]); print("Grupos:", body["mixed_groups_applied"]); print("Advertencias:", body["stock_warnings"])
    else: print("Error:", response.json().get("error", {}).get("code", "respuesta inválida"))

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--scenario", action="append", choices=["simple","paquetes","promocion","mixto","benchmark"]); args = parser.parse_args()
    temp = engine = server_mike = server_gestar = catalog_client = None
    try:
        sys.path.insert(0, str(ROOT))
        temp, engine, gestar_app, catalog = seed_gestar()
        from mike_app.core.settings import Settings
        from mike_app.main import create_app
        from mike_app.commercial.gestar_client import GestarCommercialClient, GestarCommercialConfig
        token = os.environ["GESTAR_COMMERCIAL_BEARER_TOKEN"]; key = secrets.token_urlsafe(18)
        server_gestar, thread_gestar = start(gestar_app, free_port()); gestar_port = server_gestar.config.port
        settings = Settings("mike", "0.1.0", "development", None, None, "memory", None, None, gestar_commercial_enabled=True, gestar_base_url=f"http://127.0.0.1:{gestar_port}", gestar_bearer_token=token, gestar_installation_id="demo-installation", gestar_business_id="demo-business", gestar_tenant_id="demo-tenant", gestar_dev_key=key)
        server_mike, thread_mike = start(create_app(settings), free_port()); base = f"http://127.0.0.1:{server_mike.config.port}"
        catalog_client = GestarCommercialClient(GestarCommercialConfig(settings.gestar_base_url, token, settings.gestar_installation_id, settings.gestar_business_id, settings.gestar_tenant_id))
        page = catalog_client.list_products(limit=100); catalog = [(p.product_id, p.name) for p in page.products]; ids = [x[0] for x in catalog]
        presets = {"simple":[{"product_id":ids[0],"quantity":4}], "paquetes":[{"product_id":ids[0],"quantity":6},{"product_id":ids[1],"quantity":12}], "promocion":[{"product_id":ids[6],"quantity":4},{"product_id":ids[7],"quantity":2}], "mixto":[{"product_id":p,"quantity":2} for p in ids[:6]], "benchmark":[{"product_id":p,"quantity":6} for p in ids[:6]]}
        cart = TerminalCart(ids)
        controller = DemoController(catalog_client, cart, lambda items: quote(base, key, items))
        print("DEMOSTRACIÓN CON DATOS FICTICIOS — no crea ni reserva pedidos"); print("Catálogo consultado a Gestar:", ", ".join(f"{p}: {n}" for p,n in catalog)); print("Use simple/paquetes/promocion/mixto/benchmark, buscar texto, agregar id cantidad, modificar id cantidad, quitar id, carrito, cotizar o salir.")
        print("Ayuda: lenguaje <texto> busca menciones, muestra candidatos y exige seleccionar IDs; confirmar aplica la propuesta y no cotiza. Use cotizar por separado. Comandos manuales: buscar texto, agregar id cantidad, modificar id cantidad, quitar id, carrito, cotizar, salir.")
        for name in args.scenario or []: print(f"\nEscenario: {name}"); quote(base, key, presets[name])
        while not args.scenario:
            command = input("demo> ").strip().lower()
            if command in {"salir","exit","quit","q"}: break
            if command in presets: quote(base, key, presets[command]); continue
            if controller.process(command): continue
            if command == "carrito": print("Carrito:", cart.items()); continue
            if command == "cotizar":
                if cart.lines: quote(base, key, cart.items())
                else: print("Carrito vacío: no se envía cotización")
                continue
            if command.startswith("buscar "):
                result = catalog_client.list_products(command[7:]); print("Coincidencias:", [(p.product_id, p.name, p.code, p.unit) for p in result.products]); continue
            if command.startswith("agregar ") or command.startswith("modificar "):
                verb, raw = command.split(" ", 1); parts = raw.split();
                try:
                    product_id, quantity = int(parts[0]), int(parts[1])
                    if product_id not in ids or quantity < 1 or quantity > 10000: raise ValueError
                    if verb == "agregar" and product_id in cart.lines:
                        answer = input(f"Cantidad actual {cart.lines[product_id]}; reemplazar por {quantity}? [s/N] ").strip().lower()
                        if answer != "s": continue
                    if verb == "agregar": cart.add(product_id, quantity, replace=True)
                    else: cart.modify(product_id, quantity)
                except (ValueError, IndexError): print("Formato: agregar|modificar ID CANTIDAD")
                continue
            if command.startswith("quitar "):
                try: cart.remove(int(command.split()[1]))
                except (ValueError, IndexError): print("Formato: quitar ID")
                continue
            try: quote(base, key, [{"product_id":int(part.split("=")[0]),"quantity":int(part.split("=")[1])} for part in command.split(",")])
            except (ValueError, IndexError): print("Formato: id=cantidad,id=cantidad")
    except (KeyboardInterrupt, EOFError): print("\nSaliendo de la demostración.")
    finally:
        for server in (server_mike, server_gestar):
            if server is not None: server.should_exit = True
        if server_mike is not None: thread_mike.join(timeout=10)
        if server_gestar is not None: thread_gestar.join(timeout=10)
        if catalog_client is not None: catalog_client.close()
        if engine is not None: engine.dispose()
        if temp is not None: temp.cleanup()
        for name in list(os.environ):
            if name.startswith("GESTAR_COMMERCIAL_"): os.environ.pop(name, None)

if __name__ == "__main__": main()
