import os
import subprocess
import sys

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from mike_app.core.settings import Settings, validate_episode_journal_settings
from mike_app.runtime.postgresql_episode_journal import metadata


def make_settings(mode: str | None, url: str | None = None) -> Settings:
    return Settings(
        app_name="mike",
        app_version="0.1.0",
        environment="test",
        openai_api_key=None,
        openai_model=None,
        episode_journal=mode,
        database_url=url,
        test_database_url=None,
    )


@pytest.mark.parametrize("mode", [None, "", "sqlite", "POSTGRES"])
def test_journal_selection_must_be_explicit_and_valid(mode: str | None) -> None:
    with pytest.raises(ValueError, match="explicitly set"):
        validate_episode_journal_settings(make_settings(mode))


def test_memory_requires_no_database_url() -> None:
    validate_episode_journal_settings(make_settings("memory"))


def test_postgres_requires_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        validate_episode_journal_settings(make_settings("postgres"))


def test_postgres_accepts_explicit_database_url() -> None:
    validate_episode_journal_settings(
        make_settings("postgres", "postgresql+psycopg://example.invalid/test")
    )


def test_importing_postgresql_module_does_not_connect() -> None:
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", "import mike_app.runtime.postgresql_episode_journal"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_metadata_contains_only_approved_journal_tables() -> None:
    assert set(metadata.tables) == {"episodes", "events"}


def test_events_metadata_has_approved_types_and_constraints() -> None:
    events = metadata.tables["events"]
    assert events.c.sequence.nullable is False
    assert events.c.journal_position.identity is not None
    assert events.c.payload.type.__class__.__name__ == "JSONB"
    assert any(
        tuple(constraint.columns.keys()) == ("episode_id", "sequence")
        for constraint in events.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    assert any(isinstance(constraint, ForeignKeyConstraint) for constraint in events.constraints)
    checks = {str(constraint.sqltext) for constraint in events.constraints if isinstance(constraint, CheckConstraint)}
    assert {"sequence >= 0", "schema_version > 0"} <= checks


def test_episodes_metadata_supports_tenant_safe_foreign_key() -> None:
    episodes = metadata.tables["episodes"]
    assert episodes.c.episode_id.primary_key is True
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(constraint.columns.keys()) == ("episode_id", "tenant_id")
        for constraint in episodes.constraints
    )


def test_alembic_is_not_called_by_application_import() -> None:
    source = open("mike_app/main.py", encoding="utf8").read()
    assert "alembic" not in source.lower()
    assert "create_all" not in source


def test_memory_resources_are_created_only_during_lifespan() -> None:
    from fastapi.testclient import TestClient
    from mike_app.main import create_app

    application = create_app(make_settings("memory"))
    assert not hasattr(application.state, "episode_coordinator")
    with TestClient(application):
        assert application.state.episode_coordinator is not None
