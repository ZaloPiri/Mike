# ADR-0007 — Atomic Delivery Request Outbox

- **Status:** Accepted
- **Date:** 2026-08-15

## Context

Phase 22 provides durable PostgreSQL persistence, transactions, migrations, tenant isolation, and concurrency across processes.

The pipeline currently ends with exactly ten events and `conversation.response_ready`.

A ready response contains validated content and a resolved target, but no durable delivery request exists yet.

“Ready” does not mean requested for delivery, sent, accepted by a provider, or delivered.

MIKE needs to create atomically:

- an auditable request event;
- the episode update; and
- a durable, self-contained outbox entry.

## Decision

The approved flow is:

```text
conversation.response_ready
→ ConversationDeliveryRequestPlanner
→ ConversationDeliveryRequestedHandler
→ communication.delivery_requested
```

`communication.delivery_requested` is event 11 of the same `CognitiveEpisode`.

It is terminal and is not dispatched during Phase 23.

Phase 23 belongs:

- to Communication for the meaning of the delivery request; and
- to Orchestration & Event Runtime for atomicity, persistence, and the outbox.

Phase 23 adds no engine. MIKE retains exactly 17 engines.

## Approved conceptual model

The approved conceptual model is:

```python
@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    channel: str
    external_conversation_id: str
    outbound_sender_id: str
    outbound_recipient_id: str
    response_type: str
    language: str
    text: str
    idempotency_key: str
    request_method: str
```

The initial fixed value is:

```text
request_method = "transactional_outbox"
```

All fields are non-empty strings.

The planner is pure and deterministic, with no FastAPI, runtime, stores, environment, network, or adapters.

The planner copies exactly these values from `conversation.response_ready`:

- `channel`;
- `external_conversation_id`;
- `outbound_sender_id`;
- `outbound_recipient_id`;
- `response_type`;
- `language`; and
- `text`.

It does not trim, translate, correct, sanitize, regenerate, replace, or transform content or target.

## Approved idempotency rule

The approved rule is:

```text
idempotency_key = str(response_ready_event_id)
```

`response_ready_event_id` is globally unique.

One ready response can originate only one delivery request.

A repeated request:

- produces an explicit conflict;
- is not treated as silent success;
- creates no additional event;
- creates no additional outbox row;
- does not overwrite;
- does not retry; and
- does not use a fallback.

Idempotency against an external provider is not yet approved.

## Approved event

The exact event name is:

```text
communication.delivery_requested
```

Its exact payload contains:

- `source_event_id`;
- `response_ready_event_id`;
- `channel`;
- `external_conversation_id`;
- `outbound_sender_id`;
- `outbound_recipient_id`;
- `idempotency_key`; and
- `request_method`.

The payload does not contain:

- `text`;
- `language`;
- `response_type`;
- `delivery_status`;
- `status`;
- `attempt_count`;
- `provider_message_id`;
- `sent_at`;
- `delivered_at`;
- `last_error`;
- `outbox_id`;
- `tenant_id` inside the payload; or
- `episode_id` inside the payload.

The `Event` envelope and `CognitiveEpisode` retain the tenant and episode.

Following the repository's existing traceability convention, `source_event_id` refers to the original `message.received` event. `response_ready_event_id` refers to the immediately preceding `conversation.response_ready` event. Phase 23 approves no exception to the existing semantics of `source_event_id`.

## Approved outbox snapshot

The conceptual table is:

```text
delivery_outbox
```

Its approved columns are:

- `outbox_id UUID PRIMARY KEY`;
- `tenant_id TEXT NOT NULL`;
- `episode_id UUID NOT NULL`;
- `delivery_request_event_id UUID NOT NULL UNIQUE`;
- `response_ready_event_id UUID NOT NULL UNIQUE`;
- `idempotency_key TEXT NOT NULL UNIQUE`;
- `channel TEXT NOT NULL`;
- `external_conversation_id TEXT NOT NULL`;
- `outbound_sender_id TEXT NOT NULL`;
- `outbound_recipient_id TEXT NOT NULL`;
- `response_type TEXT NOT NULL`;
- `language TEXT NOT NULL`;
- `text TEXT NOT NULL`;
- `status TEXT NOT NULL`;
- `created_at TIMESTAMPTZ NOT NULL`; and
- `schema_version INTEGER NOT NULL`.

The only status permitted in Phase 23 is:

```text
pending
```

The outbox snapshot is self-contained so that a future worker does not need to reconstruct the complete episode.

The original authority over content and target remains `conversation.response_ready`. The outbox retains an exact copy intended for the future delivery boundary.

Phase 23 does not permit:

- `attempt_count`;
- `available_at`;
- `claimed_at`;
- `completed_at`;
- `last_error`;
- `provider_message_id`;
- `lock_owner`;
- `lease_until`; or
- `updated_at`.

## Approved constraints

The conceptual constraints are:

- global uniqueness of `outbox_id`;
- global uniqueness of `delivery_request_event_id`;
- global uniqueness of `response_ready_event_id`;
- global uniqueness of `idempotency_key`;
- a tenant-safe relationship with `episodes` through `episode_id` and `tenant_id`;
- `delivery_request_event_id` relates to the corresponding event 11;
- `response_ready_event_id` identifies event 10;
- required strings are non-empty;
- `status` is exactly `pending`;
- `schema_version` is positive; and
- timestamps are timezone-aware and normalized to UTC.

Physical constraint names are not part of this decision.

## Atomic transaction

For PostgreSQL, one transaction must:

1. Resolve the episode using tenant-safe criteria.
2. Lock the episode row with `SELECT FOR UPDATE` or an equivalent mechanism.
3. Check exactly the ten current `event_ids` and their order.
4. Compare them exactly with `expected_event_ids`.
5. Validate tenant, episode, event types, and the complete chain.
6. Validate that `conversation.response_ready` is event 10.
7. Build `communication.delivery_requested`.
8. Append event 11.
9. Create the pending `delivery_outbox` row.
10. Commit once.

Only the following state is valid as a whole:

- event 11 is stored;
- the episode is updated to eleven events; and
- the pending outbox row is stored.

The following states are invalid:

- event 11 without an outbox row;
- an outbox row without event 11;
- a partially updated episode;
- a duplicate row; or
- two requests for the same `response_ready_event_id`.

No mutation is published before every validation completes.

## EpisodeJournal boundary

The approved decision extends `EpisodeJournal` with a conceptual operation equivalent to:

```python
append_event_with_outbox(
    event,
    expected_event_ids,
    outbox_entry,
)
```

and tenant-safe reads equivalent to:

```python
get_outbox_entry(...)
list_outbox_entries(...)
```

Concrete signatures may adapt to existing value objects and conventions without changing the approved semantics.

This extension is a generic atomic persistence operation. Handlers do not know about SQLAlchemy, tables, sessions, connections, or locks.

Two independent stores that coordinate writes externally are not created.

`EpisodeCoordinator` may be adapted mechanically to expose the operation without acquiring delivery meaning.

## In-memory implementation

`InMemoryEpisodeJournal` must:

- retain the event, episode, and outbox under the same lock;
- publish all three parts together;
- provide tenant-safe reads;
- reject duplicates;
- preserve immutability; and
- guarantee atomicity only within one instance and process.

It does not provide durability, recovery, or multiprocess coordination.

## PostgreSQL implementation

`PostgreSQLEpisodeJournal` must:

- use the same engine and transaction;
- lock the episode;
- insert the event and outbox and logically update the episode within the same commit;
- translate infrastructure exceptions;
- not expose SQLAlchemy or psycopg;
- not use `create_all`;
- not run migrations automatically;
- not use fallback; and
- not retry.

## Migration

A second Alembic migration must create only `delivery_outbox` and its approved relationships.

Upgrade and downgrade must be versioned and auditable.

Downgrade removes only the table added by Phase 23.

The application does not run migrations automatically.

## Success semantics

On success:

- exactly the ten previously approved events exist;
- all belong to the same tenant and episode;
- the complete chain is valid;
- exactly one event 11 is created;
- exactly one pending outbox row is created;
- both contain values consistent with `conversation.response_ready`;
- event 11 is stored;
- event 11 is not dispatched; and
- no external call is made.

## Failure semantics

On any inconsistency or error:

- the exception propagates;
- exactly the ten previous events remain;
- the episode does not change;
- event 11 does not exist;
- no new outbox row exists;
- no rejection event is created;
- there is no retry;
- there is no fallback;
- there is no overwrite;
- there is no silent correction; and
- there is no send.

## Compatibility

Phase 23 preserves:

- the HTTP contracts of `POST /dev/messages`;
- the `/health` contract;
- development inspection contracts;
- the first ten `event_type` values and payloads;
- `conversation.response_ready` without modification;
- exactly 17 engines;
- explicit `memory|postgres` selection;
- the absence of real channels;
- the absence of external calls; and
- the absence of new dependencies.

The pipeline grows to exactly eleven events and ends with `communication.delivery_requested`.

## Out of scope

The following remain outside Phase 23:

- workers;
- polling;
- claiming;
- `SELECT FOR UPDATE SKIP LOCKED` for workers;
- processing locks;
- leases;
- outbox processing;
- later status changes;
- sending;
- WhatsApp;
- Instagram;
- real webchat;
- Meta Cloud API;
- adapters;
- retries;
- backoff;
- dead letters;
- provider idempotency;
- `communication.sent`;
- `communication.delivery_failed`;
- acknowledgements;
- delivery confirmation;
- read confirmation;
- `provider_message_id`;
- outbox deletion or archival;
- dashboards;
- advanced observability;
- new engines; and
- Phase 24 or later phases.

## Consequences

### Positive

- The delivery request is durable.
- Requests are not lost after commit.
- The event, episode, and outbox cannot diverge.
- A self-contained snapshot is available to a future worker.
- Internal idempotency is explicit.
- The design remains provider-neutral.
- The separation between readiness, request, send, and delivery is preserved.

### Costs

- `EpisodeJournal` is extended.
- A table and migration are added.
- Content and target are duplicated in the outbox.
- Event 11 is added.
- Contract and PostgreSQL testing increases.
- Messages are still not sent.
- Future phases must define claiming, retries, and statuses.

## Future phases not approved

ADR-0007 does not approve:

- a worker;
- outbox processing;
- an adapter;
- delivery;
- Phase 24; or
- any later phase.
