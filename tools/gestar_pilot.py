"""Supervised MIKE launcher for an independently running Gestar entry."""
from __future__ import annotations

import socket
import threading
import time

import uvicorn

from mike_app.commercial.cart import TerminalCart
from mike_app.commercial.gestar_client import GestarCommercialClient, GestarCommercialConfig
from mike_app.core.settings import Settings, get_settings
from mike_app.main import create_app
from mike_app.commercial.demo_controller import DemoController


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _settings() -> Settings:
    settings = get_settings()
    required = {
        "MIKE_GESTAR_BASE_URL": settings.gestar_base_url,
        "MIKE_GESTAR_BEARER_TOKEN": settings.gestar_bearer_token,
        "MIKE_GESTAR_INSTALLATION_ID": settings.gestar_installation_id,
        "MIKE_GESTAR_BUSINESS_ID": settings.gestar_business_id,
        "MIKE_GESTAR_TENANT_ID": settings.gestar_tenant_id,
        "MIKE_GESTAR_DEV_KEY": settings.gestar_dev_key,
    }
    missing = [name for name, value in required.items() if not value]
    if settings.environment != "development":
        raise RuntimeError("MIKE_ENV debe ser development para el piloto local")
    if not settings.gestar_commercial_enabled:
        raise RuntimeError("MIKE_GESTAR_COMMERCIAL_ENABLED debe ser true explícitamente")
    if missing:
        raise RuntimeError("Falta configuración requerida: " + ", ".join(missing))
    GestarCommercialConfig.from_settings(settings)
    return settings


def _start(app):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, name="mike-pilot", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("MIKE no inició dentro del plazo")
    return server, thread, port


def main() -> None:
    settings = _settings()
    client = None
    server = None
    thread = None
    cart = None
    try:
        server, thread, port = _start(create_app(settings))
        client = GestarCommercialClient(GestarCommercialConfig.from_settings(settings))
        page = client.list_products(limit=100)
        cart = TerminalCart([product.product_id for product in page.products])
        print(f"Destino: {settings.gestar_base_url} | instalación: {settings.gestar_installation_id} | negocio: {settings.gestar_business_id}")
        print("Consulta supervisada; no crea pedidos ni reserva disponibilidad.")
        print("Use lenguaje <texto>, buscar TEXTO, agregar ID CANTIDAD, modificar ID CANTIDAD, quitar ID, carrito, cotizar o salir.")
        controller = DemoController(client, cart, lambda items: _quote(port, settings.gestar_dev_key, items))
        while True:
            try:
                command = input("piloto> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCerrando MIKE; Gestar permanece activo.")
                break
            if command.lower() in {"salir", "exit", "quit", "q"}:
                break
            if controller.process(command):
                continue
            if command.startswith("buscar "):
                result = client.list_products(command[7:].strip(), limit=100)
                print("Coincidencias:", [(p.product_id, p.name, p.unit) for p in result.products])
                continue
            print("Comando no reconocido. Use lenguaje, buscar, agregar, modificar, quitar, carrito, cotizar o salir.")
    finally:
        if cart is not None:
            cart.clear()
        if client is not None:
            client.close()
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)


def _quote(port: int, key: str, items: list[dict[str, int]]) -> None:
    import httpx

    response = httpx.post(
        f"http://127.0.0.1:{port}/dev/commercial/quote",
        headers={"X-Mike-Development-Key": key},
        json={"items": items},
        timeout=5,
    )
    if response.is_success:
        body = response.json()
        print(f"HTTP {response.status_code} | ARS {body['total']} | líneas: {[(line['product_id'], line['quantity']) for line in body['lines']]}")
        print(f"Promociones: {body['promotions_applied']} | grupos: {body['mixed_groups_applied']} | advertencias: {body['stock_warnings']}")
    else:
        try:
            print(f"Error recuperable: {response.json().get('error', {}).get('code', 'commercial_error')}")
        except ValueError:
            print(f"Error recuperable: HTTP {response.status_code}")


if __name__ == "__main__":
    main()
