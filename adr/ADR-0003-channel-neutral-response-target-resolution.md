# ADR-0003 — Channel-Neutral Response Target Resolution

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Phase 18 ends with `conversation.response_validated`, which is currently the eighth and terminal event.

MIKE can produce and validate response content, but the current pipeline does not contain:

- `channel`;
- `external_message_id`;
- `external_conversation_id`;
- `sender_id`;
- `recipient_id`; or
- a delivery target.

A response must not be declared ready for delivery while it lacks an explicit, tenant-safe target.

A real delivery target or target for a real channel adapter must not be inferred from:

- the text;
- `tenant_id`;
- `episode_id`;
- `delivery_address`;
- commercial entities; or
- any implicit data.

## Decision

Phase 19 introduces a channel-neutral communication-context foundation and resolves the response target.

This responsibility belongs to the Communication engine. It does not belong to the Verification engine. It does not yet belong to Execution & Skills because it executes no delivery and invokes no external capability.

The approved flow is:

```text
conversation.response_validated
→ ConversationResponseTargetResolver
→ ConversationResponseTargetResolvedHandler
→ communication.response_target_resolved
```

`communication.response_target_resolved` is the ninth event of the same `CognitiveEpisode` and is terminal in Phase 19.

Phase 19 does not create `conversation.response_ready`.

## Approved `CommunicationContext`

The approved immutable conceptual model is:

```python
@dataclass(frozen=True, slots=True)
class CommunicationContext:
    channel: str
    external_message_id: str
    external_conversation_id: str
    sender_id: str
    recipient_id: str
```

Its fields have the following semantics:

- `channel` is the technical source channel.
- `external_message_id` is the opaque message identifier assigned or represented by the ingress adapter.
- `external_conversation_id` is the opaque identifier of the external conversation or thread.
- `sender_id` is the external identity that sent the inbound message.
- `recipient_id` is the business or technical identity that received the inbound message.

These identifiers are opaque to MIKE. They are not equivalent to `tenant_id` or `episode_id`. A `CognitiveEpisode` remains an internal cognitive unit, not an external conversation.

The communication context originates exclusively at the ingress boundary and is preserved traceably from `message.received`.

## Approved internal development context

`POST /dev/messages` retains exactly its current HTTP request and response contracts. It continues to accept only:

- `tenant_id`; and
- `text`.

The local development adapter internally creates:

```text
channel = "development"
external_message_id = a newly generated identifier
external_conversation_id = a newly generated identifier
sender_id = "development-user"
recipient_id = tenant_id
```

These values are synthetic, exclusive to the development environment, and do not represent a real integration or delivery. The reuse of `tenant_id` as the synthetic `recipient_id` value is exclusively a `POST /dev/messages` convention: it does not make `recipient_id` and `tenant_id` the same concept, resolve a real delivery target, or establish a rule for future channels. These values do not establish the future identifier formats for WhatsApp, Instagram, webchat, or any other channel.

No HTTP parameters are added to the endpoint.

## Approved resolution

The outbound target is obtained only by reversing the direction of the inbound context:

- outbound `channel` equals inbound `channel`;
- outbound recipient equals inbound `sender_id`;
- outbound sender equals inbound `recipient_id`; and
- the external conversation remains the same `external_conversation_id`.

The resolver is:

- pure;
- deterministic;
- tenant-safe;
- independent of FastAPI;
- independent of the runtime;
- independent of stores;
- free of environment variables;
- free of network access; and
- free of external adapters.

The approved initial value is:

```python
resolution_method = "reply_to_source"
```

The resolver does not transform, copy, correct, translate, sanitize, or regenerate the validated text.

## Approved event

The approved event name is:

```text
communication.response_target_resolved
```

Its approved conceptual payload contains:

- `source_event_id`
- `response_validated_event_id`
- `channel`
- `external_message_id`
- `external_conversation_id`
- `outbound_sender_id`
- `outbound_recipient_id`
- `resolution_method`

The event does not copy:

- `text`;
- `language`;
- `response_type`;
- `generation_method`;
- `validation_method`; or
- the complete chain of intermediate references.

Those values remain authoritative in `conversation.response_validated` and are recoverable through references within the episode.

`external_message_id` identifies the inbound message that originated the response. It does not assert that an external outbound message exists yet.

## Success semantics

- Exactly the eight preceding events exist in the approved order.
- All events belong to the same tenant and `CognitiveEpisode`.
- The complete reference chain is valid.
- `communication.response_target_resolved` is appended as the ninth event.
- The event is stored.
- The event is not dispatched in Phase 19.
- No external call is made.

## Failure semantics

For any inconsistency:

- propagate the exception;
- preserve the eight existing events unchanged;
- do not create or store `communication.response_target_resolved`;
- do not create a rejection event;
- do not retry;
- do not roll back existing events;
- do not use a fallback; and
- do not infer or substitute targets.

## Compatibility

- `POST /dev/messages` retains its HTTP contract.
- No real channel is connected.
- The meaning of Verification is unchanged.
- No engines are added.
- MIKE continues to have exactly 17 engines.
- No dependencies are added.
- Events and models remain immutable.
- Tenant isolation is mandatory.

## Out of scope

- `conversation.response_ready`.
- Delivery requests.
- An outbox.
- A delivery idempotency key.
- Channel adapters.
- Meta Cloud API.
- WhatsApp.
- Instagram.
- Real webchat.
- Delivery.
- Acknowledgement.
- Send confirmation.
- Delivery confirmation.
- Retries.
- Delivery status.
- Commercial authorization.
- Content transformation.
- Verification of organizational outcomes.

## Consequences

### Positive

- Establishes explicit communication context.
- Prevents recipient inference.
- Separates the internal episode from the external conversation.
- Enables future multichannel integrations to be prepared.
- Keeps the development endpoint stable.
- Preserves separation among target resolution, readiness, delivery requests, and delivery.

### Costs

- Expands the ingress payload.
- Introduces synthetic identifiers in development.
- Adds a ninth event.
- Does not yet enable any delivery.
- Idempotency and durable persistence remain pending.
