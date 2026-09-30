from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest


GESTAR = Path(r"C:\Users\Ana\Desktop\GESTAR-mike-base")
EXPECTED_HEAD = "1a2a7245b019eadfa1b950de5f9e82a48822be55"
TOKEN = "pilot-process-synthetic-token"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_products(port: int, token: str) -> None:
    request = Request(
        f"http://127.0.0.1:{port}/api/v1/commercial/products",
        headers={"Authorization": f"Bearer {token}"},
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise AssertionError("Gestar commercial_entry no inició")


@pytest.mark.skipif(not GESTAR.exists(), reason="Gestar worktree no disponible")
def test_real_programs_complete_flow_and_mike_shutdown_preserves_gestar(tmp_path):
    observed = subprocess.check_output(["git", "-C", str(GESTAR), "rev-parse", "HEAD"], text=True).strip()
    assert observed == EXPECTED_HEAD
    database = tmp_path / "pilot synthetic.sqlite3"
    prepare = r'''
from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.model_base import Base
from app.models import Category, PriceList, Product, ProductPrice
engine = create_engine("sqlite:///DB_PATH")
Base.metadata.create_all(engine)
with Session(engine) as db:
    category = Category(nombre="Piloto sintético")
    prices = PriceList(nombre="Piloto", fecha_inicio=date(2020, 1, 1), activa=True)
    product = Product(nombre="Producto A", categoria=category, activo=True, controla_stock=False)
    db.add_all([category, prices, product]); db.flush()
    db.add(ProductPrice(lista=prices, producto=product, precio_unitario=Decimal("100")))
    db.commit()
engine.dispose()
'''.replace("DB_PATH", str(database).replace("\\", "/").replace('"', '""'))
    prep_env = os.environ.copy()
    prep_env["PYTHONPATH"] = str(GESTAR)
    subprocess.run([sys.executable, "-c", prepare], cwd=GESTAR, env=prep_env, check=True)

    gestar_port = _port()
    gestar_env = prep_env | {
        "GESTAR_COMMERCIAL_ENABLED": "true",
        "GESTAR_COMMERCIAL_BEARER_TOKEN": TOKEN,
        "GESTAR_COMMERCIAL_INSTALLATION_ID": "pilot-installation",
        "GESTAR_COMMERCIAL_BUSINESS_ID": "pilot-business",
        "GESTAR_COMMERCIAL_TENANT_ID": "pilot-tenant",
        "GESTAR_COMMERCIAL_CURRENCY": "ARS",
        "GESTAR_COMMERCIAL_TIMEZONE": "America/Argentina/Buenos_Aires",
        "GESTAR_COMMERCIAL_ALLOW_HTTP_LOOPBACK": "true",
        "GESTAR_COMMERCIAL_SCOPES": "commercial.products.read commercial.quotes.read",
    }
    gestar = subprocess.Popen(
        [sys.executable, "-m", "app.commercial_entry", "--database", str(database), "--host", "127.0.0.1", "--port", str(gestar_port)],
        cwd=GESTAR, env=gestar_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    mike = None
    try:
        _wait_products(gestar_port, TOKEN)
        mike_env = os.environ.copy() | {
            "MIKE_ENV": "development",
            "MIKE_EPISODE_JOURNAL": "memory",
            "MIKE_GESTAR_COMMERCIAL_ENABLED": "true",
            "MIKE_GESTAR_BASE_URL": f"http://127.0.0.1:{gestar_port}",
            "MIKE_GESTAR_BEARER_TOKEN": TOKEN,
            "MIKE_GESTAR_INSTALLATION_ID": "pilot-installation",
            "MIKE_GESTAR_BUSINESS_ID": "pilot-business",
            "MIKE_GESTAR_TENANT_ID": "pilot-tenant",
            "MIKE_GESTAR_DEV_KEY": "pilot-local-key",
        }
        mike = subprocess.Popen(
            [sys.executable, "-m", "tools.gestar_pilot"], cwd=Path(__file__).parents[1],
            env=mike_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        output, errors = mike.communicate("lenguaje quiero 2 de Producto A\n1\ns\ncotizar\nsalir\n", timeout=20)
        assert mike.returncode == 0, errors
        assert "HTTP 200" in output
        assert "ARS 200.00" in output
        assert "2" in output
        _wait_products(gestar_port, TOKEN)
    finally:
        if mike is not None and mike.poll() is None:
            mike.kill(); mike.communicate(timeout=5)
        if gestar.poll() is None:
            gestar.terminate()
            try:
                gestar.wait(timeout=10)
            except subprocess.TimeoutExpired:
                gestar.kill(); gestar.wait(timeout=5)
        else:
            gestar.wait(timeout=5)
        try:
            gestar.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            gestar.kill(); gestar.communicate(timeout=5)
        database.unlink(missing_ok=True)
        assert not database.exists()
