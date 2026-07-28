from fastapi import APIRouter
from pydantic import BaseModel

from mike_app.core.settings import get_settings


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )
