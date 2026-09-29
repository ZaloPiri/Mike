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

ROOT = Path(__file__).resolve().parents[1]
GESTAR = Path(r"C:\Users\Ana\Desktop\GESTAR-mike-base")
GESTAR_HEAD = "272a5bbd641b925adc3bd814ea2d486e64f15e8d"

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return sock.getsockname()[1]

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
    temp = engine = server_mike = server_gestar = None
    try:
        sys.path.insert(0, str(ROOT))
        temp, engine, gestar_app, catalog = seed_gestar()
        from mike_app.core.settings import Settings
        from mike_app.main import create_app
        token = os.environ["GESTAR_COMMERCIAL_BEARER_TOKEN"]; key = secrets.token_urlsafe(18)
        server_gestar, thread_gestar = start(gestar_app, free_port()); gestar_port = server_gestar.config.port
        settings = Settings("mike", "0.1.0", "development", None, None, "memory", None, None, gestar_commercial_enabled=True, gestar_base_url=f"http://127.0.0.1:{gestar_port}", gestar_bearer_token=token, gestar_installation_id="demo-installation", gestar_business_id="demo-business", gestar_tenant_id="demo-tenant", gestar_dev_key=key)
        server_mike, thread_mike = start(create_app(settings), free_port()); base = f"http://127.0.0.1:{server_mike.config.port}"
        ids = [x[0] for x in catalog]; presets = {"simple":[{"product_id":ids[0],"quantity":4}], "paquetes":[{"product_id":ids[0],"quantity":6},{"product_id":ids[1],"quantity":12}], "promocion":[{"product_id":ids[6],"quantity":4},{"product_id":ids[7],"quantity":2}], "mixto":[{"product_id":p,"quantity":2} for p in ids[:6]], "benchmark":[{"product_id":p,"quantity":6} for p in ids[:6]]}
        print("DEMOSTRACIÓN CON DATOS FICTICIOS — no crea ni reserva pedidos"); print("Catálogo:", ", ".join(f"{p}: {n}" for p,n in catalog)); print("Use id=cantidad,id=cantidad o simple/paquetes/promocion/mixto/benchmark; salir termina.")
        for name in args.scenario or []: print(f"\nEscenario: {name}"); quote(base, key, presets[name])
        while not args.scenario:
            command = input("demo> ").strip().lower()
            if command in {"salir","exit","quit","q"}: break
            if command in presets: quote(base, key, presets[command]); continue
            try: quote(base, key, [{"product_id":int(part.split("=")[0]),"quantity":int(part.split("=")[1])} for part in command.split(",")])
            except (ValueError, IndexError): print("Formato: id=cantidad,id=cantidad")
    except (KeyboardInterrupt, EOFError): print("\nSaliendo de la demostración.")
    finally:
        for server in (server_mike, server_gestar):
            if server is not None: server.should_exit = True
        if server_mike is not None: thread_mike.join(timeout=10)
        if server_gestar is not None: thread_gestar.join(timeout=10)
        if engine is not None: engine.dispose()
        if temp is not None: temp.cleanup()
        for name in list(os.environ):
            if name.startswith("GESTAR_COMMERCIAL_"): os.environ.pop(name, None)

if __name__ == "__main__": main()
