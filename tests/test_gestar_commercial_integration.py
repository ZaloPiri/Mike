"""Black-box MIKE -> real Gestar commercial router integration.

The Gestar application factory/lifespan is intentionally not imported.  Only
the committed router and its real service dependencies are mounted in an
isolated FastAPI process with a synthetic SQLite database.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import importlib.util
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mike_app.core.settings import Settings
from mike_app.main import create_app


GESTAR = Path(r"C:\Users\Ana\Desktop\GESTAR-mike-base")
TOKEN = "synthetic-integration-token"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def integrated_stack(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(GESTAR))
    from app.database import Base, get_db
    from app.models import (Category, MixedPriceGroup, MixedPriceGroupItem,
                            PriceList, Product, ProductPrice, Promotion,
                            PromotionItem, AuditEvent, CashMovement, Sale,
                            StockMovement)
    # Import only the commercial module: app.routes.__init__ eagerly imports
    # every HTML router, which would require Gestar's optional Jinja runtime.
    routes_package = types.ModuleType("app.routes")
    routes_package.__path__ = [str(GESTAR / "app" / "routes")]
    sys.modules["app.routes"] = routes_package
    commercial_spec = importlib.util.spec_from_file_location(
        "app.routes.commercial", GESTAR / "app" / "routes" / "commercial.py"
    )
    commercial_module = importlib.util.module_from_spec(commercial_spec)
    sys.modules["app.routes.commercial"] = commercial_module
    assert commercial_spec.loader is not None
    commercial_spec.loader.exec_module(commercial_module)
    commercial_router = commercial_module.router

    db_path = tmp_path / "gestar-synthetic.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        category = Category(nombre="Sintéticos")
        price_list = PriceList(nombre="Prueba", fecha_inicio=date(2020, 1, 1), activa=True)
        db.add_all([category, price_list])
        db.flush()
        products = [
            Product(nombre=f"Producto {name}", categoria=category, activo=True, controla_stock=False)
            for name in "ABCDEF"
        ]
        missing = Product(nombre="Sin precio", categoria=category, activo=True, controla_stock=False)
        db.add_all(products + [missing])
        db.flush()
        db.add_all([
            ProductPrice(lista=price_list, producto=product, precio_unitario=Decimal("100"),
                         precio_media_docena=Decimal("500"), precio_docena=Decimal("900"))
            for product in products
        ])
        group = MixedPriceGroup(nombre="Grupo sintético", precio_media_docena=Decimal("500"),
                                precio_docena=Decimal("900"), activo=True)
        group.items = [MixedPriceGroupItem(product_id=product.id) for product in products]
        promotion = Promotion(nombre="Promo sintética", precio_final=Decimal("100"),
                              fecha_inicio=date(2020, 1, 1), repetible=True, prioridad=1)
        promotion.items = [PromotionItem(product_id=products[0].id, cantidad=2),
                           PromotionItem(product_id=products[1].id, cantidad=1)]
        db.add_all([group, promotion])
        db.commit()
        ids = [product.id for product in products]
        missing_id = missing.id

    os.environ.update({
        "GESTAR_COMMERCIAL_ENABLED": "true",
        "GESTAR_COMMERCIAL_BEARER_TOKEN": TOKEN,
        "GESTAR_COMMERCIAL_INSTALLATION_ID": "synthetic-installation",
        "GESTAR_COMMERCIAL_BUSINESS_ID": "synthetic-business",
        "GESTAR_COMMERCIAL_TENANT_ID": "synthetic-tenant",
        "GESTAR_COMMERCIAL_CURRENCY": "ARS",
        "GESTAR_COMMERCIAL_TIMEZONE": "America/Argentina/Buenos_Aires",
        "GESTAR_COMMERCIAL_ALLOW_HTTP_LOOPBACK": "true",
        "GESTAR_COMMERCIAL_SCOPES": "commercial.products.read commercial.quotes.read",
    })

    def isolated_db():
        db = Session(engine)
        try:
            yield db
        finally:
            db.close()

    gestar_app = FastAPI()
    gestar_app.include_router(commercial_router)
    gestar_app.dependency_overrides[get_db] = isolated_db
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(gestar_app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        settings = Settings(
            app_name="mike", app_version="0.1.0", environment="development",
            openai_api_key=None, openai_model=None, episode_journal="memory",
            database_url=None, test_database_url=None, gestar_commercial_enabled=True,
            gestar_base_url=f"http://127.0.0.1:{port}", gestar_bearer_token=TOKEN,
            gestar_installation_id="synthetic-installation", gestar_business_id="synthetic-business",
            gestar_tenant_id="synthetic-tenant", gestar_dev_key="synthetic-local-key",
        )
        yield settings, ids, missing_id, engine, (Sale, CashMovement, StockMovement, AuditEvent), port
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        for key in ("GESTAR_COMMERCIAL_ENABLED", "GESTAR_COMMERCIAL_BEARER_TOKEN",
                    "GESTAR_COMMERCIAL_INSTALLATION_ID", "GESTAR_COMMERCIAL_BUSINESS_ID",
                    "GESTAR_COMMERCIAL_TENANT_ID", "GESTAR_COMMERCIAL_CURRENCY",
                    "GESTAR_COMMERCIAL_TIMEZONE", "GESTAR_COMMERCIAL_ALLOW_HTTP_LOOPBACK",
                    "GESTAR_COMMERCIAL_SCOPES"):
            os.environ.pop(key, None)


def test_real_mike_http_client_reaches_gestar_router_and_keeps_both_sides_read_only(integrated_stack):
    settings, ids, missing_id, engine, effect_models, port = integrated_stack
    before = {model: count for model, count in ((model, Session(engine).query(model).count()) for model in effect_models)}
    with TestClient(create_app(settings)) as mike:
        direct = httpx.post(f"http://127.0.0.1:{port}/api/v1/commercial/quotes",
                            headers={"Authorization": f"Bearer {TOKEN}"},
                            json={"items": [{"product_id": ids[0], "quantity": 6}]}, timeout=5)
        assert direct.status_code == 200, direct.text
        from mike_app.commercial.gestar_client import _validate_response, GestarCommercialConfig
        try:
            _validate_response(direct.json(), [{"product_id": ids[0], "quantity": 6}], GestarCommercialConfig(
                settings.gestar_base_url, TOKEN, settings.gestar_installation_id,
                settings.gestar_business_id, settings.gestar_tenant_id))
        except Exception as exc:
            raise AssertionError("Gestar response must validate in MIKE") from exc
        response = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                             json={"items": [{"product_id": ids[0], "quantity": 4}]})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == "400.00"
        assert body["installation_id"] == "synthetic-installation"
        assert body["lines"][0]["quantity"] == 4
        assert body["stock_reserved"] is False
        assert body["availability_guaranteed"] is False
        half_dozen = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                               json={"items": [{"product_id": ids[0], "quantity": 6}]})
        dozen = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                          json={"items": [{"product_id": ids[0], "quantity": 12}]})
        assert half_dozen.status_code == 200, half_dozen.text
        assert dozen.status_code == 200, dozen.text
        assert half_dozen.json()["total"] == "500.00"
        assert dozen.json()["total"] == "900.00"
        mixed = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                          json={"items": [{"product_id": product_id, "quantity": 2} for product_id in ids]})
        assert mixed.status_code == 200
        assert mixed.json()["total"] == "900.00"
        promo = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                          json={"items": [{"product_id": ids[0], "quantity": 4}, {"product_id": ids[1], "quantity": 2}]})
        assert promo.status_code == 200
        assert promo.json()["promotions_applied"][0]["times"] == 2
        assert promo.json()["total"] == "200.00"
        assert mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                         json={"items": [{"product_id": missing_id, "quantity": 1}]}).status_code == 422
    after = {model: count for model, count in ((model, Session(engine).query(model).count()) for model in effect_models)}
    assert after == before


def test_real_gestar_errors_and_binding_are_not_accepted_as_success(integrated_stack, monkeypatch):
    settings, ids, _, _, _, _ = integrated_stack
    with TestClient(create_app(settings)) as mike:
        bad_auth = settings.__class__(**{**settings.__dict__, "gestar_bearer_token": "wrong"})
        with TestClient(create_app(bad_auth)) as bad_client:
            response = bad_client.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                                       json={"items": [{"product_id": ids[0], "quantity": 1}]})
            assert response.status_code == 401
        monkeypatch.setenv("GESTAR_COMMERCIAL_SCOPES", "commercial.products.read")
        response = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                             json={"items": [{"product_id": ids[0], "quantity": 1}]})
        assert response.status_code == 403
        monkeypatch.setenv("GESTAR_COMMERCIAL_SCOPES", "commercial.products.read commercial.quotes.read")
        incompatible = settings.__class__(**{**settings.__dict__, "gestar_installation_id": "other-installation"})
        with TestClient(create_app(incompatible)) as incompatible_client:
            response = incompatible_client.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                                                json={"items": [{"product_id": ids[0], "quantity": 1}]})
            assert response.status_code == 409
            assert "Bearer" not in response.text and TOKEN not in response.text
