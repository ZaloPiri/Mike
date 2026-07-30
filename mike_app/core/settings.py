import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    environment: str
    openai_api_key: str | None
    openai_model: str | None


def get_settings() -> Settings:
    return Settings(
        app_name="mike",
        app_version="0.1.0",
        environment=os.getenv("MIKE_ENV", "development"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL"),
    )
