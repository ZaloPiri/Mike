"""Ephemeral, development-only web sessions for the supervised quote flow."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from .cart import CartProposalError, TerminalCart
from .catalog_resolution import CatalogResolution
from .language_interpreter import interpret


class WebSessionError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass
class WebSession:
    token: str
    csrf: str
    created_at: float
    last_used: float
    cart: TerminalCart
    resolution: CatalogResolution | None = None
    searches: dict[str, tuple[int | None, object]] = field(default_factory=dict)
    proposal: object | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class WebSessionManager:
    def __init__(self, catalog_client, quote_client, *, max_sessions: int = 4, idle_seconds: int = 1800):
        self.catalog_client = catalog_client
        self.quote_client = quote_client
        self.max_sessions = max_sessions
        self.idle_seconds = idle_seconds
        self._sessions: dict[str, WebSession] = {}
        self._bootstrap: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue_bootstrap_code(self) -> str:
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._bootstrap[code] = time.monotonic() + 300
        return code

    def bootstrap(self, code: str) -> WebSession:
        now = time.monotonic()
        with self._lock:
            expiry = self._bootstrap.get(code)
            if not isinstance(code, str) or expiry is None or expiry < now:
                self._bootstrap.pop(code, None)
                raise WebSessionError("web_bootstrap_failed", 401)
            self._bootstrap.pop(code)
            self._expire_locked(now)
            if len(self._sessions) >= self.max_sessions:
                raise WebSessionError("session_limit", 429)
            token = secrets.token_urlsafe(32)
            session = WebSession(token, secrets.token_urlsafe(24), now, now, TerminalCart([]))
            self._sessions[token] = session
            return session

    def get(self, token: str) -> WebSession:
        with self._lock:
            self._expire_locked(time.monotonic())
            session = self._sessions.get(token)
            if session is None:
                raise WebSessionError("web_session_required", 401)
            session.last_used = time.monotonic()
            return session

    def logout(self, token: str) -> None:
        with self._lock:
            if token not in self._sessions:
                raise WebSessionError("web_session_required", 401)
            self._sessions.pop(token)

    def _expire_locked(self, now: float) -> None:
        for token, session in list(self._sessions.items()):
            if now - session.last_used > self.idle_seconds:
                self._sessions.pop(token, None)

    @contextmanager
    def session_lock(self, session: WebSession):
        if not session.lock.acquire(timeout=1.0):
            raise WebSessionError("session_busy", 409)
        try:
            yield
        finally:
            session.lock.release()

    @staticmethod
    def interpretation(session: WebSession, text: str) -> object:
        result = interpret(text)
        if result.status.value != "interpretable":
            raise WebSessionError("interpretation_invalid", 422)
        session.resolution = CatalogResolution.from_interpretation(result)
        session.searches.clear()
        session.proposal = None
        return result

    def manual_search(self, session: WebSession, query: str, cursor: str | None, limit: int) -> tuple[str, object]:
        page = self.catalog_client.list_products(query, limit=limit, cursor=cursor)
        search_id = secrets.token_urlsafe(16)
        session.searches[search_id] = (None, page)
        return search_id, page

    def select(self, session: WebSession, search_id: str, product_id: object) -> object:
        current = session.searches.get(search_id)
        if current is None:
            raise WebSessionError("selection_not_current")
        _, page = current
        if isinstance(product_id, bool) or not isinstance(product_id, int):
            raise WebSessionError("invalid_input", 422)
        product = next((item for item in page.products if item.product_id == product_id), None)
        if product is None:
            raise WebSessionError("selection_not_current")
        return product

    @staticmethod
    def fingerprint(items: list[dict[str, int]]) -> str:
        return hashlib.sha256(repr(items).encode("utf-8")).hexdigest()
