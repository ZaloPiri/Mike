from __future__ import annotations

import sqlite3
import subprocess
import sys
import os
import socket
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tools.gestar_pilot_orchestrator import (
    REQUIRED_SCHEMA,
    _remove_owned_tree,
    backup_source,
    validate_copy,
)


GESTAR = Path(r"C:\Users\Ana\Desktop\GESTAR-mike-base")


def _synthetic_schema(path):
    db = sqlite3.connect(path)
    try:
        for table, columns in REQUIRED_SCHEMA.items():
            definition = ", ".join(f'"{column}" INTEGER' for column in sorted(columns))
            db.execute(f'CREATE TABLE "{table}" ({definition})')
        db.commit()
    finally:
        db.close()


def test_backup_uses_readonly_source_and_validates_copy(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "snapshot.sqlite3"
    _synthetic_schema(source)
    backup_source(source, destination, timeout_seconds=5)
    validate_copy(destination)
    read_only = sqlite3.connect(f"file:{destination.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        read_only.execute('CREATE TABLE forbidden (id INTEGER)')
    read_only.close()


def test_cleanup_retries_windows_style_late_release(tmp_path, monkeypatch):
    temporary = tmp_path / "session"
    temporary.mkdir()
    attempts = 0

    import tools.gestar_pilot_orchestrator as orchestrator

    real_rmtree = orchestrator.shutil.rmtree

    def delayed_rmtree(path):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(32, "archivo utilizado por otro proceso")
        real_rmtree(path)

    monkeypatch.setattr(orchestrator.shutil, "rmtree", delayed_rmtree)
    errors = []
    _remove_owned_tree(temporary, errors, attempts=3, delay=0)

    assert attempts == 3
    assert not errors
    assert not temporary.exists()


def test_orchestrator_requires_explicit_source_and_worktree():
    result = subprocess.run(
        [sys.executable, "-m", "tools.gestar_pilot_orchestrator", "--source-db", "missing.sqlite3"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--gestar-worktree" in result.stderr


@pytest.mark.skipif(not GESTAR.exists(), reason="Gestar worktree no disponible")
@pytest.mark.parametrize("mode", ["terminal", "web"])
def test_orchestrator_runs_real_programs_and_preserves_preexisting_service(tmp_path, mode):
    prep = r'''
from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.model_base import Base
from app.models import Category, PriceList, Product, ProductPrice
engine = create_engine("sqlite:///DB_PATH")
Base.metadata.create_all(engine)
with Session(engine) as db:
    category = Category(nombre="Orquestador sintético")
    prices = PriceList(nombre="Piloto", fecha_inicio=date(2020, 1, 1), activa=True)
    product = Product(nombre="Producto A", categoria=category, activo=True, controla_stock=False)
    db.add_all([category, prices, product]); db.flush()
    db.add(ProductPrice(lista=prices, producto=product, precio_unitario=Decimal("100")))
    db.commit()
engine.dispose()
'''
    source = tmp_path / "source.sqlite3"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(GESTAR)
    subprocess.run(
        [sys.executable, "-c", prep.replace("DB_PATH", str(source).replace("\\", "/"))],
        cwd=GESTAR, env=environment, check=True,
    )
    source_hash = __import__("hashlib").sha256(source.read_bytes()).digest()
    service_dir = tmp_path / "preexisting"
    service_dir.mkdir()
    probe = socket.socket(); probe.bind(("127.0.0.1", 0)); service_port = probe.getsockname()[1]; probe.close()
    service = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(service_port)],
        cwd=service_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                from urllib.request import urlopen
                with urlopen(f"http://127.0.0.1:{service_port}", timeout=1):
                    break
            except Exception:
                time.sleep(0.05)
        command = [sys.executable, "-m", "tools.gestar_pilot_orchestrator", "--source-db", str(source), "--gestar-worktree", str(GESTAR), "--mode", mode]
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).parents[1], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        interaction = "lenguaje quiero 2 de Producto A\n1\ns\ncotizar\nsalir\n" if mode == "terminal" else "salir\n"
        output, error = process.communicate(interaction, timeout=45)
        assert process.returncode == 0, error
        if mode == "terminal":
            assert "HTTP 200" in output
            assert "ARS 200.00" in output
        else:
            assert "MIKE web: http://127.0.0.1:" in output
            assert "Código bootstrap" in output
        assert __import__("hashlib").sha256(source.read_bytes()).digest() == source_hash
        assert service.poll() is None
    finally:
        if service.poll() is None:
            service.terminate(); service.wait(timeout=5)
