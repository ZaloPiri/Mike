"""Black-box MIKE -> real Gestar commercial router integration.

The Gestar application factory/lifespan is intentionally not imported.  Only
the committed router and its real service dependencies are mounted in an
isolated FastAPI process with a synthetic SQLite database.
"""

from __future__ import annotations

import os
import socket
import subprocess
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
GESTAR_EXPECTED_HEAD = "1a2a7245b019eadfa1b950de5f9e82a48822be55"
TOKEN = "synthetic-integration-token"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def integrated_stack(tmp_path, monkeypatch):
    observed_head = subprocess.check_output(
        ["git", "-C", str(GESTAR), "rev-parse", "HEAD"], text=True
    ).strip()
    assert observed_head == GESTAR_EXPECTED_HEAD
    monkeypatch.syspath_prepend(str(GESTAR))
    from app.model_base import Base
    from app.commercial_database import get_db
    from app.models import (Category, MixedPriceGroup, MixedPriceGroupItem,
                            PriceList, Product, ProductPrice, Promotion,
                            PromotionItem, AuditEvent, CashMovement, Sale,
                            StockMovement)
    from app.commercial_entry import create_commercial_app

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
            for name in "ABCDEFGH"
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
        group.items = [MixedPriceGroupItem(product_id=product.id) for product in products[:6]]
        promotion = Promotion(nombre="Promo sintética", precio_final=Decimal("100"),
                              fecha_inicio=date(2020, 1, 1), repetible=True, prioridad=1)
        promotion.items = [PromotionItem(product_id=products[6].id, cantidad=2),
                           PromotionItem(product_id=products[7].id, cantidad=1)]
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

    gestar_app, readonly_service = create_commercial_app(db_path)
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
        readonly_service.close()
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
                          json={"items": [{"product_id": current_id, "quantity": 2} for current_id in ids[:6] ]})
        assert mixed.status_code == 200
        assert mixed.json()["total"] == "900.00"
        promo = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                          json={"items": [{"product_id": ids[6], "quantity": 4}, {"product_id": ids[7], "quantity": 2}]})
        assert promo.status_code == 200
        assert promo.json()["promotions_applied"][0]["times"] == 2
        assert promo.json()["total"] == "200.00"
        assert mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                         json={"items": [{"product_id": missing_id, "quantity": 1}]}).status_code == 422
    after = {model: count for model, count in ((model, Session(engine).query(model).count()) for model in effect_models)}
    assert after == before


def test_benchmark_cart_promotion_and_mixed_group_through_mike(integrated_stack):
    settings, ids, _, engine, effect_models, _ = integrated_stack
    before = {model: Session(engine).query(model).count() for model in effect_models}
    items = [{"product_id": ids[6], "quantity": 4}, {"product_id": ids[7], "quantity": 2}]
    items.extend({"product_id": product_id, "quantity": 2} for product_id in ids[:6])
    started = time.perf_counter()
    with TestClient(create_app(settings)) as mike:
        response = mike.post("/dev/commercial/quote",
                             headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                             json={"items": items})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    body = response.json()
    print(f"MIKE_GESTAR_BENCHMARK_ELAPSED_SECONDS={elapsed:.6f}")
    assert elapsed < 5.0
    assert body["promotions_applied"] and body["promotions_applied"][0]["times"] == 2
    assert body["mixed_groups_applied"] and body["mixed_groups_applied"][0]["times"] >= 1
    requested = {item["product_id"]: item["quantity"] for item in items}
    consumed = {product_id: 0 for product_id in requested}
    for entry in body["promotions_applied"] + body["mixed_groups_applied"]:
        for component in entry["components"]:
            consumed[component["product_id"]] += component["quantity"]
    for line in body["lines"]:
        assert requested[line["product_id"]] == (
            line["promotion_quantity"] + line["mixed_group_quantity"] + line["remaining_quantity"]
        )
        assert consumed[line["product_id"]] == line["promotion_quantity"] + line["mixed_group_quantity"]
    assert body["total"] == "1100.00"
    after = {model: Session(engine).query(model).count() for model in effect_models}
    assert after == before


def test_committed_mixed_plus_promotion_benchmark_through_mike(integrated_stack):
    """Reproduce Gestar benchmark case mixed_plus_promotion exactly.

    Source: tests/benchmark_commercial_limits.py and
    tests/test_pricing_engine_optimization.py at Gestar HEAD 272a5bb.
    """
    settings, ids, _, engine, effect_models, _ = integrated_stack
    from app.models import Promotion, PromotionItem

    with Session(engine) as db:
        db.query(PromotionItem).delete()
        db.query(Promotion).delete()
        for n in range(2):
            promotion = Promotion(
                nombre=f"Benchmark Promo {n}", precio_final=Decimal("900"),
                fecha_inicio=date(2020, 1, 1), activa=True,
                prioridad=n, repetible=True,
            )
            promotion.items = [
                PromotionItem(product_id=ids[n], cantidad=2),
                PromotionItem(product_id=ids[n + 1], cantidad=2),
            ]
            db.add(promotion)
        db.commit()
        before = {model: db.query(model).count() for model in effect_models}

    started = time.perf_counter()
    with TestClient(create_app(settings)) as mike:
        response = mike.post(
            "/dev/commercial/quote",
            headers={"X-MIKE-Development-Key": "synthetic-local-key"},
            json={"items": [{"product_id": product_id, "quantity": 6} for product_id in ids[:6]]},
        )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    body = response.json()
    print(f"MIKE_GESTAR_COMMITTED_BENCHMARK_ELAPSED_SECONDS={elapsed:.6f}")
    assert elapsed < 5.0
    assert body["total"] == "2700.00"
    assert body["promotions_applied"] == []
    assert [(entry["size"], entry["times"], entry["subtotal"]) for entry in body["mixed_groups_applied"]] == [(12, 3, "2700.00")]
    assert [line["remaining_quantity"] for line in body["lines"]] == [0] * 6
    assert body["pricing_breakdown"] == []
    consumed = {
        line["product_id"]: sum(
            component["quantity"]
            for group in body["mixed_groups_applied"]
            for component in group["components"]
            if component["product_id"] == line["product_id"]
        )
        for line in body["lines"]
    }
    assert all(consumed[line["product_id"]] == line["quantity"] for line in body["lines"])
    with Session(engine) as db:
        after = {model: db.query(model).count() for model in effect_models}
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


def test_real_catalog_page_selection_then_quote_and_deactivated_product(integrated_stack):
    settings, ids, _, engine, effect_models, port = integrated_stack
    before = {model: Session(engine).query(model).count() for model in effect_models}
    with httpx.Client() as catalog_http:
        page = catalog_http.get(f"http://127.0.0.1:{port}/api/v1/commercial/products?limit=2",
                                headers={"Authorization": f"Bearer {TOKEN}"})
        assert page.status_code == 200
        selected = page.json()["products"][0]
        assert selected["product_id"] == ids[0]
        assert page.json()["next_cursor"]
    with TestClient(create_app(settings)) as mike:
        quoted = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                           json={"items": [{"product_id": selected["product_id"], "quantity": 4}]})
        assert quoted.status_code == 200 and quoted.json()["lines"][0]["product_id"] == selected["product_id"]
        from app.models import Product
        with Session(engine) as db:
            db.get(Product, selected["product_id"]).activo = False; db.commit()
        rejected = mike.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                             json={"items": [{"product_id": selected["product_id"], "quantity": 4}]})
        assert rejected.status_code == 422
    with Session(engine) as db:
        assert {model: db.query(model).count() for model in effect_models} == before


def test_real_catalog_search_page_and_explicit_selection(integrated_stack):
    settings, ids, _, engine, effect_models, _ = integrated_stack
    from mike_app.commercial.catalog_resolution import CatalogResolution, ResolutionStatus
    from mike_app.commercial.gestar_client import GestarCommercialClient, GestarCommercialConfig
    from mike_app.commercial.language_interpreter import interpret

    before = {model: Session(engine).query(model).count() for model in effect_models}
    client = GestarCommercialClient(GestarCommercialConfig(
        settings.gestar_base_url, TOKEN, settings.gestar_installation_id,
        settings.gestar_business_id, settings.gestar_tenant_id,
    ))
    try:
        resolution = CatalogResolution.from_interpretation(interpret("quiero 6 de Producto A"))
        resolution = resolution.search(client, 0, limit=1)
        assert resolution.mentions[0].status is ResolutionStatus.PENDING_SELECTION
        assert resolution.mentions[0].page is not None
        selected_id = resolution.mentions[0].page.products[0].product_id
        assert selected_id == ids[0]
        with pytest.raises(ValueError):
            resolution.select(0, ids[1])
        resolved = resolution.select(0, selected_id)
        assert resolved.mentions[0].status is ResolutionStatus.RESOLVED
        assert resolved.mentions[0].mention.quantity == 6
        assert resolved.mentions[0].mention.quantity_text == "6"
    finally:
        client.close()
    with Session(engine) as db:
        assert {model: db.query(model).count() for model in effect_models} == before


def test_real_language_selection_proposal_and_explicit_quote(integrated_stack):
    settings, ids, _, engine, effect_models, _ = integrated_stack
    from mike_app.commercial.gestar_client import GestarCommercialClient, GestarCommercialConfig
    from tools.gestar_demo import DemoController

    before = {model: Session(engine).query(model).count() for model in effect_models}
    catalog = GestarCommercialClient(GestarCommercialConfig(
        settings.gestar_base_url, TOKEN, settings.gestar_installation_id,
        settings.gestar_business_id, settings.gestar_tenant_id,
    ))
    try:
        cart = __import__("mike_app.commercial.cart", fromlist=["TerminalCart"]).TerminalCart(ids)
        responses = []
        with TestClient(create_app(settings)) as mike:
            def quote(items):
                response = mike.post("/dev/commercial/quote",
                                     headers={"X-MIKE-Development-Key": "synthetic-local-key"},
                                     json={"items": items})
                responses.append(response)
                return response

            answers = iter([str(ids[0]), str(ids[1]), "s"])
            demo = DemoController(catalog, cart, quote, input_fn=lambda _: next(answers), output_fn=lambda _: None)
            assert demo.process("lenguaje quiero 4 de Producto A y 6 de Producto B") is True
            assert cart.items() == [{"product_id": ids[0], "quantity": 4}, {"product_id": ids[1], "quantity": 6}]
            assert responses == []
            assert demo.process("cotizar") is True
        assert len(responses) == 1
        assert responses[0].status_code == 200, responses[0].text
        body = responses[0].json()
        assert [(line["product_id"], line["quantity"]) for line in body["lines"]] == [(ids[0], 4), (ids[1], 6)]
        assert body["total"] == "900.00"
        assert body["mixed_groups_applied"]
        consumed = sum(component["quantity"] for group in body["mixed_groups_applied"]
                        for component in group["components"])
        assert consumed == sum(line["mixed_group_quantity"] for line in body["lines"])
    finally:
        catalog.close()
    with Session(engine) as db:
        assert {model: db.query(model).count() for model in effect_models} == before
