from __future__ import annotations

from mike_app.commercial.gestar_client import CatalogPage, CatalogProduct
from mike_app.core.settings import Settings
from mike_app.main import create_app
from mike_app.commercial.web_sessions import WebSessionManager
from fastapi.testclient import TestClient
import threading
import time


class FakeCommercial:
    def list_products(self, query, limit=50, cursor=None):
        return CatalogPage("install", "business", (CatalogProduct(1, "Producto A", "A", "unidad"),), None)

    def quote(self, items):
        return {"currency": "ARS", "items": items, "total": "100.00"}

    def close(self):
        pass


class BlockingCommercial(FakeCommercial):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def quote(self, items):
        self.started.set()
        assert self.release.wait(3)
        return super().quote(items)


def _settings(**changes):
    values = dict(app_name="mike", app_version="0.1.0", environment="development",
                  openai_api_key=None, openai_model=None, episode_journal="memory",
                  database_url=None, test_database_url=None,
                  gestar_commercial_enabled=True, gestar_base_url="http://127.0.0.1:9000",
                  gestar_bearer_token="synthetic", gestar_installation_id="install",
                  gestar_business_id="business", gestar_tenant_id="tenant",
                  gestar_dev_key="dev", web_control_key="control")
    values.update(changes)
    return Settings(**values)


def _headers():
    return {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}


def test_get_does_not_create_session_and_bootstrap_is_single_use():
    app = create_app(_settings())
    with TestClient(app) as client:
        app.state.web_sessions.catalog_client = FakeCommercial()
        app.state.web_sessions.quote_client = app.state.web_sessions.catalog_client
        assert client.get("/dev/web-commercial/", headers={"Host": "127.0.0.1:8000"}).json() == {"bootstrap_required": True}
        response = client.post("/dev/web-commercial/control/bootstrap-code", headers={**_headers(), "X-MIKE-Control-Key": "control"})
        code = response.json()["code"]
        boot = client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": code})
        assert boot.status_code == 200
        csrf = boot.json()["csrf"]
        assert client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": code}).status_code == 401
        assert client.get("/dev/web-commercial/state", headers={**_headers(), "X-MIKE-CSRF": csrf}).status_code == 200


def test_web_flow_interpret_select_propose_confirm_and_quote_without_auto_quote():
    app = create_app(_settings())
    with TestClient(app) as client:
        fake = FakeCommercial()
        app.state.web_sessions.catalog_client = fake
        app.state.web_sessions.quote_client = fake
        code = client.post("/dev/web-commercial/control/bootstrap-code", headers={**_headers(), "X-MIKE-Control-Key": "control"}).json()["code"]
        boot = client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": code})
        csrf = boot.json()["csrf"]
        auth = {**_headers(), "X-MIKE-CSRF": csrf}
        assert client.post("/dev/web-commercial/interpret", headers=auth, json={"text": "quiero 2 de Producto A"}).status_code == 200
        search = client.post("/dev/web-commercial/search", headers=auth, json={"query": "Producto A", "cursor": None, "limit": 10, "mention_index": 0}).json()
        assert client.post("/dev/web-commercial/select", headers=auth, json={"search_id": search["search_id"], "product_id": 1}).status_code == 200
        proposal = client.post("/dev/web-commercial/proposals", headers=auth).json()
        assert client.get("/dev/web-commercial/state", headers=auth).json()["lines"] == []
        confirmed = client.post(f"/dev/web-commercial/proposals/{proposal['proposal_id']}/confirm", headers=auth, json={"expected_revision": 0})
        assert confirmed.status_code == 200
        quote = client.post("/dev/web-commercial/quote", headers=auth, json={"expected_revision": 1})
        assert quote.status_code == 200
        assert quote.json()["quote"]["items"] == [{"product_id": 1, "quantity": 2}]
        assert client.post(f"/dev/web-commercial/proposals/{proposal['proposal_id']}/confirm", headers=auth, json={"expected_revision": 1}).status_code == 409


def test_control_code_requires_independent_secret_and_origin():
    app = create_app(_settings())
    with TestClient(app) as client:
        headers = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        assert client.post("/dev/web-commercial/control/bootstrap-code", headers=headers).status_code == 401
        assert client.post("/dev/web-commercial/control/bootstrap-code", headers={**headers, "X-MIKE-Control-Key": "control", "Origin": "http://evil.test"}).status_code == 403


def test_bootstrap_code_is_consumed_atomically_and_expiry_is_enforced():
    app = create_app(_settings())
    with TestClient(app) as client:
        code = client.post("/dev/web-commercial/control/bootstrap-code", headers={**_headers(), "X-MIKE-Control-Key": "control"}).json()["code"]
        results = []

        def consume():
            results.append(client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": code}).status_code)

        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert sorted(results) == [200, 401]

        expired = app.state.web_sessions.issue_bootstrap_code()
        app.state.web_sessions._bootstrap[expired] = 0
        assert client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": expired}).status_code == 401


def test_distinct_bootstraps_obey_four_session_capacity_atomically():
    manager = WebSessionManager(None, None, max_sessions=4)
    codes = [manager.issue_bootstrap_code() for _ in range(5)]
    results = []

    def consume(code):
        try:
            manager.bootstrap(code)
            results.append("ok")
        except Exception as exc:
            results.append(getattr(exc, "code", "other"))

    threads = [threading.Thread(target=consume, args=(code,)) for code in codes]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert results.count("ok") == 4
    assert results.count("session_limit") == 1


def test_web_session_isolation_and_logout_revokes_shared_browser_session():
    manager = WebSessionManager(None, None)
    first = manager.bootstrap(manager.issue_bootstrap_code())
    second = manager.bootstrap(manager.issue_bootstrap_code())
    assert first.token != second.token
    assert len(manager._sessions) == 2
    manager.logout(first.token)
    assert manager.get(second.token) is second
    try:
        manager.get(first.token)
    except Exception as exc:
        assert getattr(exc, "code", None) == "web_session_required"


def test_quote_releases_session_lock_and_discards_after_cart_change_or_logout():
    app = create_app(_settings())
    fake = BlockingCommercial()
    with TestClient(app) as client:
        app.state.web_sessions.catalog_client = fake
        app.state.web_sessions.quote_client = fake
        code = client.post("/dev/web-commercial/control/bootstrap-code", headers={**_headers(), "X-MIKE-Control-Key": "control"}).json()["code"]
        boot = client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": code})
        auth = {**_headers(), "X-MIKE-CSRF": boot.json()["csrf"]}
        search = client.post("/dev/web-commercial/search", headers=auth, json={"query": "A", "cursor": None, "limit": 10}).json()
        client.post("/dev/web-commercial/cart/add", headers=auth, json={"product_id": 1, "quantity": 1, "selection_id": search["search_id"], "expected_revision": 0})
        result = []
        worker = threading.Thread(target=lambda: result.append(client.post("/dev/web-commercial/quote", headers=auth, json={"expected_revision": 1}).status_code))
        worker.start()
        assert fake.started.wait(2)
        assert client.post("/dev/web-commercial/cart/modify", headers=auth, json={"product_id": 1, "quantity": 2, "expected_revision": 1}).status_code == 200
        fake.release.set(); worker.join(3)
        assert result == [409]

    app = create_app(_settings())
    fake = BlockingCommercial()
    with TestClient(app) as client:
        app.state.web_sessions.catalog_client = fake
        app.state.web_sessions.quote_client = fake
        code = client.post("/dev/web-commercial/control/bootstrap-code", headers={**_headers(), "X-MIKE-Control-Key": "control"}).json()["code"]
        boot = client.post("/dev/web-commercial/bootstrap", headers=_headers(), json={"code": code})
        auth = {**_headers(), "X-MIKE-CSRF": boot.json()["csrf"]}
        search = client.post("/dev/web-commercial/search", headers=auth, json={"query": "A", "cursor": None, "limit": 10}).json()
        client.post("/dev/web-commercial/cart/add", headers=auth, json={"product_id": 1, "quantity": 1, "selection_id": search["search_id"], "expected_revision": 0})
        result = []
        worker = threading.Thread(target=lambda: result.append(client.post("/dev/web-commercial/quote", headers=auth, json={"expected_revision": 1}).status_code))
        worker.start(); assert fake.started.wait(2)
        assert client.post("/dev/web-commercial/logout", headers=auth).status_code == 204
        fake.release.set(); worker.join(3)
        assert result == [409]
