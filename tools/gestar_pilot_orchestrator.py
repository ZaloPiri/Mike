"""Run a supervised MIKE session against a temporary SQLite snapshot."""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


REQUIRED_SCHEMA = {
    "categories": {"id", "nombre"},
    "products": {"id", "nombre", "categoria_id", "codigo_interno", "unidad_venta", "controla_stock", "activo", "orden_venta"},
    "price_lists": {"id", "nombre", "fecha_inicio", "fecha_fin", "activa"},
    "product_prices": {"id", "price_list_id", "product_id", "precio_unitario", "precio_media_docena", "precio_docena"},
    "promotions": {"id", "nombre", "precio_final", "fecha_inicio", "fecha_fin", "activa", "prioridad", "repetible"},
    "promotion_items": {"id", "promotion_id", "product_id", "cantidad"},
    "mixed_price_groups": {"id", "nombre", "precio_media_docena", "precio_docena", "activo"},
    "mixed_price_group_items": {"id", "group_id", "product_id"},
    "product_stock_configs": {"id", "product_id", "permitir_stock_negativo", "stock_minimo", "activo"},
    "product_sale_mode_configs": {"product_id", "hecho_en_el_momento"},
    "product_stocks": {"id", "product_id", "cantidad_actual"},
}
EXPECTED_GESTAR_HEAD = "1a2a7245b019eadfa1b950de5f9e82a48822be55"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _existing_source(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise RuntimeError("La base fuente no existe o no es un archivo")
    return path.resolve()


def backup_source(source: Path, destination: Path, timeout_seconds: float = 30.0) -> None:
    started = time.monotonic()
    source_uri = source.as_uri() + "?mode=ro"
    read_connection = sqlite3.connect(source_uri, uri=True, timeout=0.1)
    try:
        while True:
            if time.monotonic() - started > timeout_seconds:
                raise TimeoutError("La captura SQLite excedió el plazo")
            write_connection = sqlite3.connect(destination)
            try:
                def progress(status, remaining, total):
                    if time.monotonic() - started > timeout_seconds:
                        raise TimeoutError("La captura SQLite excedió el plazo")

                read_connection.backup(write_connection, pages=256, progress=progress, sleep=0.05)
                write_connection.commit()
                return
            except sqlite3.OperationalError as exc:
                if "busy" not in str(exc).lower() and "locked" not in str(exc).lower():
                    raise
                if time.monotonic() - started > timeout_seconds:
                    raise TimeoutError("La fuente SQLite permaneció bloqueada") from exc
                time.sleep(0.05)
            finally:
                write_connection.close()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        read_connection.close()


def _validate_gestar_worktree(worktree: Path) -> None:
    try:
        observed = subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("No se pudo verificar la revisión de Gestar") from exc
    if observed != EXPECTED_GESTAR_HEAD:
        raise RuntimeError("La revisión de Gestar no es la validada para este bloque")


def validate_copy(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("La copia no pasó PRAGMA quick_check")
        for table, required in REQUIRED_SCHEMA.items():
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if not required <= columns:
                raise RuntimeError(f"Esquema incompatible: {table}")
    finally:
        connection.close()


def _wait_for_gestar(port: int, token: str, deadline_seconds: float = 15.0) -> None:
    request = Request(
        f"http://127.0.0.1:{port}/api/v1/commercial/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Gestar no quedó disponible dentro del plazo")


def _start(command: list[str], cwd: Path, environment: dict[str, str], *, inherit_io: bool = False) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=None if inherit_io else subprocess.DEVNULL,
        stdout=None if inherit_io else subprocess.DEVNULL,
        stderr=None if inherit_io else subprocess.DEVNULL,
        text=True,
    )


def run(source_db: str, gestar_worktree: str, mike_worktree: str | None = None) -> int:
    source = _existing_source(source_db)
    gestar = Path(gestar_worktree).expanduser().resolve()
    if not (gestar / "app" / "commercial_entry.py").is_file():
        raise RuntimeError("El worktree Gestar no contiene app.commercial_entry")
    _validate_gestar_worktree(gestar)
    mike = Path(mike_worktree or Path(__file__).resolve().parents[1]).resolve()
    temporary = Path(tempfile.mkdtemp(prefix="mike-pilot-session-"))
    copy = temporary / "gestar-snapshot.sqlite3"
    gestar_process = None
    mike_process = None
    token = secrets.token_urlsafe(32)
    dev_key = secrets.token_urlsafe(24)
    capture_at = datetime.now().astimezone().isoformat()
    try:
        backup_source(source, copy)
        validate_copy(copy)
        port = _free_port()
        base_environment = os.environ.copy()
        gestar_environment = base_environment | {
            "PYTHONPATH": str(gestar),
            "GESTAR_COMMERCIAL_ENABLED": "true",
            "GESTAR_COMMERCIAL_BEARER_TOKEN": token,
            "GESTAR_COMMERCIAL_INSTALLATION_ID": "pilot-installation",
            "GESTAR_COMMERCIAL_BUSINESS_ID": "pilot-business",
            "GESTAR_COMMERCIAL_TENANT_ID": "pilot-tenant",
            "GESTAR_COMMERCIAL_CURRENCY": "ARS",
            "GESTAR_COMMERCIAL_TIMEZONE": "America/Argentina/Buenos_Aires",
            "GESTAR_COMMERCIAL_ALLOW_HTTP_LOOPBACK": "true",
            "GESTAR_COMMERCIAL_SCOPES": "commercial.products.read commercial.quotes.read",
        }
        gestar_process = _start(
            [sys.executable, "-m", "app.commercial_entry", "--database", str(copy), "--host", "127.0.0.1", "--port", str(port)],
            gestar,
            gestar_environment,
        )
        _wait_for_gestar(port, token)
        print(f"Copia capturada: {capture_at}")
        print("Los precios corresponden a esta captura; no se crean pedidos ni se reserva stock.")
        mike_environment = base_environment | {
            "MIKE_ENV": "development",
            "MIKE_EPISODE_JOURNAL": "memory",
            "MIKE_GESTAR_COMMERCIAL_ENABLED": "true",
            "MIKE_GESTAR_BASE_URL": f"http://127.0.0.1:{port}",
            "MIKE_GESTAR_BEARER_TOKEN": token,
            "MIKE_GESTAR_INSTALLATION_ID": "pilot-installation",
            "MIKE_GESTAR_BUSINESS_ID": "pilot-business",
            "MIKE_GESTAR_TENANT_ID": "pilot-tenant",
            "MIKE_GESTAR_DEV_KEY": dev_key,
        }
        mike_process = _start([sys.executable, "-m", "tools.gestar_pilot"], mike, mike_environment, inherit_io=True)
        return mike_process.wait()
    finally:
        cleanup_errors: list[str] = []
        for process in (mike_process, gestar_process):
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception as exc:
                        cleanup_errors.append(f"proceso PID {process.pid}: {exc}")
                except Exception as exc:
                    cleanup_errors.append(f"proceso PID {process.pid}: {exc}")
        try:
            shutil.rmtree(temporary)
        except OSError as exc:
            cleanup_errors.append(f"recurso propio {temporary}: {exc}")
        for error in cleanup_errors:
            print(f"No se pudo limpiar {error}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sesión MIKE–Gestar sobre copia SQLite temporal")
    parser.add_argument("--source-db", required=True, help="Ruta explícita a la base fuente existente")
    parser.add_argument("--gestar-worktree", required=True, help="Worktree validado de Gestar")
    parser.add_argument("--mike-worktree", default=None, help="Worktree MIKE; por defecto, la raíz actual del módulo")
    args = parser.parse_args()
    try:
        return run(args.source_db, args.gestar_worktree, args.mike_worktree)
    except Exception as exc:
        print(f"No se pudo iniciar la sesión: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
