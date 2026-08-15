import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    environment: str
    openai_api_key: str | None
    openai_model: str | None
    episode_journal: str | None
    database_url: str | None
    test_database_url: str | None


def get_settings() -> Settings:
    return Settings(
        app_name="mike",
        app_version="0.1.0",
        environment=os.getenv("MIKE_ENV", "development"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL"),
        episode_journal=os.getenv("MIKE_EPISODE_JOURNAL"),
        database_url=os.getenv("DATABASE_URL"),
        test_database_url=os.getenv("MIKE_TEST_DATABASE_URL"),
    )


def validate_episode_journal_settings(settings: Settings) -> None:
    if settings.episode_journal not in {"memory", "postgres"}:
        raise ValueError(
            "MIKE_EPISODE_JOURNAL must be explicitly set to memory or postgres"
        )
    if settings.episode_journal == "postgres" and not settings.database_url:
        raise ValueError("DATABASE_URL is required when MIKE_EPISODE_JOURNAL=postgres")
