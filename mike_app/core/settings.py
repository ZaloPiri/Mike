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
    delivery_run_once_enabled: bool = False
    gestar_commercial_enabled: bool = False
    gestar_base_url: str | None = None
    gestar_bearer_token: str | None = None
    gestar_installation_id: str | None = None
    gestar_business_id: str | None = None
    gestar_tenant_id: str | None = None
    gestar_dev_key: str | None = None
    web_control_key: str | None = None


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
        delivery_run_once_enabled=os.getenv("MIKE_DELIVERY_RUN_ONCE", "false").lower() == "true",
        gestar_commercial_enabled=os.getenv("MIKE_GESTAR_COMMERCIAL_ENABLED", "false").lower() == "true",
        gestar_base_url=os.getenv("MIKE_GESTAR_BASE_URL"),
        gestar_bearer_token=os.getenv("MIKE_GESTAR_BEARER_TOKEN"),
        gestar_installation_id=os.getenv("MIKE_GESTAR_INSTALLATION_ID"),
        gestar_business_id=os.getenv("MIKE_GESTAR_BUSINESS_ID"),
        gestar_tenant_id=os.getenv("MIKE_GESTAR_TENANT_ID"),
        gestar_dev_key=os.getenv("MIKE_GESTAR_DEV_KEY"),
        web_control_key=os.getenv("MIKE_WEB_CONTROL_KEY"),
    )


def validate_episode_journal_settings(settings: Settings) -> None:
    if settings.episode_journal not in {"memory", "postgres"}:
        raise ValueError(
            "MIKE_EPISODE_JOURNAL must be explicitly set to memory or postgres"
        )
    if settings.episode_journal == "postgres" and not settings.database_url:
        raise ValueError("DATABASE_URL is required when MIKE_EPISODE_JOURNAL=postgres")
    if settings.delivery_run_once_enabled and settings.environment != "development":
        raise ValueError("MIKE_DELIVERY_RUN_ONCE can only be enabled in development")
