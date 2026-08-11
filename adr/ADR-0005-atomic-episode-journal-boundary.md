# ADR-0005 — Atomic Episode Journal Boundary

- **Status:** Accepted
- **Date:** 2026-08-11

## Context

The current pipeline ends with `conversation.response_ready` as its tenth event.

Events and episodes are currently stored in:

- `InMemoryEventStore`; and
- `InMemoryEpisodeStore`.

`EpisodeCoordinator` depends on these concrete classes.

The current compound append performs two separate operations:

1. append the event to the event store;
2. update the episode in the episode store.

There is no transaction between those operations. If the second operation fails after the first succeeds, an event can remain stored without being referenced by its episode.

The current stores also do not provide:

- durability;
- recovery after restart;
- coordination between processes;
- locks;
- version control;
- compare-and-swap; or
- sufficient protection against concurrent append.

Phase 21 does not implement delivery. Before creating `delivery_requested` or an outbox, MIKE needs a replaceable persistence boundary that atomically preserves the invariants between events and episodes.

## Decision

Phase 21 introduces a runtime boundary conceptually named:

```text
Atomic Episode Journal Boundary
```

The conceptual port may be named `EpisodeJournal`, consistent with the repository vocabulary.

Its responsibility is to maintain jointly:

- events;
- episodes;
- tenant membership;
- event order;
- uniqueness;
- version control; and
- logical atomicity of compound operations.

This boundary belongs to Orchestration & Event Runtime because it defines storage and concurrency mechanics, not business meaning.

No engine is added. MIKE continues to have exactly 17 engines.

## Conceptual port

The replaceable conceptual port is equivalent to:

```python
class EpisodeJournal(Protocol):
    def create_episode_with_event(...): ...
    def append_event(..., expected_event_ids: tuple[str, ...]): ...
    def get_event(...): ...
    def get_episode(...): ...
    def list_events(...): ...
    def list_episodes(...): ...
```

Concrete signatures may adapt to the existing value objects and conventions without changing the approved semantics.

The port shall not depend on FastAPI or concrete handlers.

`EpisodeCoordinator` shall depend on the port, not on `InMemoryEventStore` or `InMemoryEpisodeStore` through `isinstance` checks or other concrete coupling.

Handlers shall continue to depend on the coordinator and shall not know the concrete journal implementation.

## Atomic creation

Initial episode creation and storage of its first event form one logical operation.

On success:

- the initial event is stored;
- the episode is stored; and
- the episode references exactly that event.

On failure:

- the event is not stored;
- the episode is not stored; and
- the exception is propagated.

No state containing only one of the two elements may become visible.

## Atomic append with expected version

`append_event` shall receive the expected episode version, represented by the exact current tuple of `event_ids`.

The operation shall:

1. resolve the episode within the requested tenant;
2. verify that the episode belongs to that tenant;
3. verify that the event belongs to the same tenant;
4. verify that the current `event_ids` exactly match `expected_event_ids`;
5. reject an `event_id` duplicated globally within the journal instance;
6. reject an `event_id` already present in the episode;
7. construct the updated immutable episode; and
8. publish the event and updated episode together.

If `expected_event_ids` does not match, the operation shall produce an explicit concurrency conflict. The concrete exception name may follow repository conventions, but the conflict shall not be hidden as success or resolved by overwrite.

For any failure:

- the new event is not stored;
- the episode is not modified;
- no partial write occurs; and
- the exception is propagated.

There is no later rollback because no mutation is published before all validations complete.

## Approved initial implementation

Phase 21 initially implements:

```text
InMemoryEpisodeJournal
```

It shall protect compound operations with an internal lock shared by the journal instance.

The implementation shall preserve:

- immutable `Event` objects;
- immutable `CognitiveEpisode` objects;
- ordering through `event_ids`;
- tenant isolation;
- tenant-safe reads;
- rejection of duplicate IDs; and
- logical atomicity within one instance.

The lock shall cover version verification and joint publication, preventing two appends with the same expected version from both succeeding.

For two concurrent appends against the same expected version:

- exactly one may succeed;
- the other receives the explicit conflict; and
- no partial write may occur.

## Approved actual guarantees

Phase 21 may declare only:

- logical atomicity within one process instance;
- concurrency control within that instance;
- optimistic versioning through `expected_event_ids`;
- tenant isolation;
- order;
- uniqueness of `event_id`;
- absence of partial writes between event and episode; and
- a replaceable boundary for a future implementation.

Phase 21 may not declare:

- durability;
- persistence on disk;
- recovery after restart;
- coordination between processes;
- coordination between multiple workers;
- database transactions;
- at-least-once delivery;
- exactly-once delivery;
- retries;
- an outbox;
- an inbox;
- dead letters; or
- external idempotency.

During Phase 21, "stored" continues to mean stored in memory within the current process instance.

## Internal migration

`EpisodeCoordinator` shall use `EpisodeJournal` to:

- create an episode with its initial event;
- append subsequent events;
- resolve events and episodes; and
- list events and episodes where applicable.

It shall no longer coordinate two independent writes to the event store and episode store.

The previous stores may either:

- be integrated internally behind the journal; or
- be replaced by a joint implementation.

This mechanical choice does not change the architecture provided that:

- one atomic boundary exists;
- state cannot diverge;
- the approved guarantees are maintained; and
- the coordinator no longer has concrete coupling to the two stores.

## Pipeline and compatibility

Phase 21 adds no events.

The pipeline retains exactly ten events and ends with:

```text
conversation.response_ready
```

Phase 21 changes none of the following:

- any `event_type`;
- any payload;
- pipeline order;
- `POST /dev/messages`;
- its HTTP request;
- its HTTP response;
- the meaning of the 17 engines; or
- ADR-0001 through ADR-0004.

No dependencies are added.

Existing tests shall continue to work, except for mechanical adaptations required to construct the new journal or coordinator.

## Failure semantics

For any creation, append, tenant, duplication, or conflict error:

- propagate the exception;
- leave the observable journal state unchanged from before the operation;
- do not create a rejection event;
- do not retry;
- do not use a fallback;
- do not overwrite; and
- do not silently correct `expected_event_ids`.

Future retry policy belongs to another phase.

## Out of scope

- PostgreSQL.
- SQLAlchemy.
- Alembic.
- SQLite.
- Filesystem persistence.
- Migrations.
- Durable persistence.
- An outbox.
- An inbox.
- `delivery_requested`.
- Adapters.
- Sending.
- Retries.
- Backoff.
- Dead-letter handling.
- Distributed locks.
- Leases.
- Multi-process coordination.
- Multiple workers.
- Provider idempotency.
- Changes to the cognitive pipeline.
- Updating the test count in `README.md`.

## Consequences

### Positive

- Eliminates possible divergence between the event store and episode store.
- Decouples `EpisodeCoordinator` from concrete in-memory implementations.
- Establishes a replaceable boundary for PostgreSQL.
- Introduces optimistic concurrency control.
- Allows concurrent append to be tested correctly.
- Keeps handlers and business meaning separate from persistence.
- Avoids building delivery on a partial-write foundation.

### Costs

- Refactors stores, coordinator, `main.py`, and fixtures.
- Introduces an additional port.
- Requires a lock and concurrency tests.
- Retains conceptual duplication between `Event` and `CognitiveEpisode`.
- Still provides no durability.
- A future PostgreSQL implementation must honor the same contract through real transactions.

## Future phases not yet approved

The following items are directions, not approved implementation decisions:

- a later phase may implement the port with PostgreSQL and real transactions;
- `delivery_requested` and a durable outbox shall wait until that foundation exists; and
- PostgreSQL technology, schemas, migrations, and operation require a separate human decision.

No Phase 22 or later phase is approved by this ADR.
