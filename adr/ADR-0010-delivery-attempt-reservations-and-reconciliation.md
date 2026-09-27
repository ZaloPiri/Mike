# ADR-0010 — Delivery Attempt Reservations and Reconciliation

- **Status:** Accepted
- **Date:** 2026-09-27

## Context

ADR-0009 approves recoverable delivery processing through a development
adapter, durable successful receipts, three transaction boundaries, a
60-second lease, a 10-second adapter timeout, at most three attempts, 30- and
120-second backoffs, and atomic finalization of event 12.

Implementation review identified three decisions that require an explicit
complement:

1. `adapter_attempt_count` cannot be interpreted as an exact count of calls
   that actually ran when a process can fail after reserving an attempt and
   before invoking the adapter.
2. A timeout or unknown result does not prove that an operation did not accept
   the snapshot. Late acceptance must be reconciled and must not create a
   receipt after a valid terminal `failed` state.
3. `run-once` must not be callable merely because an endpoint has a
   `/dev/` prefix. It must be disabled by default and explicitly enabled
   only for local development.

This ADR complements ADR-0009. It prevails only over ADR-0009's
interpretation of `adapter_attempt_count`, its unresolved timeout/unknown
result/late-acceptance rules, and its local-development activation rule. It
does not change T1, T2, T3, the lease duration, timeout duration, maximum
attempt budget, backoffs, successful-receipt model, event 12, or any Phase 23
event and outbox decision from ADR-0007 and ADR-0008.

## Decision

### 1. Durable attempt reservations

The field name `adapter_attempt_count` is retained. It represents durable
authorized and reserved adapter attempts, not an exact count of invocations
that were effectively executed.

A reservation is incremented and committed by a protected operation before a
new adapter invocation is authorized. Every real invocation requires its own
reservation. One reservation never authorizes repeated calls.

The rules are:

- a crash after reservation and before invocation may consume the attempt;
- a consumed reservation is never returned or decremented;
- at most three reservations exist for one delivery request;
- claiming or reclaiming a request does not consume a reservation;
- inspecting or reusing a compatible receipt does not consume a reservation;
- a recovered process cannot reuse an earlier reservation to start another
  call;
- the receipt is consulted before reserving another invocation;
- a compatible receipt permits finalization even when all three reservations
  are consumed; and
- when the budget is exhausted without a receipt, no fourth invocation may
  start. The request must be reconciled safely before it is terminally
  failed.

The first and second reservations use the approved 30- and 120-second
reprogramming delays after transient results, respectively. A third failed
reserved invocation ends in `failed` without new eligibility. A permanent
failure ends directly in `failed`, independent of remaining reservations.

This decision does not claim that `adapter_attempt_count` measures calls
that actually ran.

The reservation is confirmed in its own protected transaction before the
adapter is invoked. Publication of a successful receipt occurs in a later,
independent transaction. A failure or rollback during the invocation or
receipt publication does not undo a reservation that has already committed.

T1, T2, and T3 retain their names as processing stages; they do not require
exactly three database transactions in every execution. This clarification
prevails over any reading of ADR-0009 that would require the reservation and
successful-receipt insertion to share one transaction. It does not change T3:
event 12, the episode update, the acceptance pointer, and `completed` remain
one atomic finalization commit.

### 2. Timeout and reconciliation

The ten-second timeout is an actual limit on the invocation boundary. It is
not evidence that the underlying operation was cancelled or that acceptance
did not occur. The timeout boundary and post-timeout reconciliation are
separate concerns: a run-once operation need not complete its entire
reconciliation exactly ten seconds after it began, and stopping a local wait
does not automatically stop work already executing.

The processor must not manufacture a receipt for timeout or unknown result.
It must query durable adapter storage first:

- a compatible, previously confirmed receipt is an accepted result and may
  proceed to T3 under a current claim;
- without such a receipt, the same idempotency key may be retried only when a
  reservation remains;
- a locally calculated result that was not confirmed by a durable receipt is
  not durable acceptance; and
- an incompatible snapshot is an immutable conflict and cannot overwrite a
  receipt.

Receipt publication and failure transitions are coordinated transactionally
against the same delivery request. The check for absence of a receipt and
the decision to make the request terminally `failed` cannot leave a race in
which a late compatible acceptance is confirmed afterward.

The required race outcomes are deterministic:

- if a compatible acceptance wins and is confirmed first, the request is not
  declared `failed`; processing recovers its finalization;
- if a valid `failed` transition wins first, no earlier operation may later
  confirm a receipt for that request;
- an operation with an expired or replaced claim cannot publish a receipt or
  any other durable effect;
- a successful receipt is never deleted to force `failed`; and
- claim replacement prevents the former processor from publishing effects.

A compatible receipt never grants finalization authority by itself. T3 still
requires a current claim, matching token, valid lease, compatible receipt,
and the approved episode/event conditions.

The implementable sequence remains:

1. T1 claims or reclaims at most one request.
2. T2 checks the receipt before reserving an attempt.
3. If no receipt exists and budget remains, T2 reserves once, invokes within
   the ten-second boundary, and persists a receipt only for confirmed
   success.
4. Timeout and unknown result enter reconciliation, not fabricated success.
5. A current claim with a compatible receipt proceeds to T3.
6. Failure transitions are protected by the same request authority and are
   rejected for stale claims.
7. Once a valid terminal `failed` transition commits, a prior operation
   cannot publish a receipt afterward.

The existing Phase 24 implementation must be brought into compliance with
this sequence. In particular, a constant alone is not an effective timeout,
and a receipt/failure race is not resolved merely by application-level
ordering.

No permanent worker, polling loop, new processing state, external broker, or
external delivery guarantee is introduced.

### 3. Local development activation

`run-once` is disabled by default.

It may be enabled explicitly only in the project's recognized development
environment. Any configuration attempting to enable it outside development
must be rejected clearly. When disabled, the endpoint cannot execute
processing.

When enabled, the operator must bind the server exclusively to loopback and
must not publish it through a proxy, tunnel, or port forwarding. The
application distinguishes controls it can verify from deployment constraints
it cannot observe:

- the `/dev/` prefix is not authorization;
- `Host` and `X-Forwarded-For` headers are not authorization;
- the application must not claim knowledge or control of the server's real
  bind address unless that information is explicitly available to it;
- tenant identity remains explicit on every operation; and
- production administrative authentication is not introduced by this ADR.

This activation change applies only to the new run-once operation. Existing
endpoints are not broadened or reclassified.

### 4. Continuing Phase 24 obligations

The following remain implementation obligations from ADR-0009 and are not
new functional decisions:

- ordinary append is protected against
  `communication.delivery_accepted`;
- T3 validates the complete preceding event chain;
- state and claim-field combinations are valid and mutually consistent;
- PostgreSQL is authoritative for lease, eligibility, and backoff timing,
  evaluated at the correct point after relevant locks are acquired;
- downgrade obtains effective writer exclusion from its history check through
  destructive DDL;
- schema verification detects an incomplete Phase 24 schema; and
- new memory-contract and real-PostgreSQL tests cover the approved behavior.

Memory need not receive auxiliary indexes when its existing structures and
single publication lock already demonstrate the guarantee.

### 5. Required evidence

The implementation must add tests for:

- a crash after reservation and before adapter invocation;
- exactly three reservations and no fourth invocation;
- recovery with a compatible receipt after all three reservations are
  consumed;
- exhausted budget without a receipt;
- an effective ten-second timeout;
- an operation attempting completion after timeout;
- receipt-versus-`failed` races in both commit orders;
- expired and replaced claim tokens;
- recovery without consuming another reservation;
- run-once disabled by default;
- explicit development enablement and rejection outside development;
- functional equivalence between memory and PostgreSQL; and
- real PostgreSQL persistence races using independent connections and
  controlled synchronization.

The existing ADR-0009 exclusions remain: no Gestar, WhatsApp, external
network, permanent worker, polling, event 13, or Phase 25.

## Consequences

### Benefits

- The attempt budget remains durable and honest about what it measures.
- Late and unknown outcomes cannot silently manufacture acceptance.
- A valid terminal failure cannot later be contradicted by a stale process.
- Local processing is opt-in and clearly separated from production exposure.
- ADR-0009 remains stable except for the explicitly superseded
  interpretations.

### Costs

- Attempt reservations may be consumed without a corresponding call.
- Timeout reconciliation requires durable coordination and race tests.
- Local development activation requires explicit configuration and deployment
  discipline.
- PostgreSQL concurrency tests are required before implementation can be
  considered complete.

## Implementation compatibility

The current implementation must be reviewed against this ADR before Phase 24
is declared complete. Known compatibility checks include:

- reservation commits and crash recovery;
- actual timeout enforcement;
- receipt publication fencing;
- terminal-failure fencing;
- protected event-12 append;
- complete T3 chain validation;
- PostgreSQL clock and lock ordering;
- downgrade writer exclusion;
- complete schema verification; and
- development-only, disabled-by-default run-once activation.

These are verification targets, not additional architecture. No new
mechanism outside this decision is approved.

