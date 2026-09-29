from decimal import Decimal
import json

import httpx
import pytest

from mike_app.commercial.gestar_client import (
    CommercialProtocolError,
    GestarCommercialClient,
    GestarCommercialConfig,
)


def _quote_payload():
    return {
        "installation_id": "lasandwicheria-local", "business_id": "lasandwicheria",
        "currency": "ARS", "commercial_date": "2026-09-28",
        "calculated_at": "2026-09-28T20:00:01-03:00",
        "price_list": {"id": 3, "name": "Septiembre", "starts_on": "2026-09-01", "ends_on": None},
        "lines": [{"product_id": 17, "quantity": 4, "unit": "unidad", "normal_subtotal": "400.00",
                   "promotion_quantity": 0, "mixed_group_quantity": 0, "remaining_quantity": 4}],
        "promotions_applied": [], "mixed_groups_applied": [],
        "pricing_breakdown": [{"kind": "unit", "package_size": 1, "product_id": 17,
                               "quantity": 4, "applications": 4, "unit_price": "100.00", "subtotal": "400.00"}],
        "stock_warnings": [], "total": "400.00", "stock_reserved": False,
        "availability_guaranteed": False,
    }


def _client(handler):
    transport = httpx.MockTransport(handler)
    return GestarCommercialClient(
        GestarCommercialConfig("https://gestar.example", "secret-not-real", "lasandwicheria-local", "lasandwicheria", "tenant-lasandwicheria"),
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )


def test_quote_sends_only_items_and_validates_complete_response():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_quote_payload())

    client = _client(handler)
    try:
        result = client.quote([{"product_id": 17, "quantity": 4}])
    finally:
        client.close()
    assert seen == {
        "url": "https://gestar.example/api/v1/commercial/quotes",
        "auth": "Bearer secret-not-real",
        "body": {"items": [{"product_id": 17, "quantity": 4}]},
    }
    assert result["total"] == "400.00"


def test_list_products_validates_identity_and_cursor():
    def handler(request):
        assert request.url.path == "/api/v1/commercial/products"
        assert request.url.params["query"] == "jamón"
        return httpx.Response(200, json={"installation_id": "lasandwicheria-local", "business_id": "lasandwicheria",
                                         "products": [{"product_id": 17, "name": "Jamón", "code": None, "unit": "unidad"}],
                                         "next_cursor": "next"})
    client = _client(handler)
    try:
        page = client.list_products("jamón", 1)
    finally:
        client.close()
    assert page.products[0].product_id == 17 and page.next_cursor == "next"


def test_list_products_rejects_incompatible_identity_and_invalid_limits():
    client = _client(lambda request: httpx.Response(200, json={"installation_id": "other", "business_id": "lasandwicheria", "products": [], "next_cursor": None}))
    try:
        with pytest.raises(CommercialProtocolError):
            client.list_products(limit=101)
        with pytest.raises(CommercialProtocolError):
            client.list_products()
    finally:
        client.close()


@pytest.mark.parametrize("body", [
    [{"product_id": True, "quantity": 1}],
    [{"product_id": 1, "quantity": 0}],
    [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}],
])
def test_quote_rejects_ambiguous_or_duplicate_items(body):
    client = _client(lambda request: httpx.Response(500))
    try:
        with pytest.raises(CommercialProtocolError):
            client.quote(body)
    finally:
        client.close()


def test_quote_rejects_identity_and_false_commercial_guarantees():
    def handler(request):
        payload = _quote_payload()
        payload["installation_id"] = "other"
        return httpx.Response(200, json=payload)

    client = _client(handler)
    try:
        with pytest.raises(CommercialProtocolError):
            client.quote([{"product_id": 17, "quantity": 4}])
    finally:
        client.close()


def test_quote_rejects_unreconciled_decimal():
    def handler(request):
        payload = _quote_payload()
        payload["total"] = "0.00"
        return httpx.Response(200, json=payload)

    client = _client(handler)
    try:
        with pytest.raises(CommercialProtocolError):
            client.quote([{"product_id": 17, "quantity": 4}])
    finally:
        client.close()


def test_quote_rejects_promotion_consumption_without_double_counting():
    def handler(request):
        payload = _quote_payload()
        payload["lines"][0].update(promotion_quantity=2, remaining_quantity=2)
        payload["pricing_breakdown"][0].update(quantity=2, applications=2, subtotal="200.00")
        payload["promotions_applied"] = [{"promotion_id": 1, "name": "Combo", "times": 2,
                                           "unit_final_price": "100.00", "subtotal": "200.00",
                                           "components": [{"product_id": 17, "quantity": 1}]}]
        payload["total"] = "400.00"
        return httpx.Response(200, json=payload)
    client = _client(handler)
    try:
        with pytest.raises(CommercialProtocolError):
            client.quote([{"product_id": 17, "quantity": 4}])
    finally:
        client.close()
