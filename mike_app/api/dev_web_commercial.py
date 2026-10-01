from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Body, Header, Request, Response
from fastapi.responses import JSONResponse

from mike_app.commercial.catalog_resolution import CatalogResolution, MentionResolution, ResolutionStatus
from mike_app.commercial.cart import CartProposalError
from mike_app.commercial.gestar_client import CommercialClientError, GestarCommercialClient, GestarCommercialConfig
from mike_app.commercial.web_sessions import WebSessionError

router = APIRouter(prefix="/dev/web-commercial")
COOKIE = "mike_web_session"
CSRF_HEADER = "X-MIKE-CSRF"
CONTROL_HEADER = "X-MIKE-Control-Key"


def _error(exc: WebSessionError) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": "Solicitud web no disponible"}}, status_code=exc.status)


def _settings(request: Request):
    settings = request.app.state.settings
    if settings.environment != "development" or not settings.gestar_commercial_enabled:
        raise WebSessionError("development_only_disabled", 403)
    return settings


def _manager(request: Request):
    manager = request.app.state.web_sessions
    if manager.catalog_client is None:
        config = GestarCommercialConfig.from_settings(request.app.state.settings)
        client = request.app.state.gestar_commercial_client
        if client is None:
            client = GestarCommercialClient(config)
            request.app.state.gestar_commercial_client = client
        manager.catalog_client = client
        manager.quote_client = client
    return manager


def _origin(request: Request, *, bootstrap: bool = False, require_origin: bool = True) -> None:
    host = request.headers.get("host", "")
    if not (host.startswith("127.0.0.1:") or host.startswith("localhost:")):
        raise WebSessionError("origin_not_allowed", 403)
    origin = request.headers.get("origin")
    if bootstrap and origin != f"http://{host}":
        raise WebSessionError("origin_not_allowed", 403)
    if not bootstrap and require_origin and origin != f"http://{host}":
        raise WebSessionError("origin_not_allowed", 403)


def _session(request: Request, csrf: str | None = Header(default=None, alias=CSRF_HEADER)):
    manager = request.app.state.web_sessions
    token = request.cookies.get(COOKIE)
    csrf = request.headers.get(CSRF_HEADER)
    if not token or not csrf:
        raise WebSessionError("web_session_required", 401)
    session = manager.get(token)
    if not secrets.compare_digest(csrf, session.csrf):
        raise WebSessionError("csrf_invalid", 403)
    return session


@router.get("")
def initial(request: Request):
    try:
        _settings(request)
        _origin(request, bootstrap=False) if request.headers.get("origin") else None
        return {"bootstrap_required": True}
    except WebSessionError as exc:
        return _error(exc)


@router.post("/control/bootstrap-code")
def issue_code(request: Request, x_mike_control_key: str | None = Header(default=None, alias=CONTROL_HEADER)):
    try:
        _settings(request)
        _origin(request, bootstrap=True) if request.headers.get("origin") else None
        expected = request.app.state.settings.web_control_key
        if not expected or not x_mike_control_key or not secrets.compare_digest(expected, x_mike_control_key):
            raise WebSessionError("control_auth_failed", 401)
        return {"code": request.app.state.web_sessions.issue_bootstrap_code()}
    except WebSessionError as exc:
        return _error(exc)


@router.post("/bootstrap")
def bootstrap(request: Request, body: dict[str, Any] = Body(...), response: Response = None):
    try:
        _settings(request)
        _origin(request, bootstrap=True)
        if set(body) != {"code"} or not isinstance(body["code"], str):
            raise WebSessionError("web_bootstrap_failed", 401)
        session = request.app.state.web_sessions.bootstrap(body["code"])
        result = JSONResponse({"authenticated": True, "csrf": session.csrf})
        result.set_cookie(COOKIE, session.token, httponly=True, secure=False, samesite="strict", path="/dev/")
        return result
    except WebSessionError as exc:
        return _error(exc)


@router.get("/state")
def state(request: Request):
    try:
        _settings(request); _origin(request, require_origin=False); session = _session(request)
        proposal = session.proposal
        return {"cart_revision": session.cart.revision, "lines": session.cart.items(),
                "proposal_id": str(proposal.proposal_id) if proposal else None}
    except WebSessionError as exc:
        return _error(exc)


@router.post("/interpret")
def interpret_route(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        if set(body) != {"text"} or not isinstance(body["text"], str): raise WebSessionError("invalid_input", 422)
        with request.app.state.web_sessions.session_lock(session):
            result = request.app.state.web_sessions.interpretation(session, body["text"])
        return {"status": result.status.value, "mentions": [
            {"product_text": m.product_text, "quantity": m.quantity,
             "quantity_text": m.quantity_text, "unit_text": m.unit_text}
            for m in result.mentions
        ]}
    except WebSessionError as exc:
        return _error(exc)


@router.post("/search")
def search(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        if set(body) - {"query", "cursor", "limit", "mention_index"} != set() or set(body) & {"query", "cursor", "limit"} != {"query", "cursor", "limit"} or not isinstance(body["query"], str): raise WebSessionError("invalid_input", 422)
        with request.app.state.web_sessions.session_lock(session):
            manager = _manager(request)
            mention_index = body.get("mention_index")
            if mention_index is not None:
                if session.resolution is None or not isinstance(mention_index, int) or not 0 <= mention_index < len(session.resolution.mentions):
                    raise WebSessionError("search_not_current")
                session.resolution = session.resolution.search(manager.catalog_client, mention_index, limit=body["limit"])
                current = session.resolution.mentions[mention_index]
                if current.page is None:
                    error = current.error
                    if isinstance(error, CommercialClientError):
                        raise WebSessionError(error.code, error.status_code)
                    raise WebSessionError("commercial_source_unreachable", 502)
                page = current.page
                search_id = secrets.token_urlsafe(16)
                session.searches[search_id] = (mention_index, page)
            else:
                search_id, page = manager.manual_search(session, body["query"], body["cursor"], body["limit"])
        return {"search_id": search_id, "products": [p.__dict__ for p in page.products], "next_cursor": page.next_cursor}
    except WebSessionError as exc: return _error(exc)
    except CommercialClientError as exc: return _error(WebSessionError(exc.code, exc.status_code))
    except Exception: return _error(WebSessionError("commercial_source_unreachable", 502))


@router.post("/select")
def select(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        with request.app.state.web_sessions.session_lock(session):
            search = session.searches.get(body.get("search_id"))
            product = request.app.state.web_sessions.select(session, body.get("search_id"), body.get("product_id"))
            session.cart.allowed_ids.add(product.product_id)
            if search and search[0] is not None and session.resolution is not None:
                session.resolution = session.resolution.select(search[0], body.get("product_id"))
        return {"product_id": product.product_id, "name": product.name, "unit": product.unit}
    except WebSessionError as exc: return _error(exc)


@router.post("/proposals")
def prepare_proposal(request: Request):
    try:
        _settings(request); _origin(request); session = _session(request)
        if session.resolution is None:
            raise WebSessionError("invalid_input", 422)
        with request.app.state.web_sessions.session_lock(session):
            proposal = session.cart.prepare(session.resolution)
            session.proposal = proposal
        return {"proposal_id": str(proposal.proposal_id), "cart_id": str(proposal.cart_id),
                "cart_revision": proposal.cart_revision,
                "lines": [{"product_id": line.product_id, "name": line.name,
                            "unit": line.unit, "quantity": line.quantity,
                            "operation": line.operation,
                            "previous_quantity": line.previous_quantity} for line in proposal.lines]}
    except WebSessionError as exc: return _error(exc)
    except CartProposalError:
        return _error(WebSessionError("invalid_input", 422))


@router.post("/proposals/{proposal_id}/confirm")
def confirm_proposal(proposal_id: str, request: Request, body: dict[str, Any] = Body(...)):
    try:
        from uuid import UUID
        _settings(request); _origin(request); session = _session(request)
        with request.app.state.web_sessions.session_lock(session):
            if session.proposal is None or str(session.proposal.proposal_id) != proposal_id:
                raise WebSessionError("proposal_stale")
            changed = session.cart.confirm(UUID(proposal_id), body.get("expected_revision"))
            session.proposal = None
        return {"changed": changed, "cart_revision": session.cart.revision, "lines": session.cart.items()}
    except WebSessionError as exc: return _error(exc)
    except (ValueError, CartProposalError): return _error(WebSessionError("proposal_stale"))


@router.post("/proposals/{proposal_id}/cancel")
def cancel_proposal(proposal_id: str, request: Request):
    try:
        from uuid import UUID
        _settings(request); _origin(request); session = _session(request)
        with request.app.state.web_sessions.session_lock(session):
            session.cart.cancel(UUID(proposal_id)); session.proposal = None
        return Response(status_code=204)
    except WebSessionError as exc: return _error(exc)
    except (ValueError, CartProposalError): return _error(WebSessionError("proposal_stale"))


@router.post("/quote")
def quote(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        with request.app.state.web_sessions.session_lock(session):
            if body.get("expected_revision") != session.cart.revision:
                raise WebSessionError("cart_revision_conflict")
            items = session.cart.items()
            if not items: raise WebSessionError("empty_cart")
            fingerprint = request.app.state.web_sessions.fingerprint(items)
        result = _manager(request).quote_client.quote(items)
        with request.app.state.web_sessions.session_lock(session):
            if session.token not in request.app.state.web_sessions._sessions or session.cart.revision != body["expected_revision"] or request.app.state.web_sessions.fingerprint(session.cart.items()) != fingerprint:
                raise WebSessionError("quote_stale")
        return {"cart_revision": body["expected_revision"], "cart_fingerprint": fingerprint, "quote": result}
    except WebSessionError as exc: return _error(exc)
    except CommercialClientError as exc: return _error(WebSessionError(exc.code, exc.status_code))
    except Exception: return _error(WebSessionError("commercial_source_unreachable", 502))


@router.post("/cart/add")
def cart_add(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        if not isinstance(body.get("product_id"), int) or isinstance(body.get("product_id"), bool): raise WebSessionError("invalid_input", 422)
        if not isinstance(body.get("quantity"), int) or isinstance(body.get("quantity"), bool): raise WebSessionError("invalid_input", 422)
        selection = body.get("selection_id")
        if selection not in session.searches: raise WebSessionError("selection_not_current")
        with request.app.state.web_sessions.session_lock(session):
            if body.get("expected_revision") != session.cart.revision: raise WebSessionError("cart_revision_conflict")
            request.app.state.web_sessions.select(session, selection, body["product_id"])
            session.cart.allowed_ids.add(body["product_id"])
            session.cart.add(body["product_id"], body["quantity"], replace=bool(body.get("replace", False)))
        return {"cart_revision": session.cart.revision, "lines": session.cart.items()}
    except WebSessionError as exc: return _error(exc)
    except (ValueError, KeyError): return _error(WebSessionError("invalid_input", 422))


@router.post("/cart/modify")
def cart_modify(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        with request.app.state.web_sessions.session_lock(session):
            if body.get("expected_revision") != session.cart.revision: raise WebSessionError("cart_revision_conflict")
            session.cart.modify(body.get("product_id"), body.get("quantity"))
        return {"cart_revision": session.cart.revision, "lines": session.cart.items()}
    except WebSessionError as exc: return _error(exc)
    except (ValueError, KeyError): return _error(WebSessionError("invalid_input", 422))


@router.post("/cart/remove")
def cart_remove(request: Request, body: dict[str, Any] = Body(...)):
    try:
        _settings(request); _origin(request); session = _session(request)
        with request.app.state.web_sessions.session_lock(session):
            if body.get("expected_revision") != session.cart.revision: raise WebSessionError("cart_revision_conflict")
            session.cart.remove(body.get("product_id"))
        return {"cart_revision": session.cart.revision, "lines": session.cart.items()}
    except WebSessionError as exc: return _error(exc)
    except (ValueError, KeyError): return _error(WebSessionError("invalid_input", 422))


@router.post("/logout")
def logout(request: Request):
    try:
        _settings(request); _origin(request); _session(request)
        request.app.state.web_sessions.logout(request.cookies[COOKIE])
        return Response(status_code=204)
    except WebSessionError as exc: return _error(exc)
