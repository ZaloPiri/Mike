from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from mike_app.commercial.gestar_client import (
    CommercialClientError,
    CommercialConfigurationError,
    CommercialIdentityError,
    CommercialProtocolError,
    GestarCommercialClient,
    GestarCommercialConfig,
)

router = APIRouter()


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": "Consulta comercial no disponible"}})


@router.post("/dev/commercial/quote")
def quote(request: Request, body: dict[str, Any] = Body(...), x_mike_development_key: str | None = Header(default=None)) -> Any:
    settings = request.app.state.settings
    if settings.environment != "development" or not settings.gestar_commercial_enabled:
        return _error(403, "development_only_disabled")
    if not settings.gestar_dev_key or not x_mike_development_key or not secrets.compare_digest(x_mike_development_key, settings.gestar_dev_key):
        return _error(401, "local_authentication_failed")
    try:
        if set(body) != {"items"} or not isinstance(body["items"], list):
            raise CommercialProtocolError("invalid request")
        config = GestarCommercialConfig.from_settings(settings)
        client = getattr(request.app.state, "gestar_commercial_client", None)
        if client is None:
            client = GestarCommercialClient(config)
            request.app.state.gestar_commercial_client = client
        result = client.quote(body["items"])
        return result
    except CommercialConfigurationError as exc:
        return _error(exc.status_code, exc.code)
    except CommercialIdentityError as exc:
        return _error(exc.status_code, exc.code)
    except CommercialProtocolError as exc:
        return _error(400, "invalid_request")
    except CommercialClientError as exc:
        return _error(exc.status_code, exc.code)
