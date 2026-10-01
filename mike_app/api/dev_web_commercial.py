from __future__ import annotations

import secrets
import os
from typing import Any

from fastapi import APIRouter, Body, Header, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

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
        _origin(request, require_origin=False)
        headers = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache", "Vary": "Cookie"}
        csrf = ""
        token = request.cookies.get(COOKIE)
        if token:
            try:
                csrf = request.app.state.web_sessions.get(token).csrf
            except WebSessionError:
                response = HTMLResponse(_PAGE.replace("__MIKE_CSRF__", ""), headers=headers)
                response.delete_cookie(COOKIE, path="/dev/", secure=False, httponly=True, samesite="strict")
                return response
        return HTMLResponse(_PAGE.replace("__MIKE_CSRF__", csrf), headers=headers)
    except WebSessionError as exc:
        return _error(exc)


_PAGE = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta id="mike-csrf" data-csrf="__MIKE_CSRF__">
<title>MIKE · Cotización local</title><style>
body{font:16px system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#202124}main{display:grid;gap:1rem}section{border:1px solid #ddd;border-radius:8px;padding:1rem}button{margin:.25rem;padding:.45rem .7rem}input{padding:.45rem;margin:.25rem}pre{white-space:pre-wrap;background:#f5f5f5;padding:.7rem}.muted{color:#666}.danger{color:#a00}.ok{color:#064}
</style></head><body><main><h1>MIKE · consulta comercial local</h1>
<p><strong>No crea pedidos ni reserva stock.</strong> La cotización usa una instantánea de captura.</p>
<section id="login"><h2>Acceso</h2><label>Código bootstrap <input id="code" autocomplete="one-time-code"></label><button id="bootstrap">Entrar</button><p id="loginMsg" class="danger"></p></section>
<section id="app" hidden><p id="capture" class="muted"></p><button id="logout">Cerrar sesión</button>
<h2>Solicitud</h2><input id="phrase" size="55" placeholder="quiero 2 de Producto A"><button id="interpret">Interpretar</button><p id="message"></p>
<h2>Resolución de la frase</h2><div id="mentions"></div>
<h2>Búsqueda manual</h2><input id="query" placeholder="nombre o código"><button id="search">Buscar</button><div id="manualResults"></div>
<h2>Propuesta</h2><div id="proposal"></div><button id="prepare" disabled>Preparar propuesta</button><button id="confirm" disabled>Confirmar</button><button id="cancel" disabled>Cancelar</button>
<h2>Carrito confirmado</h2><div id="cart"></div><button id="quote">Cotizar</button><div id="quoteResult"></div></section></main>
<script>
const $=id=>document.getElementById(id);let csrf=$('mike-csrf').dataset.csrf||null,revision=null,proposal=null,searchId=null,latest=0,quotedRevision=null,resolvedMentions=new Set(),mentionCount=0,productNames={};
const headers=()=>({'Content-Type':'application/json','X-MIKE-CSRF':csrf});
async function api(path,body,method='POST'){const id=++latest;const r=await fetch(path,{method,headers:headers(),body:method==='GET'?undefined:JSON.stringify(body)});const data=await r.json().catch(()=>({error:{code:'respuesta_invalida'}}));if(id!==latest)return {stale:true};if(!r.ok)throw data.error||{code:'error'};return data}
function msg(x,good=false){$('message').textContent=x;$('message').className=good?'ok':'danger'}
function renderState(s){if(s.csrf)csrf=s.csrf;const changed=revision!==null&&revision!==s.cart_revision;revision=s.cart_revision;if(changed){quotedRevision=null;$('quoteResult').textContent='La cotización anterior quedó invalidada por un cambio del carrito.'}const cart=$('cart');cart.replaceChildren();if(!s.lines.length)cart.textContent='Vacío';for(const line of s.lines){const row=document.createElement('div');row.textContent=`ID ${line.product_id}: ${line.quantity} `;const q=document.createElement('input');q.type='number';q.min='1';q.max='10000';q.value=line.quantity;const change=document.createElement('button');change.textContent='Modificar';change.onclick=()=>mutate('/dev/web-commercial/cart/modify',{product_id:line.product_id,quantity:Number(q.value),expected_revision:revision});const remove=document.createElement('button');remove.textContent='Quitar';remove.onclick=()=>mutate('/dev/web-commercial/cart/remove',{product_id:line.product_id,expected_revision:revision});row.append(q,change,remove);cart.append(row)}if(s.proposal_id)$('proposal').textContent='Propuesta pendiente: '+s.proposal_id;else if(!proposal)$('proposal').textContent='Sin propuesta pendiente'}
async function state(){try{const s=await api('/dev/web-commercial/state',null,'GET');if(s&&!s.stale){renderState(s);$('capture').textContent='Captura: '+(s.capture_at||'la instantánea configurada')+' · Los precios corresponden a esa captura.'}}catch(e){csrf=null;$('login').hidden=false;$('app').hidden=true;$('loginMsg').textContent='Sesión no disponible: '+(e.code||'error')}}
async function mutate(path,body){try{const d=await api(path,body);if(!d.stale){await state();msg('Carrito actualizado.',true)}}catch(e){msg('Carrito: '+e.code);await state()}}
$('bootstrap').onclick=async()=>{try{const r=await fetch('/dev/web-commercial/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('code').value})});const d=await r.json();if(!r.ok)throw d.error;csrf=d.csrf;$('login').hidden=true;$('app').hidden=false;await state()}catch(e){$('loginMsg').textContent='No se pudo iniciar: '+(e.code||'error')}};
 $('interpret').onclick=async()=>{try{const d=await api('/dev/web-commercial/interpret',{text:$('phrase').value});if(d.stale)return;resolvedMentions=new Set();mentionCount=d.mentions.length;$('prepare').disabled=true;const box=$('mentions');box.replaceChildren();d.mentions.forEach((m,i)=>{const row=document.createElement('section');row.dataset.mentionIndex=i;const title=document.createElement('div');title.textContent=`Mención ${i+1}: ${m.quantity} ${m.unit_text||''} ${m.product_text}`;const status=document.createElement('span');status.textContent=' · pendiente';const results=document.createElement('div');results.className='mention-results';const b=document.createElement('button');b.textContent='Buscar esta mención';b.onclick=()=>searchMention(i,row,results,status,m.product_text,null);row.append(title,status,b,results);box.append(row)});msg('Interpretación lista. Busca cada mención y selecciona por ID.',true)}catch(e){msg('Interpretación: '+e.code);await state()}};
async function searchMention(index,row,results,status,query,cursor){try{const d=await api('/dev/web-commercial/search',{query,cursor,limit:10,mention_index:index});if(d.stale)return;const sid=d.search_id;results.replaceChildren();for(const p of d.products){const b=document.createElement('button');b.textContent=`Seleccionar ID ${p.product_id} · ${p.name} · ${p.unit}`;b.onclick=async()=>{await select(p.product_id,sid);resolvedMentions.add(index);status.textContent=' · seleccionado ID '+p.product_id;$('prepare').disabled=resolvedMentions.size!==mentionCount};results.append(b)}if(d.next_cursor){const next=document.createElement('button');next.textContent='Siguiente página';next.onclick=()=>searchMention(index,row,results,status,query,d.next_cursor);results.append(next)}}catch(e){status.textContent=' · error recuperable';msg('Búsqueda: '+e.code);await state()}}
$('search').onclick=async()=>{try{const d=await api('/dev/web-commercial/search',{query:$('query').value,cursor:null,limit:10});if(d.stale)return;searchId=d.search_id;const box=$('manualResults');box.replaceChildren(...d.products.map(p=>{const b=document.createElement('button');b.textContent=`Seleccionar ID ${p.product_id} · ${p.name} · ${p.unit}`;b.onclick=()=>select(p.product_id,d.search_id);return b}));if(d.next_cursor){const b=document.createElement('button');b.textContent='Siguiente página';b.onclick=async()=>{const n=await api('/dev/web-commercial/search',{query:$('query').value,cursor:d.next_cursor,limit:10});if(!n.stale){searchId=n.search_id;$('manualResults').textContent=n.products.map(p=>`ID ${p.product_id} · ${p.name} · ${p.unit}`).join(' · ')}};box.append(b)}}catch(e){msg('Búsqueda: '+e.code);await state()}};
async function select(id,sid=searchId){try{const d=await api('/dev/web-commercial/select',{search_id:sid,product_id:id});if(d.stale)return;if(d.name)productNames[id]=d.name;msg('Producto seleccionado: ID '+id,true)}catch(e){msg('Selección: '+e.code);await state()}}
$('prepare').onclick=async()=>{try{proposal=await api('/dev/web-commercial/proposals',{});$('proposal').textContent=proposal.lines.map(x=>`${x.operation} ID ${x.product_id}: ${x.previous_quantity??'—'} → ${x.quantity} ${x.unit}`).join(' · ');$('confirm').disabled=false;$('cancel').disabled=false}catch(e){msg('Propuesta: '+e.code)}};
$('confirm').onclick=async()=>{try{await api('/dev/web-commercial/proposals/'+proposal.proposal_id+'/confirm',{expected_revision:proposal.cart_revision});proposal=null;$('confirm').disabled=true;$('cancel').disabled=true;await state();msg('Carrito confirmado. Cotizar es una acción separada.',true)}catch(e){msg('Confirmación: '+e.code);await state()}};
$('cancel').onclick=async()=>{try{await api('/dev/web-commercial/proposals/'+proposal.proposal_id+'/cancel',{});proposal=null;$('confirm').disabled=true;$('cancel').disabled=true;msg('Propuesta cancelada; carrito conservado.',true)}catch(e){msg('Cancelación: '+e.code)}};
function productLabel(id){return productNames[id]||`Producto ID ${id}`}
function quoteComponents(components){return components.map(c=>`${productLabel(c.product_id)} × ${c.quantity}`).join(', ')}
function renderQuote(q){const box=$('quoteResult');box.replaceChildren();const title=document.createElement('h3');title.textContent=`Total ${q.currency||'ARS'} ${q.total}`;box.append(title);const notice=document.createElement('p');notice.textContent='No crea pedidos ni reserva stock.';box.append(notice);const dates=document.createElement('p');dates.textContent=`Fecha de cálculo: ${q.calculated_at} · Fecha comercial: ${q.commercial_date}`;box.append(dates);const lines=document.createElement('ul');for(const line of (q.lines||[])){const item=document.createElement('li');item.textContent=`${productLabel(line.product_id)} × ${line.quantity} ${line.unit||''}`;lines.append(item)}box.append(lines);const normal=document.createElement('div');normal.textContent='Desglose normal';for(const item of (q.pricing_breakdown||[])){const p=document.createElement('p');p.textContent=`${item.kind}, ${item.quantity} unidades (${item.package_size} por aplicación), ${item.applications} aplicaciones, importe ${item.subtotal}`;normal.append(p)}box.append(normal);for(const [label,entries] of [['Promociones aplicadas',q.promotions_applied||[]],['Grupos mixtos aplicados',q.mixed_groups_applied||[]]]){const section=document.createElement('div');section.textContent=label;for(const entry of entries){const p=document.createElement('p');p.textContent=`${entry.name||label} · veces ${entry.times} · importe ${entry.subtotal} · componentes: ${quoteComponents(entry.components||[])}`;section.append(p)}box.append(section)}const warnings=document.createElement('p');warnings.textContent=`Advertencias de stock: ${(q.stock_warnings||[]).map(w=>w.code).join(', ')||'ninguna'}`;box.append(warnings);const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='JSON original';const raw=document.createElement('pre');raw.textContent=JSON.stringify(q,null,2);details.append(summary,raw);box.append(details)}
 $('quote').onclick=async()=>{try{const d=await api('/dev/web-commercial/quote',{expected_revision:revision});if(d.stale)return;quotedRevision=d.cart_revision;renderQuote(d.quote)}catch(e){$('quoteResult').textContent='Cotización no disponible: '+e.code;await state()}};
$('logout').onclick=async()=>{try{await api('/dev/web-commercial/logout',{});location.reload()}catch(e){msg('Cierre: '+e.code)}};
if(csrf){$('login').hidden=true;$('app').hidden=false;state();}
</script></body></html>'''


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
        return {"csrf": session.csrf, "cart_revision": session.cart.revision, "lines": session.cart.items(),
                "proposal_id": str(proposal.proposal_id) if proposal else None,
                "capture_at": os.getenv("MIKE_WEB_CAPTURE_AT")}
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
