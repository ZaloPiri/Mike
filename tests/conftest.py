import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mike_app.core.settings import Settings


@pytest.fixture(scope="module")
def memory_app() -> FastAPI:
    from mike_app.main import create_app

    return create_app(
        Settings(
            app_name="mike",
            app_version="0.1.0",
            environment="test",
            openai_api_key=None,
            openai_model=None,
            episode_journal="memory",
            database_url=None,
            test_database_url=None,
        )
    )


@pytest.fixture(scope="module")
def memory_client(memory_app: FastAPI):
    with TestClient(memory_app) as client:
        yield client
