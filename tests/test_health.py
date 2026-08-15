import pytest

app = None
client = None


@pytest.fixture(scope="module", autouse=True)
def bind_memory_app(memory_app, memory_client):
    global app, client
    app = memory_app
    client = memory_client
    yield


def test_health_endpoint_returns_expected_payload() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mike",
        "version": "0.1.0",
    }
