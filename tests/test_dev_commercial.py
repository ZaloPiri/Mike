from fastapi.testclient import TestClient

from mike_app.core.settings import Settings
from mike_app.main import create_app


def _settings(**changes):
    values = dict(app_name="mike", app_version="0.1.0", environment="development",
                  openai_api_key=None, openai_model=None, episode_journal="memory",
                  database_url=None, test_database_url=None, gestar_dev_key="local-only")
    values.update(changes)
    return Settings(**values)


def test_dev_commercial_is_disabled_by_default_and_requires_local_key():
    with TestClient(create_app(_settings())) as client:
        assert client.post("/dev/commercial/quote", json={"items": []}).status_code == 403
    with TestClient(create_app(_settings(gestar_commercial_enabled=True))) as client:
        response = client.post("/dev/commercial/quote", json={"items": []})
        assert response.status_code == 401


def test_dev_commercial_rejects_tenant_id_before_any_source_call():
    settings = _settings(gestar_commercial_enabled=True)
    with TestClient(create_app(settings)) as client:
        response = client.post("/dev/commercial/quote", headers={"X-MIKE-Development-Key": "local-only"},
                               json={"tenant_id": "caller", "items": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
