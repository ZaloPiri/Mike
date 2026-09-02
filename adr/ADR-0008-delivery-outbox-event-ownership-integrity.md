# ADR-0008 — Delivery Outbox Event Ownership Integrity

- **Status:** Accepted
- **Date:** 2026-08-23

## Context

ADR-0007 approved the atomic creation of event 11,
`communication.delivery_requested`, and its corresponding
`delivery_outbox` entry.

The first Phase 23 implementation proposed individual foreign keys from
`delivery_request_event_id` and `response_ready_event_id` to
`events.event_id`. Those foreign keys prove that each globally unique event
identifier exists, but they do not physically guarantee that either event
belongs to the `episode_id` and `tenant_id` recorded by the outbox entry.

Python validation protects the normal application path, but it does not
replace the required relational integrity. The Phase 22 schema makes
`event_id` globally unique, but it does not provide a referenceable key that
includes `event_id`, `episode_id`, and `tenant_id`.

The Phase 23 review also identified:

- event 11 lacked its required causation and correlation envelope;
- ordinary append operations could persist
  `communication.delivery_requested` without an outbox entry;
- trace-envelope validation across the ten-event chain was incomplete; and
- in-memory and PostgreSQL outbox listings used different ordering rules.

## Decision

ADR-0008 complements ADR-0007. It prevails only over the statement in
ADR-0007 that the second migration creates exclusively `delivery_outbox`.
It neither replaces nor modifies any other ADR-0007 decision.

### 1. Composite Event Ownership Key

The Phase 23 migration shall add to `events` a composite unique constraint
equivalent to:

```text
UNIQUE (event_id, episode_id, tenant_id)
```

`event_id` remains the globally unique primary key and continues to define
event identity. The composite constraint does not change that identity. Its
sole purpose is to provide a referenceable key that expresses episode and
tenant ownership.

The Phase 22 migration is not modified retroactively. This change is made
only by the new, versioned Phase 23 migration. This ADR does not prescribe
the final physical name of the constraint.

### 2. Composite Foreign Keys

`delivery_outbox` shall retain its tenant-safe relationship with `episodes`:

```text
(episode_id, tenant_id)
→ episodes(episode_id, tenant_id)
```

It shall also use relationships equivalent to:

```text
(delivery_request_event_id, episode_id, tenant_id)
→ events(event_id, episode_id, tenant_id)

(response_ready_event_id, episode_id, tenant_id)
→ events(event_id, episode_id, tenant_id)
```

These composite foreign keys physically guarantee that the referenced event
11 and event 10 exist and that each belongs to the same episode and tenant as
the outbox entry.

The composite foreign keys guarantee existence and ownership only. They
cannot by themselves guarantee `event_type` or positions 10 and 11. Event
type, order, payload, references, and semantic consistency remain validated
inside the application transaction.

Individual foreign keys from the event identifier columns to
`events.event_id` are insufficient and shall not be retained as substitutes
for the composite foreign keys. No trigger or column is added.

### 3. Migration Lifecycle

Upgrade shall, in order:

1. Add the composite unique constraint to `events`.
2. Create `delivery_outbox`.
3. Create its approved constraints.
4. Create its tenant-safe foreign key to `episodes`.
5. Create both composite foreign keys to `events`.

Downgrade shall, in order:

1. Drop `delivery_outbox`.
2. Drop from `events` only the composite unique constraint added by Phase 23.

Downgrade does not modify any other Phase 22 constraint. Upgrade, downgrade,
and SQLAlchemy metadata shall agree. The migration adds no defaults,
cascades, future columns, or dependencies. It does not use `create_all`, and
the application does not run migrations automatically.

### 4. Event 11 Trace Envelope

`communication.delivery_requested` shall set:

```text
causation_id = str(response_ready_event_id)
```

Its `correlation_id` shall be propagated exactly from
`conversation.response_ready`. Under the current event 10 contract, that
value may be `None`. Phase 23 does not additionally require event 11 to match
an episode correlation that event 10 does not propagate.

`source_event_id` in the payload continues to identify the original
`message.received` event. `response_ready_event_id` in the payload continues
to identify event 10. `causation_id` belongs to the `Event` envelope and
identifies event 10; `correlation_id` also belongs to the `Event` envelope.
Neither field is added to the payload.

Event 11 shall be rejected when the preceding chain does not satisfy the
approved trace conventions. This decision does not redefine the conventions
of the first ten events. Validation shall follow the existing, approved
contract for each event type. Phase 23 does not add correlation propagation
or immediate causation to events 1 through 10.

### 5. Protected Append

Ordinary operations equivalent to:

```text
EpisodeJournal.append_event(...)
EpisodeCoordinator.append_to_episode(...)
```

shall explicitly reject `communication.delivery_requested`. That event type
may be persisted only through the atomic operation equivalent to:

```text
append_event_with_outbox(...)
```

This guarantee applies to `InMemoryEpisodeJournal`,
`PostgreSQLEpisodeJournal`, and every supported public path through
`EpisodeCoordinator`.

No other existing event type is blocked, and the historical semantics of
ordinary append remain unchanged. The check uses value equality, not Python
object identity, and occurs before any mutation. Event 11 cannot exist
without an outbox entry through a supported public API.

This is an invariant of the application and persistence boundary; it does
not require a database trigger.

### 6. Full Trace-Chain Validation

Before event 11 is created, both the handler and the atomic persistence
boundary shall validate the complete ten-event chain according to its current
contracts, including:

- the exact count, event types, and order;
- one common `tenant_id` and `episode_id`;
- the complete, ordered expected event identifiers;
- `source_event_id` according to its established convention;
- the event-specific predecessor references;
- `correlation_id` and `causation_id` for events 1 through 10 according to
  each event's real, current contract, including `None` wherever that is the
  approved value;
- `conversation.response_ready` as event 10; and
- event 11 `correlation_id` exactly equal to event 10 `correlation_id`, event
  11 `causation_id` equal to `str(response_ready_event_id)`, and consistency
  among event 10, event 11, and the outbox snapshot.

No new references are invented for previous events; their existing contracts
are validated. An altered trace envelope is any `correlation_id` or
`causation_id` value different from the value expected by the applicable
current contract, including a non-`None` value where `None` is expected. Such
a chain shall be rejected before mutation. Every failure leaves exactly the
preceding ten events and creates neither event 11 nor an outbox entry.

### 7. Canonical Outbox Ordering

In-memory and PostgreSQL implementations shall use the same canonical order:

1. `created_at` ascending.
2. `outbox_id` ascending as the deterministic tie-breaker.

Only already approved columns are used. No `journal_position` or other column
is added. This is not insertion order: inverted timestamps are ordered by
`created_at`, and equal timestamps are resolved by `outbox_id`. UUID ordering
shall be semantically equivalent in both implementations. Tenant-safe filters
preserve the same ordering.

### 8. Required Tests

The implementation shall prove at least:

- the event 10 composite foreign key with an existing UUID from another
  episode;
- the event 10 composite foreign key with an existing UUID from another
  tenant;
- the event 11 composite foreign key with an existing UUID from another
  episode;
- the event 11 composite foreign key with an existing UUID from another
  tenant;
- equivalent metadata and migration definitions;
- a real upgrade/downgrade/upgrade cycle;
- event 11 causation and exact correlation equality with event 10, including
  the current `None` case;
- rejection of chains with altered `causation_id` or `correlation_id`;
- rejection of `communication.delivery_requested` through ordinary append in
  memory and PostgreSQL, without mutation;
- equivalent memory and PostgreSQL ordering with inverted and equal
  timestamps; and
- real rollback without orphaned events or outbox entries.

### 9. Compatibility

This decision preserves:

- the approved exactly-once internal request semantics;
- terminal event 11 and the pipeline of exactly eleven events;
- the first ten event types and payloads;
- exactly 17 engines;
- existing HTTP contracts;
- explicit `memory|postgres` selection;
- the absence of external calls; and
- the absence of workers, adapters, retries, sending, or new dependencies.

### 10. Out of Scope

ADR-0008 does not approve:

- triggers;
- changing the `events` primary key;
- new columns;
- workers, claiming, or processing;
- retries;
- adapters or real channels;
- sending or later delivery states;
- Phase 24;
- standardizing or newly propagating `correlation_id` or `causation_id`
  through events 1 through 10, which requires a separate future decision;
- retroactive modification of the Phase 22 migration;
- rewriting ADR-0007; or
- any new decision not enumerated here.

## Consequences

### Positive

- Event ownership is physically guaranteed.
- Cross-tenant and cross-episode event references are prevented.
- Event 11 has complete traceability.
- Supported ordinary append cannot create event 11.
- Altered chains are rejected.
- Both journals use identical outbox ordering.
- The guarantees can be audited against real PostgreSQL.

### Costs

- The Phase 23 migration adds a constraint to `events`.
- Downgrade must remove that constraint.
- Additional validation and tests are required.
- The composite constraint is redundant for event identifier uniqueness but
  necessary to express ownership.
- Outbox processing and sending still do not exist.
