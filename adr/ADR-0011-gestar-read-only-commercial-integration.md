# ADR-0011 — Gestar Read-Only Commercial Integration

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

MIKE accepts development messages, optional structured perception, and
deterministic responses. It has no Gestar client or commercial lookup.
Gestar is the commercial source of truth for La Sandwichería. Its current
application exposes HTML/form routes, not an approved machine API.

The relevant internal services are `pricing_engine.calculate()` and
`sales.preview()` in `app/services/`. `sales.confirm()` has commercial side
effects and is excluded. This proposal does not approve Phase 25, alter
events 1–12, or change ADR-0009/0010.

## Decision

### 1. Frontier and first increment

Gestar exposes, as the accepted architecture, a versioned HTTP JSON API at
`/api/v1/commercial`. MIKE uses a client boundary and must not import Gestar code, access its
database, or duplicate pricing rules. Gestar remains the sole commercial
authority.

The first increment is a supervised, read-only technical query using explicit
IDs and quantities. It may list active products and calculate a complete
quotation. It does not create orders, sales, invoices, cash or stock
movements, reservations, production requests, or pickup commitments.

The concrete routes are:

- `GET /api/v1/commercial/products?query=<text>&limit=<1..100>&cursor=<opaque>`;
- `POST /api/v1/commercial/quotes`.

Product pages are ordered by ascending integer `product_id`. An omitted
cursor starts at the first product, a cursor starts after the last product of
the previous page, and a terminal page returns `next_cursor: null`. The quote
request accepts no cursor, commercial date, or price-list selector.

The technical MIKE operation is `POST /dev/commercial/quote`, disabled by
default and rejected outside development. It accepts explicit IDs and
quantities, creates no event, and does not enter the conversational or
delivery pipeline. It does not require OpenAI, name resolution, or
conversation continuity.

### 2. Currency, date, and price list

The first integration is exclusively ARS. Gestar
must declare the installation currency in trusted configuration and return
`"currency": "ARS"` in every valid quotation. MIKE must not invent, infer,
or complete currency. Missing, malformed, or non-ARS configuration disables
the integration before commercial data is presented.

The initial quote request does not accept `calculation_date`, `price_list_id`,
or arbitrary list selection. Gestar determines `commercial_date` using the
explicit installation timezone:
`America/Argentina/Buenos_Aires`.

Every successful product and quote response includes:

- `installation_id` and `business_id`, from trusted Gestar configuration;
- `commercial_date` as an ISO date, for quotes;
- `calculated_at` as an aware ISO-8601 timestamp, for quotes;
- `currency`, always ARS for this first increment, for quotes; and
- `price_list`, including ID, name, start date, and end date, for quotes.

MIKE compares `installation_id` and `business_id` with its configured
installation-to-tenant binding. Missing, malformed, or incompatible values
invalidate the response. JSON identity does not replace Bearer
authentication, transport validation, or server authorization.

Gestar preserves `app/repositories/price_lists.py:vigente()`:

1. active list;
2. `fecha_inicio <= commercial_date`;
3. no end date or `fecha_fin >= commercial_date`;
4. newest start date; and
5. highest ID as tie-breaker.

No valid quote exists without an applicable list and sufficient prices for
the complete cart.

### 3. Input validation and provisional limits

Before calculation, the API requires strict JSON integer values:

- `product_id` is a positive integer, not a boolean or ambiguous string;
- `quantity` is a positive integer, not a boolean or fraction;
- one to 50 lines;
- quantity at most 10,000 per line;
- no repeated product IDs, returning `422 duplicate_product_line`;
- existence and active status for every product;
- product search text at most 100 Unicode characters; and
- product listing `limit` from 1 to 100 with a bounded documented cursor.

These limits are provisional. They are justified by the current engine's
quantity consolidation and exploration of promotion and mixed-group
combinations, but representative loads and adversarial combinations must be
measured before enablement. If evidence requires different limits or a
different engine strategy, the change must be reported explicitly.

Quantity uses the product's declared `unidad_venta`. The first contract
accepts integer sale units and performs no implicit conversion between units,
dozens, weight, or packaging. An incompatible unit returns
`422 invalid_quantity_unit`; the complete HTTP schema remains implementation
work pending before routes are implemented.

### 4. Complete quotation and source calculation

Gestar calculates the complete cart through the existing pricing engine. MIKE
never calculates each line independently. The intended boundary is a new
read-only Gestar service reusing `pricing_engine.calculate()`.

`sales.preview()` is not considered pure by its name. In the inspected code it
reads products, pricing, and stock warnings through
`inventory.ensure_available()` without commits or commercial movements. This
must remain true for the fixed Gestar revision. `sales.confirm()` is
forbidden: it creates and flushes a sale, deducts stock, writes cash and audit
records, commits, and runs the post-commit backup path.

The response schema is:

```json
{
  "installation_id": "lasandwicheria-local",
  "business_id": "lasandwicheria",
  "currency": "ARS",
  "commercial_date": "2026-09-28",
  "calculated_at": "2026-09-28T20:00:01-03:00",
  "price_list": {"id": 3, "name": "Septiembre", "starts_on": "2026-09-01", "ends_on": null},
  "lines": [
    {"product_id": 17, "quantity": 4, "unit": "unidad", "normal_subtotal": "400.00", "promotion_quantity": 0, "mixed_group_quantity": 0, "remaining_quantity": 4},
    {"product_id": 42, "quantity": 8, "unit": "unidad", "normal_subtotal": "800.00", "promotion_quantity": 0, "mixed_group_quantity": 0, "remaining_quantity": 8}
  ],
  "promotions_applied": [],
  "mixed_groups_applied": [],
  "pricing_breakdown": [
    {"kind": "unit", "package_size": 1, "product_id": 17, "quantity": 4, "unit_price": "100.00", "subtotal": "400.00"},
    {"kind": "unit", "package_size": 1, "product_id": 42, "quantity": 8, "unit_price": "100.00", "subtotal": "800.00"}
  ],
  "stock_warnings": [],
  "total": "1200.00",
  "stock_reserved": false,
  "availability_guaranteed": false
}
```

The mixed example is fictitious and is not a commercial rule:

```json
{
  "installation_id": "lasandwicheria-local",
  "business_id": "lasandwicheria",
  "currency": "ARS",
  "commercial_date": "2026-09-28",
  "calculated_at": "2026-09-28T20:00:01-03:00",
  "price_list": {"id": 3, "name": "Septiembre", "starts_on": "2026-09-01", "ends_on": null},
  "lines": [
    {"product_id": 17, "quantity": 4, "unit": "unidad", "normal_subtotal": "0.00", "promotion_quantity": 0, "mixed_group_quantity": 4, "remaining_quantity": 0},
    {"product_id": 42, "quantity": 8, "unit": "unidad", "normal_subtotal": "0.00", "promotion_quantity": 0, "mixed_group_quantity": 8, "remaining_quantity": 0}
  ],
  "promotions_applied": [],
  "mixed_groups_applied": [{"group_id": 2, "name": "Grupo ficticio", "size": 12, "times": 1, "unit_price": "1200.00", "subtotal": "1200.00", "components": [{"product_id": 17, "quantity": 4}, {"product_id": 42, "quantity": 8}]}],
  "pricing_breakdown": [],
  "stock_warnings": [],
  "total": "1200.00",
  "stock_reserved": false,
  "availability_guaranteed": false
}
```

The promotion example is fictitious and is not a commercial rule:

```json
{
  "installation_id": "lasandwicheria-local",
  "business_id": "lasandwicheria",
  "currency": "ARS",
  "commercial_date": "2026-09-28",
  "calculated_at": "2026-09-28T20:00:01-03:00",
  "price_list": {"id": 3, "name": "Septiembre", "starts_on": "2026-09-01", "ends_on": null},
  "lines": [
    {"product_id": 17, "quantity": 2, "unit": "unidad", "normal_subtotal": "0.00", "promotion_quantity": 2, "mixed_group_quantity": 0, "remaining_quantity": 0},
    {"product_id": 42, "quantity": 1, "unit": "unidad", "normal_subtotal": "0.00", "promotion_quantity": 1, "mixed_group_quantity": 0, "remaining_quantity": 0}
  ],
  "promotions_applied": [{"promotion_id": 5, "name": "Combo ficticio", "times": 1, "unit_final_price": "900.00", "subtotal": "900.00", "components": [{"product_id": 17, "quantity": 2}, {"product_id": 42, "quantity": 1}]}],
  "mixed_groups_applied": [],
  "pricing_breakdown": [],
  "stock_warnings": [],
  "total": "900.00",
  "stock_reserved": false,
  "availability_guaranteed": false
}
```

`components` expresses total consumption across all applications of its
promotion or group; it is not multiplied by `times` again. A normal
`pricing_breakdown` entry contains `kind`, `package_size`, `product_id`,
`quantity`, `unit_price`, and `subtotal`. Package sizes are 1, 6, or 12 only
when selected by the deployed engine. `normal_subtotal` is the amount for
`remaining_quantity` and equals the sum of that line's normal breakdown
entries. Components and totals must reconcile without double counting:

```text
requested = promotion quantity + mixed-group quantity + remaining quantity
total = promotion subtotals + mixed-group subtotals + normal subtotals
```

Gestar supplies all quantities and monetary values. MIKE invents no product
subtotal, discount allocation, or rounding. Gestar currently uses `Decimal`
and `Numeric(12, 2)`; the engine uses exact Decimal arithmetic. The
`ROUND_HALF_UP` residual allocation in `sales.confirm()` is a historical sale
concern, not automatically a quotation rule. Any new quote rounding or
allocation remains pending human approval.

### 5. Complete failure and error contracts

No applicable list or insufficient price data rejects the complete request.
There is no partial quote and no substitution with price zero.

Gestar errors use 401 for invalid/revoked credentials, 403 for missing scope
or installation/tenant mismatch, 422 for invalid data, duplicate lines,
missing products, units, lists, or prices, and 503 for missing/incompatible
ARS configuration. MIKE separately reports connection failure,
`commercial_source_timeout`, incomplete/invalid JSON, and identity mismatch.

The first contract has no `quote_id`. `request_id` is non-persistent tracing
only and cannot authorize or confirm a purchase. Errors contain no secrets,
SQL, paths, driver details, or unauthorized commercial data.

Stock warnings are limited to vocabulary grounded in
`inventory.ensure_available()`:

- `stock_below_requested_quantity`;
- `made_to_order_not_stock_checked`; and
- `stock_not_configured`.

No warning guarantees availability, production capacity, reservation, or
future fulfillment.

### 6. Authentication and transport

The accepted per-installation Bearer credential has only:

```text
commercial.products.read
commercial.quotes.read
```

It is stored outside both repositories, injected through an approved secret
store or process environment, never put in URLs, responses, fixtures, or
logs, validated on every request, explicitly revocable, and rotatable with
bounded overlap. It maps exactly one installation/business to one approved
MIKE tenant.

API routes use an API-specific branch of Gestar's security middleware or an
equivalent shared authorization layer. They do not depend on browser cookies
and do not open a general bypass. Existing session/role permissions remain
for HTML routes. HTTPS is required outside loopback. HTTP is permitted only
for explicitly enabled local development bound to loopback, with the
credential still mandatory. “Local” is not authentication, and `Host` and
`X-Forwarded-For` are not authorization.

### 7. MIKE timeout and scope

The first operation is the separate `POST /dev/commercial/quote`, disabled by
default and limited to development. It uses explicit IDs and quantities,
creates no event, and does not enter delivery processing. It does not require
OpenAI. Name resolution and continuity remain outside this increment.

The accepted five-second client timeout covers connection establishment,
request transmission, and receipt of the response body. It only stops MIKE
waiting; it does not promise cancellation of the Gestar calculation. MIKE
discards incomplete, malformed, or identity-mismatched responses. This ADR
does not claim that Gestar already has an independently bounded server
execution policy. `calculated_at` remains informative because a quote may
lose commercial validity immediately.

### 8. Gestar revision dependency

The inspected Gestar repository was:

```text
branch: master
HEAD: 92327e92f933dc4d3498b99475a5df8949b6b268
```

The working tree contained pre-existing changes, including
`app/services/pricing_engine.py`, `app/services/sales.py`, and new mixed-price
group files. Mixed-group calculation and sale breakdown were observed in the
working tree, not in that Gestar HEAD. Before implementation, a specific
validated Gestar revision containing the required behavior remains required
before implementation and must be fixed by
commit, tag, or equivalent release artifact. This ADR neither selects,
modifies, stages, publishes, nor cleans Gestar changes.

## Explicit exclusions

Pending orders, confirmation, payments, cash, invoicing, ARCA, reservations,
stock or production mutations, pickup acceptance, external channels,
workers, polling, brokers, new dependencies, Phase 24 changes, and changes
to events 1–12 remain excluded.

## Verification plan

### Block A — Gestar read-only API

Define JSON routes, strict schemas, ARS configuration, commercial date,
selected list, warning vocabulary, machine authentication, installation
binding, and quote reconciliation. Tests cover success, validation/auth
errors, timeout, missing price/list, promotion and mixed-group reconciliation,
and before/after absence of sale, cash, stock, invoice, production, and audit
mutations. Load evidence with representative and adversarial carts is
required before enabling the provisional limits.

### Block B — MIKE explicit-ID client

Add the client only after the API contract and Gestar revision are fixed.
Keep it development-only and disabled by default. Test explicit IDs,
identity mismatch, transport errors, malformed responses, timeout, no OpenAI
dependency, and unchanged Phase 24 state.

### Block C — Names and supervised response

Only later resolve unique names, reject ambiguity, preserve line associations,
present freshness and warnings, and define continuity or order contracts.

## Accepted decision and implementation boundary

The human approval recorded for this ADR is:

> “Apruebo la arquitectura de consulta MIKE–Gestar de ADR-0011 con ese
> alcance; los esquemas HTTP se concretarán antes de implementar las rutas.”

The accepted decisions are:

- HTTP JSON read-only API;
- Gestar as the sole commercial authority;
- ARS and `America/Argentina/Buenos_Aires`;
- current-list selection by Gestar;
- promotions and mixed groups in scope;
- read-only authentication and installation–business–tenant binding;
- explicit-ID development query, disabled by default;
- no changes to events 1–12 or Phase 24;
- five-second MIKE client timeout; and
- provisional input limits requiring evidence before enablement.

The following work remains explicitly pending before implementing routes:

- complete HTTP request, product, quote, and error schemas;
- precise quantity and package-price semantics;
- a fixed, validated Gestar revision with the required capabilities; and
- operational credential and transport configuration.

The acceptance does not authorize deployment, activation, or commercial
changes. Pending work is not represented as completed or approved in detail.

## Implementation work pending

### Commercial

1. Complete the HTTP request, product, quote, and error schemas.
2. Precisely define quantity and package-price semantics.
3. Fix and validate the Gestar revision used for implementation.
4. Complete operational credential and transport configuration.

### Technical and operational

1. Complete `/api/v1/commercial`, `/dev/commercial/quote`, and exact schemas.
2. Complete credential issuance, external storage, revocation, rotation, and
   HTTPS configuration.
3. Complete the installation/business/MIKE-tenant binding configuration.
4. Produce evidence for the five-second client timeout and provisional load
   limits.
5. Validate the fixed Gestar revision used for implementation.
6. Complete safe errors and non-persistent request tracing.

Name resolution, multi-line language entities, continuity, orders, pickup
scheduling, reservations, payments, and external channels may be postponed.

## Consequences

Gestar remains authoritative and the first integration is read-only,
reversible, and testable with explicit IDs without a language model. Costs
include a new API and machine-authentication path, explicit currency and
price-list identity, stale non-reservable quotes, provisional load limits, a
fixed Gestar revision, and future work for names and continuity.
