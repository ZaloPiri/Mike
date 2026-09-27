# ADR-0009 — Recoverable Delivery Processing and Development Adapter

- **Status:** Accepted
- **Date:** 2026-09-27

## Context

Phase 23 ends with event 11, `communication.delivery_requested`, and one
`delivery_outbox` row in `pending`. Creation of the event, episode update,
and outbox row is atomic, as decided by ADR-0007 and constrained by ADR-0008.

Phase 23 does not process the request. There is no claim, lease, adapter,
receipt, recovery, acceptance, or external send. The Phase 23 dispatcher is
not a durable worker and event 11 remains stored without dispatch.

Phase 24 must demonstrate durable, recoverable, and idempotent processing
before any Gestar, WhatsApp, or real-channel integration. The scope remains
internal and explicitly controlled. There is no permanent worker: processing
is started only by an explicit local development `run-once` operation, and
each invocation handles at most one eligible request.

## Decision

### 1. Processing boundary and states

Phase 24 adds processing after the committed Phase 23 boundary. It does not
change events 1–11, their payloads, or the atomic creation of event 11 and
the outbox row.

`delivery_outbox.status` may contain exclusively:

- `pending` — eligible when its PostgreSQL-authoritative `available_at` has arrived;
- `processing` — held by one unexpired claim;
- `completed` — finalization and event 12 have committed; or
- `failed` — processing has permanently stopped or exhausted its attempts.

The only valid transitions are:

```text
pending → processing
processing → pending       (recoverable transient failure)
processing → completed
processing → failed
expired processing → processing (reclaim with a new claim)
```

There are no transitions from `completed` or `failed`. A failed row does not
claim that an external recipient received anything.

Phase 24 adds nullable `delivery_accepted_event_id` to the outbox. It is
conceptually required exactly when status is `completed`, and forbidden for
all other statuses by a compatible CHECK constraint. It references event 12
through the tenant-safe and episode-safe composite relationship:

```text
(delivery_accepted_event_id, episode_id, tenant_id)
→ events(event_id, episode_id, tenant_id)
```

The pointer is unique, one-to-one with the outbox, is set only by T3, and
cannot be replaced after completion. The foreign key proves existence and
ownership, not `event_type`; T3 validates
`communication.delivery_accepted`. T3 locks the corresponding outbox row,
requires `processing`, a matching current token, and a valid lease, then
creates event 12, updates the episode, sets the pointer, and changes the
status to `completed` in one transaction. A physical uniqueness constraint or
equivalent approved relational guarantee prevents one event ID from being
associated with multiple outbox rows. No triggers are added and the events
primary key is unchanged.

Ordinary append rejects `communication.delivery_accepted` before mutation.
Only the atomic finalization operation may persist it; this protection
applies to `EpisodeCoordinator`, `InMemoryEpisodeJournal`,
`PostgreSQLEpisodeJournal`, and every supported public API. The maximum-one
event-12 guarantee is the combined result of the outbox lock, terminal state,
claim token and lease, unique pointer, one-to-one relationship, CHECK,
protected append, and idempotent finalization.

### 2. Claim, lease, attempts, and errors

The claim is atomic and tenant-safe. It records, at minimum, a unique claim
token, acquisition time, lease expiry, attempt count, next eligible time, and
a safe bounded last error when applicable. PostgreSQL is authoritative for
the clock used for leases and eligibility.

The defaults are fixed and validated:

- lease: 60 seconds;
- no lease renewal;
- maximum adapter invocations: three;
- adapter timeout: 10 seconds;
- after transient attempt one: 30 seconds;
- after transient attempt two: 120 seconds.

If a separate claim counter is needed, it is distinct from
`adapter_attempt_count`. Only `adapter_attempt_count` is the processing
attempt count: it increases exactly once immediately before each real adapter
invocation. Claiming, reclaiming, inspection, receipt lookup, and receipt
reuse do not increment it. There are at most three real invocations. A
transient failure after invocation one waits 30 seconds; a transient failure
after invocation two waits 120 seconds; the third failed invocation ends in
`failed` with no new eligibility. A permanent failure ends directly in
`failed`, regardless of attempts remaining.

At most one unexpired claim exists for a request. A valid claim cannot be
taken by another processor. An expired claim can be reclaimed with a new
token; the stale owner cannot finalize, release, or modify the request.
PostgreSQL coordination uses database locking and does not depend on global
Python locks.

Transient failure returns to `pending` with the specified backoff while
attempts remain. Permanent failure transitions directly to `failed`. Unknown
result or timeout first consults the durable adapter storage; if a compatible
successful receipt exists, processing follows it without repeating the
effect, and if none exists the adapter is retried with the same
`idempotency_key`. Unexpected errors leave no partial state and preserve
recovery. Failure transitions are protected transactions that validate the
outbox, tenant, token, and current authority; a stale processor cannot record
a failure against a newer claim. Persisted errors are bounded and safe: they
do not contain secrets, SQL, parameters, DSNs, or raw driver messages.

The in-memory implementation mirrors the functional transitions with an
injectable clock, but does not promise persistence after restart or
multiprocess coordination.

### 3. Three transaction boundaries

Processing has three independent commits. No database transaction or journal
lock remains open while the adapter runs.

**T1 — claim**

1. Select at most one eligible request, tenant-scoped, using an atomic claim.
2. Lock it, including expired `processing` rows eligible for recovery.
3. Set `processing`, claim token, lease, acquisition time, and the
   unambiguous attempt record/count.
4. Commit before invoking the adapter.

**T2 — development adapter receipt**

1. Process the immutable outbox snapshot with the internal adapter.
2. Persist a durable, idempotent receipt in its own table.
3. Use exactly the Phase 23 `idempotency_key`.
4. Create or reuse a receipt only for a successful adapter acceptance.
5. Return the existing receipt for the same key and identical snapshot.
6. Return an immutable conflict for the same key and a different snapshot.
7. Commit independently.

The receipt preserves the request identity, tenant, idempotency key, an
unequivocal snapshot hash or representation, adapter result, and stable
receipt identity. A receipt is exclusively durable evidence of a successful
development-adapter acceptance. Transient failure, permanent failure,
timeout without confirmed acceptance, and unknown result do not create a
receipt; those outcomes belong to outbox technical history. A compatible
successful receipt is sufficient for T3 after a crash. A durable receipt does
not itself authorize finalization: a current claim, matching token, and
valid lease are always required.

**T3 — finalization**

1. Verify the claim token and lease are still valid, and require status
   `processing`.
2. Verify the compatible receipt and its accepted result.
3. Set the outbox to `completed`.
4. Append event 12 and update the episode in the same commit.

T3 is one atomic PostgreSQL transaction. A stale token or expired lease is
rejected without mutation. If T2 committed a successful receipt and the lease
then expires, the old processor cannot complete the outbox, create event 12,
update the episode, change status, or renew the lease. A later `run-once`
claims it with a new token, consults the same idempotency key, reuses the
compatible receipt without another adapter attempt, and continues to T3. If
no receipt exists it invokes the adapter with the same key under the normal
attempt and timeout rules; an incompatible snapshot is a conflict and cannot
overwrite the receipt or create event 12. A crash
before T3 commits leaves the request recoverable; a crash during T3 rolls
back `completed`, the episode update, and event 12 together. After a
successful T3 commit, repetition returns the stable completed result and
cannot create another event 12. Thus T2 and T3 are not presented as one
impossible cross-transaction atomic operation; durable receipt plus guarded
T3 provides convergence.

### 4. Development adapter

Phase 24 contains exactly one internal development adapter. It is local,
durable, deterministic, network-free, and has no Gestar, WhatsApp, external
API, or commercial action. It does not represent delivery to or reading by a
customer.

It can deterministically simulate success, transient failure, permanent
failure, and unknown result for tests. Only success creates a receipt. Receipt
idempotency applies to the existing request: the same key and same snapshot
reuse the receipt, while the same key with different content, target, tenant,
or request identity is an immutable conflict and cannot overwrite it.

### 5. Event 12

Successful finalization creates exactly one stored, undispatched event:

```text
event_type = communication.delivery_accepted
```

It has the same `tenant_id` and `episode_id` as event 11, is immediately
after event 11, and uses:

```text
causation_id = str(delivery_request_event_id)
correlation_id = event_11.correlation_id  # copied exactly, including None
```

The minimal versioned payload contains only references sufficient to relate
event 11, `response_ready_event_id`, the outbox row, the durable receipt, and
the internal acceptance method (including the adapter/channel identifiers).
It does not duplicate the complete response text.

Event 12 is created only during successful T3, at most once per delivery
request, and no route creates event 13. It means durable acceptance by the
development adapter, not human reading, external delivery, order fulfillment,
or commercial success.

### 6. Run-once operation

An explicit local development-only `run-once` operation processes at most one
request and returns a structured result distinguishing:

- no eligible work;
- completed;
- reprogrammed (`pending` with a future eligibility time); and
- failed.

It has no permanent loop, polling, background execution, startup execution,
or automatic execution during application creation or lifespan. It requires
a tenant and is not a general administrative interface. Production
administrative authentication is not approved by this ADR.

### 7. Guarantees and tenant safety

Phase 24 guarantees:

- one current claim per request;
- durable idempotent receipt processing;
- no `completed` without a valid compatible receipt;
- no event 12 without `completed`;
- no duplicate finalization or event 12;
- no completed row without a non-null `delivery_accepted_event_id`;
- no non-completed row with `delivery_accepted_event_id`;
- stale-token rejection;
- safe recovery after crashes between T1, T2, and T3;
- tenant isolation for every read and write; and
- PostgreSQL processing through the single engine shared by the application
  lifecycle.

Exactly-once external delivery is not promised. Adapter invocations may
repeat, but the durable receipt and Phase 23 idempotency key prevent duplicate
internal acceptance effects.

### 8. Migration and metadata

A new versioned Alembic migration may add only the fields strictly required
for claim, lease, attempts, eligibility, errors, and finalization to
`delivery_outbox`; create the durable development-adapter receipt table; and
add the required constraints, indexes, and tenant-safe relationships.
Metadata and migration must remain equivalent. Historical migrations are not
modified. `create_all` is not used and the application does not run Alembic
automatically.

Downgrade performs an explicit read-only history check before destructive DDL
and aborts with a safe, clear error if any `processing`, `completed`, or
`failed` rows, `adapter_attempt_count > 0`, claim or lease data,
`delivery_accepted_event_id`, receipts, event 12 records, or other Phase 24
history exists. Only an empty Phase 24 history permits removing its schema.
It never deletes first and checks later, silently deletes history, converts
`completed` to `pending`, or alters Phase 23 constraints or data except for
Phase 24 additions. Historical migrations remain unchanged.

### 9. Required PostgreSQL verification

Real PostgreSQL tests with independent connections must cover:

- simultaneous claims and one winner per request;
- two finalizers competing for one outbox and exactly one event 12;
- uniqueness of `delivery_accepted_event_id`;
- event-12 foreign keys across tenants and episodes;
- CHECK consistency for completed and non-completed pointers;
- protected ordinary append in memory, PostgreSQL, and coordinator;
- concurrent processing of different requests;
- valid and expired leases;
- crashes after T1, after receipt creation in T2, and during T3;
- lease expiry after T2, stale rejection without mutation, and new-claim
  receipt reuse;
- stale tokens;
- compatible and incompatible duplicate receipts;
- receipt creation only on success and no receipt for transient, permanent,
  timeout, or unknown outcomes without confirmed acceptance;
- unknown outcomes with and without an existing receipt;
- duplicate event 12 prevention;
- backoff and exhaustion of three attempts;
- recovery without incrementing `adapter_attempt_count`;
- transient, permanent, unknown, timeout, and rollback behavior;
- cross-tenant isolation;
- migration upgrade, safe downgrade, blocked downgrade, and re-upgrade;
- downgrade blocked before DDL when history exists and permitted when empty;
- equivalent metadata and migration;
- rollback without event 12, completed status, or partial pointer;
- preserved first eleven events and no event 13; and
- one shared engine across lifecycle with no automatic processing.

Memory tests must state its reduced durability and coordination guarantees.

### 10. Compatibility

The decision preserves ADR-0007 and ADR-0008: events 1–11, their envelopes
and payloads, atomic event-11/outbox creation, ownership constraints,
canonical outbox ordering, existing HTTP contracts, the 17 engines,
`memory|postgres` selection, lifecycle behavior, tenant safety, and the
existing append behavior remain intact.

Event 12 appears only after an explicit successful `run-once`. No external
call is introduced and no previous event is changed.

### 11. Out of scope

The following are not approved: Gestar; WhatsApp; email, SMS, social media,
or any real send; permanent workers, daemons, automatic polling, brokers or
external queues; multiple adapters; real-channel routing; commercial actions,
orders, prices, or stock; production administrative authentication; external
observability; deployment; Phase 25; events after event 12; and changes to
events 1–11.

## Consequences

### Benefits

- Durable, recoverable processing is demonstrable.
- Concurrent claims and idempotent receipts are verifiable.
- Crashes can converge without duplicate internal acceptance or event 12.
- A future real-channel integration has a controlled boundary.
- No additional external infrastructure is required.

### Costs

- A migration, receipt table, mutable states, leases, and backoff are added.
- Three transaction boundaries and recovery paths increase complexity.
- Real PostgreSQL concurrency and migration tests are required.
- The development adapter does not communicate outside MIKE.
- Memory remains non-durable and single-process.
