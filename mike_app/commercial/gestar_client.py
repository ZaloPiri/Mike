from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlparse

import httpx


class CommercialClientError(Exception):
    status_code = 502
    code = "commercial_source_unreachable"

    def __init__(self, message: str = "No se pudo consultar Gestar") -> None:
        super().__init__(message)


class CommercialConfigurationError(CommercialClientError):
    status_code = 503
    code = "commercial_configuration_unavailable"


class CommercialTimeoutError(CommercialClientError):
    status_code = 408
    code = "commercial_source_timeout"


class CommercialProtocolError(CommercialClientError):
    status_code = 422
    code = "commercial_schema_invalid"


class CommercialIdentityError(CommercialProtocolError):
    status_code = 409
    code = "commercial_identity_mismatch"


class CommercialSourceError(CommercialClientError):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__("Gestar rechazó la consulta comercial")
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class GestarCommercialConfig:
    base_url: str
    bearer_token: str
    installation_id: str
    business_id: str
    tenant_id: str
    timeout_seconds: float = 5.0

    @classmethod
    def from_settings(cls, settings: Any) -> "GestarCommercialConfig":
        values = (settings.gestar_base_url, settings.gestar_bearer_token,
                  settings.gestar_installation_id, settings.gestar_business_id,
                  settings.gestar_tenant_id)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise CommercialConfigurationError()
        parsed = urlparse(settings.gestar_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise CommercialConfigurationError()
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme == "http" and not loopback:
            raise CommercialConfigurationError()
        if parsed.query or parsed.fragment:
            raise CommercialConfigurationError()
        return cls(settings.gestar_base_url.rstrip("/"), settings.gestar_bearer_token,
                   settings.gestar_installation_id, settings.gestar_business_id,
                   settings.gestar_tenant_id)


def _strict_positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CommercialProtocolError(f"invalid {field}")
    return value


def _money(value: Any) -> Decimal:
    if not isinstance(value, str) or len(value) < 4:
        raise CommercialProtocolError("invalid amount")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CommercialProtocolError("invalid amount") from exc
    if result.quantize(Decimal("0.01")) != result or value != f"{result:.2f}":
        raise CommercialProtocolError("invalid amount")
    return result


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise CommercialProtocolError("incomplete response")
    return mapping[key]


def _validate_response(payload: Any, requested: list[dict[str, int]], config: GestarCommercialConfig) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CommercialProtocolError()
    if _require(payload, "installation_id") != config.installation_id or _require(payload, "business_id") != config.business_id:
        raise CommercialIdentityError("incompatible commercial identity")
    if _require(payload, "currency") != "ARS":
        raise CommercialProtocolError("unsupported currency")
    try:
        date.fromisoformat(_require(payload, "commercial_date"))
        calculated_at = datetime.fromisoformat(_require(payload, "calculated_at"))
    except (TypeError, ValueError) as exc:
        raise CommercialProtocolError("invalid commercial timestamp") from exc
    if calculated_at.tzinfo is None:
        raise CommercialProtocolError("timestamp must be aware")
    price_list = _require(payload, "price_list")
    if (not isinstance(price_list, dict) or isinstance(_require(price_list, "id"), bool)
            or not isinstance(_require(price_list, "id"), int) or not isinstance(_require(price_list, "name"), str)
            or not isinstance(_require(price_list, "starts_on"), str)
            or (_require(price_list, "ends_on") is not None and not isinstance(_require(price_list, "ends_on"), str))):
        raise CommercialProtocolError()
    try:
        date.fromisoformat(price_list["starts_on"])
        if price_list["ends_on"] is not None:
            date.fromisoformat(price_list["ends_on"])
    except ValueError as exc:
        raise CommercialProtocolError("invalid price list dates") from exc
    lines = _require(payload, "lines")
    if not isinstance(lines, list) or len(lines) != len(requested):
        raise CommercialProtocolError("line mismatch")
    expected = {item["product_id"]: item["quantity"] for item in requested}
    seen: set[int] = set()
    normal_by_product: dict[int, Decimal] = {}
    for line in lines:
        if not isinstance(line, dict):
            raise CommercialProtocolError()
        product_id = _strict_positive(_require(line, "product_id"), "product_id")
        quantity = _strict_positive(_require(line, "quantity"), "quantity")
        if product_id in seen or expected.get(product_id) != quantity:
            raise CommercialProtocolError("line mismatch")
        seen.add(product_id)
        promotion = _require(line, "promotion_quantity")
        mixed = _require(line, "mixed_group_quantity")
        remaining = _require(line, "remaining_quantity")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (promotion, mixed, remaining)) or quantity != promotion + mixed + remaining:
            raise CommercialProtocolError("quantity reconciliation failed")
        normal = _money(_require(line, "normal_subtotal"))
        normal_by_product[product_id] = normal
    if seen != set(expected):
        raise CommercialProtocolError("line mismatch")
    breakdown = _require(payload, "pricing_breakdown")
    if not isinstance(breakdown, list):
        raise CommercialProtocolError()
    breakdown_quantity: dict[int, int] = {}
    breakdown_total: dict[int, Decimal] = {}
    normal_total = Decimal("0.00")
    for item in breakdown:
        if not isinstance(item, dict):
            raise CommercialProtocolError()
        kind = _require(item, "kind")
        package_size = _strict_positive(_require(item, "package_size"), "package_size")
        if kind not in {"unit", "package"} or (kind == "unit" and package_size != 1) or (kind == "package" and package_size not in {6, 12}):
            raise CommercialProtocolError()
        product_id = _strict_positive(_require(item, "product_id"), "product_id")
        quantity = _strict_positive(_require(item, "quantity"), "quantity")
        applications = _strict_positive(_require(item, "applications"), "applications")
        unit_price = _money(_require(item, "unit_price"))
        subtotal = _money(_require(item, "subtotal"))
        if quantity != applications * package_size or subtotal != unit_price * applications:
            raise CommercialProtocolError("pricing reconciliation failed")
        breakdown_quantity[product_id] = breakdown_quantity.get(product_id, 0) + quantity
        breakdown_total[product_id] = breakdown_total.get(product_id, Decimal("0.00")) + subtotal
        normal_total += subtotal
    for line in lines:
        product_id = line["product_id"]
        if breakdown_quantity.get(product_id, 0) != line["remaining_quantity"] or breakdown_total.get(product_id, Decimal("0.00")) != normal_by_product[product_id]:
            raise CommercialProtocolError("normal pricing reconciliation failed")
    promotions = _require(payload, "promotions_applied")
    groups = _require(payload, "mixed_groups_applied")
    if not isinstance(promotions, list) or not isinstance(groups, list):
        raise CommercialProtocolError()
    applied_total = normal_total
    applied_consumption: dict[int, int] = {}
    for collection, group in ((promotions, "promotion"), (groups, "mixed")):
        for entry in collection:
            if not isinstance(entry, dict):
                raise CommercialProtocolError()
            _strict_positive(_require(entry, "times"), "times")
            _money(_require(entry, "subtotal"))
            if group == "promotion":
                _money(_require(entry, "unit_final_price"))
            else:
                size = _require(entry, "size")
                if size not in {6, 12}:
                    raise CommercialProtocolError()
                _money(_require(entry, "unit_price"))
            components = _require(entry, "components")
            if not isinstance(components, list) or not components:
                raise CommercialProtocolError()
            for component in components:
                if not isinstance(component, dict) or _strict_positive(_require(component, "product_id"), "product_id") not in expected:
                    raise CommercialProtocolError()
                component_quantity = _strict_positive(_require(component, "quantity"), "quantity")
                component_product = component["product_id"]
                applied_consumption[component_product] = applied_consumption.get(component_product, 0) + component_quantity
    for line in lines:
        product_id = line["product_id"]
        if applied_consumption.get(product_id, 0) != line["promotion_quantity"] + line["mixed_group_quantity"]:
            raise CommercialProtocolError("applied consumption reconciliation failed")
    for collection in (promotions, groups):
        for entry in collection:
            applied_total += _money(entry["subtotal"])
    if _money(_require(payload, "total")) != applied_total or _require(payload, "stock_reserved") is not False or _require(payload, "availability_guaranteed") is not False:
        raise CommercialProtocolError("total reconciliation failed")
    warnings = _require(payload, "stock_warnings")
    if not isinstance(warnings, list):
        raise CommercialProtocolError()
    allowed = {"stock_below_requested_quantity", "made_to_order_not_stock_checked", "stock_not_configured"}
    for warning in warnings:
        if not isinstance(warning, dict) or _require(warning, "code") not in allowed:
            raise CommercialProtocolError()
    return payload


class GestarCommercialClient:
    def __init__(self, config: GestarCommercialConfig, client_factory: Callable[..., httpx.Client] | None = None) -> None:
        self.config = config
        self._client = (client_factory or httpx.Client)(follow_redirects=False, verify=True)

    def close(self) -> None:
        self._client.close()

    def quote(self, items: list[dict[str, int]]) -> dict[str, Any]:
        if not 1 <= len(items) <= 50:
            raise CommercialProtocolError("invalid item count")
        normalized: list[dict[str, int]] = []
        seen: set[int] = set()
        for item in items:
            if set(item) != {"product_id", "quantity"}:
                raise CommercialProtocolError("invalid item shape")
            product_id = _strict_positive(item["product_id"], "product_id")
            quantity = _strict_positive(item["quantity"], "quantity")
            if quantity > 10000 or product_id in seen:
                raise CommercialProtocolError("invalid or duplicate item")
            seen.add(product_id)
            normalized.append({"product_id": product_id, "quantity": quantity})
        started = time.monotonic()
        try:
            stream = self._client.stream(
                "POST",
                f"{self.config.base_url}/api/v1/commercial/quotes",
                headers={"Authorization": f"Bearer {self.config.bearer_token}", "Accept": "application/json"},
                json={"items": normalized},
                timeout=max(0.001, self.config.timeout_seconds - (time.monotonic() - started)),
            )
            with stream as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > self.config.timeout_seconds:
                        raise CommercialTimeoutError()
                    body.extend(chunk)
                response_content = bytes(body)
        except httpx.TimeoutException as exc:
            raise CommercialTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise CommercialClientError() from exc
        if time.monotonic() - started > self.config.timeout_seconds:
            raise CommercialTimeoutError()
        if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
            raise CommercialClientError()
        if response.status_code >= 400:
            try:
                error = json.loads(response_content).get("error", {})
                code = error.get("code", "commercial_source_rejected")
            except (ValueError, AttributeError):
                code = "commercial_source_invalid_json"
            raise CommercialSourceError(response.status_code, code)
        try:
            payload = json.loads(response_content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise CommercialProtocolError("invalid JSON") from exc
        return _validate_response(payload, normalized, self.config)
