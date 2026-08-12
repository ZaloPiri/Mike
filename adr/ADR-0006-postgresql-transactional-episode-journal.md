# ADR-0006 — PostgreSQL Transactional Episode Journal

- **Status:** Accepted
- **Date:** 2026-08-12

## Context

Phase 21 introduced `EpisodeJournal` and an `InMemoryEpisodeJournal` implementation.

`EpisodeCoordinator` already depends on the replaceable port.

The in-memory implementation guarantees atomicity and concurrency only within one instance and process. It does not provide durability, recovery after restart, or coordination between processes or workers.

The pipeline retains exactly ten events and ends with:

```text
conversation.response_ready
```

Before delivery, an outbox, or `delivery_requested`, MIKE needs a durable and transactional journal implementation.

Phase 22 implements durable persistence without changing business meaning or the pipeline.

## Decision

Phase 22 introduces:

```text
PostgreSQLEpisodeJournal
```

The approved architecture uses:

- synchronous SQLAlchemy;
- psycopg 3;
- Alembic; and
- an `episodes` / `events` schema.

## Architectural ownership

`PostgreSQLEpisodeJournal` belongs to Orchestration & Event Runtime.

It does not belong to Communication, Verification, or Execution & Skills.

Phase 22 adds no engines. MIKE retains exactly 17 engines.

## Approved relational schema

### `episodes`

The `episodes` relation conceptually contains:

- `episode_id UUID PRIMARY KEY`;
- `tenant_id TEXT NOT NULL`;
- `created_at TIMESTAMPTZ NOT NULL`;
- `updated_at TIMESTAMPTZ NOT NULL`;
- `correlation_id TEXT NULL`;
- `schema_version INTEGER NOT NULL`; and
- a restriction that permits a tenant-safe foreign key through
  `(episode_id, tenant_id)`.

`episode_id` is globally unique.

### `events`

The `events` relation conceptually contains:

- `event_id UUID PRIMARY KEY`;
- `tenant_id TEXT NOT NULL`;
- `episode_id UUID NOT NULL`;
- `sequence INTEGER NOT NULL`;
- a monotonic `journal_position BIGINT`;
- `event_type TEXT NOT NULL`;
- `occurred_at TIMESTAMPTZ NOT NULL`;
- `payload JSONB NOT NULL`;
- `correlation_id TEXT NULL`;
- `causation_id TEXT NULL`; and
- `schema_version INTEGER NOT NULL`.

The schema enforces:

- global uniqueness of `event_id`;
- a tenant-safe foreign key to `episodes` using `episode_id` and
  `tenant_id`;
- `UNIQUE (episode_id, sequence)`;
- a valid `sequence` according to the concrete sequence convention;
- a positive `schema_version`;
- non-empty `tenant_id` and `event_type` values; and
- no cross-tenant association.

Accidental constraint names are not part of this decision.

## Authoritative ordering

`sequence` determines the order of events within an episode.
`CognitiveEpisode.event_ids` is reconstructed by ordering events by
`sequence`.

The `episodes` relation does not duplicate `event_ids` as a UUID array or
JSONB value.

`journal_position` preserves the tenant-wide order returned by
`list_events`. Filtering by `event_type` preserves that order.

`list_episodes` preserves creation order through the initial event or an
equivalent relational representation.

Timestamps do not determine event or episode order.

## Atomic episode creation

`create_episode_with_event` executes in one database transaction. The
episode and its initial event are written and committed together.

Any failure rolls back the complete transaction. No partial episode and no
orphan event become visible or remain stored.

## Atomic append and concurrency

`append_event` performs the following operation:

1. Begin a transaction.
2. Find the episode using tenant-safe criteria.
3. Lock the episode row with `SELECT ... FOR UPDATE` or an equivalent
   database mechanism.
4. Reconstruct the current event IDs in `sequence` order.
5. Compare them exactly with `expected_event_ids`.
6. Raise `EpisodeConcurrencyConflictError` if they differ.
7. Enforce global uniqueness of `event_id`.
8. Determine the next valid `sequence`.
9. Store the event and update the episode within the transaction.
10. Commit once after the complete operation succeeds.

When two processes or workers append against the same episode version,
exactly one succeeds. The other receives
`EpisodeConcurrencyConflictError`, and the losing event is not stored.

## Approved version semantics

The complete `expected_event_ids` tuple remains the authoritative public
episode version. Its content and order are compared exactly.

It is not replaced by an integer, a count, the last `sequence`, or a hash.
Future version optimizations are outside Phase 22.

## Tenant semantics

`tenant_id` remains an opaque `TEXT` identifier. Phase 22 does not create a
`tenants` table.

`event_id` and `episode_id` are globally unique. Cross-tenant reads do not
reveal whether an object exists, and listings return only data belonging to
the requested tenant.

Database constraints and domain validations complement one another; neither
replaces the other.

## Domain reconstruction and immutability

The journal returns `Event` and `CognitiveEpisode` domain objects. It does
not expose ORM models, sessions, or connections.

Persisted values are reconstructed through the domain models. Mutable JSONB
values are therefore frozen again according to `Event` invariants.

`EpisodeCoordinator` and runtime handlers remain unaware of PostgreSQL and
SQLAlchemy.

## Payload and JSONB

JSONB preserves structural value, not original JSON text or object-key
order.

NaN and infinite floating-point values are rejected explicitly. Payloads
are validated before writing, and serialization or numeric-range failures
are translated rather than leaking driver or ORM exceptions.

Phase 22 introduces no new commercial schema per `event_type` and no event
upcasters.

## Timestamps

Timestamps continue to be generated in Python. They remain timezone-aware,
are normalized to UTC, and are persisted as `TIMESTAMPTZ`.

PostgreSQL does not replace the domain clock. Ordering depends on `sequence`
and `journal_position`, not timestamps.

## Error translation

`PostgreSQLEpisodeJournal` does not expose SQLAlchemy `IntegrityError` or
`OperationalError`, or psycopg and SQLAlchemy infrastructure exceptions,
directly through the journal boundary.

The existing public error semantics remain:

- `TypeError` for invalid types;
- `ValueError` for invariant violations, tenant-safe nonexistence, and
  duplicates; and
- `EpisodeConcurrencyConflictError` for version conflicts.

A journal-specific infrastructure exception may follow repository
conventions. Failures do not trigger a fallback, retry, overwrite, or silent
correction.

## Migrations

Alembic is the only approved schema migration mechanism. Migrations are
versioned and auditable.

The application does not call `create_all` at startup and does not run
migrations automatically. Applying migrations is a separate operational
step.

The first migration is limited to the episode journal.

## Configuration

Phase 22 uses the following configuration variables:

```text
MIKE_EPISODE_JOURNAL=memory|postgres
DATABASE_URL=...
```

`MIKE_EPISODE_JOURNAL` requires an explicit selection. Phase 22 defines no implicit default.

`memory` selects `InMemoryEpisodeJournal`.

`postgres` selects `PostgreSQLEpisodeJournal`.

There is no silent fallback between journal implementations.

Selecting `postgres` without `DATABASE_URL` causes a clear startup failure.

Selecting `postgres` when PostgreSQL is unavailable or the required schema is missing or incompatible causes a clear startup failure.

Real credentials are not stored in Git.

`.env.example` may document variable names and non-secret example values during implementation.

The SQLAlchemy engine and connection pool are created and closed through the application lifecycle.

Importing modules does not open database connections or create external infrastructure.

## In-memory implementation

`InMemoryEpisodeJournal` remains available for rapid local development and unit tests.

It does not provide durability, recovery after restart, or coordination between processes or workers, and it shall not be represented as providing those guarantees.

The durable production mode is `postgres`.

`InMemoryEpisodeJournal` and `PostgreSQLEpisodeJournal` shall satisfy a shared contract test suite. Tests that depend on object identity, the internal lock, or other implementation-specific in-memory behavior remain separate.

Each application instance selects exactly one journal implementation. The two implementations shall not operate simultaneously as parallel sources of truth within the same application instance.

## Testing strategy

Phase 22 requires a shared contract test suite for:

- `InMemoryEpisodeJournal`; and
- `PostgreSQLEpisodeJournal`.

The PostgreSQL implementation shall be tested against a real PostgreSQL instance. SQLite and mocks do not provide evidence for PostgreSQL transactions, row locking, constraints, rollback, or concurrency and shall not replace those tests.

The required PostgreSQL coverage includes:

- application of the Alembic migration;
- atomic episode creation;
- atomic event append;
- complete rollback after failure;
- exact comparison of `expected_event_ids`, including content and order;
- explicit concurrency conflicts;
- global duplicate `event_id` rejection;
- tenant-safe reads and lists;
- tenant isolation;
- authoritative episode ordering by `sequence`;
- tenant-wide event ordering by `journal_position`;
- filtered event ordering;
- reconstruction of immutable `Event` and `CognitiveEpisode` objects;
- two concurrent connections appending to the same episode and expected version, with exactly one successful commit;
- concurrent appends to different episodes;
- persistence after closing and reconstructing the journal, engine, or application;
- HTTP integration;
- preservation of exactly ten pipeline events; and
- no real external calls.

The approved test configuration variable is:

    MIKE_TEST_DATABASE_URL=...

It may reference a local PostgreSQL instance or a dedicated test database.

Tests shall never run against a production database. They shall isolate and clean their data without depending on execution order.

Docker, Testcontainers, and CI are not requirements of Phase 22.

Phase 22 is not considered verified or complete until the PostgreSQL tests have run successfully against a real PostgreSQL instance.

## Health and availability

The existing HTTP contract of `/health` remains unchanged.

Phase 22 does not convert `/health` into PostgreSQL readiness. A separate readiness endpoint remains outside the scope of this phase.

When `postgres` mode is selected, missing required configuration, unavailable PostgreSQL infrastructure, or an incompatible or missing required schema shall cause a clear startup failure.

The application shall not degrade automatically or silently to `InMemoryEpisodeJournal`.

## Compatibility

Phase 22 does not change:

- the public `EpisodeJournal` Protocol;
- `EpisodeCoordinator`;
- synchronous handlers;
- the synchronous dispatcher;
- existing event types;
- existing event payloads;
- pipeline order;
- the ten existing events;
- `conversation.response_ready` as the terminal event;
- the HTTP request or response contracts of `POST /dev/messages`;
- development inspection endpoint contracts;
- the meaning of Verification; or
- the seventeen engines.

Phase 22 does not connect a channel and performs no delivery.

## Out of scope

The following remain outside Phase 22:

- asynchronous conversion;
- a `tenants` table;
- an outbox;
- an inbox;
- `delivery_requested`;
- channel adapters;
- sending;
- acknowledgements;
- retries;
- backoff;
- dead-letter handling;
- provider idempotency;
- pipeline changes;
- new engines;
- new commercial rules;
- event upcasters;
- partitioning;
- archival;
- read replicas;
- high availability;
- advanced observability;
- Docker;
- Testcontainers;
- CI;
- Railway deployment;
- a readiness endpoint; and
- automatic migrations at application startup.

## Consequences

### Positive

- Events and episodes can survive process and application restarts.
- Episode creation and append gain real transactional atomicity.
- PostgreSQL row locking and constraints coordinate concurrent processes and workers.
- Database constraints reinforce global identifiers, tenant-safe relationships, and episode ordering.
- The durable implementation remains replaceable behind the existing `EpisodeJournal` port.
- Handlers, the dispatcher, and `EpisodeCoordinator` remain independent of PostgreSQL and SQLAlchemy.
- The result provides a safer persistence foundation for a future, separately approved outbox or delivery decision.

### Costs

- SQLAlchemy, psycopg, and Alembic add dependencies and maintenance surface.
- PostgreSQL becomes required infrastructure for durable operation.
- Schema evolution requires versioned migrations and a separate operational migration step.
- The application must manage engine and pool lifecycle.
- Database and driver errors must be translated into stable domain semantics.
- PostgreSQL integration and concurrency tests are slower than in-memory unit tests.
- A real PostgreSQL test instance is required to verify the implementation.
- Deployment and local development gain additional configuration and operational complexity.
- JSONB and SQL impose serialization and numeric restrictions that the in-memory implementation did not previously enforce.

Phase 22 prepares a persistence foundation for later architectural decisions. It does not approve an outbox, delivery, `delivery_requested`, Phase 23, or any later phase.
