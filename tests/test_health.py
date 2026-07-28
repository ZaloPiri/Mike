from fastapi.testclient import TestClient

from mike_app.main import app


client = TestClient(app)


def test_health_endpoint_returns_expected_payload() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mike",
        "version": "0.1.0",
    }
