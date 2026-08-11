# ADR-0004 — Conversation Response Readiness

- **Status:** Accepted
- **Date:** 2026-08-11

## Context

Phase 18 created a technically validated response:

```text
conversation.response_validated
```

Phase 19 resolved an explicit, tenant-safe target:

```text
communication.response_target_resolved
```

MIKE now has:

- validated content;
- a resolved target; and
- traceability to the original message.

There is not yet a self-contained contract declaring that both results are present, consistent, and consumable by a future delivery-request phase.

"Ready" does not mean:

- sent;
- requested for sending;
- accepted by a channel;
- delivered;
- commercially authorized; or
- verified as an organizational outcome.

## Decision

Phase 20 introduces an explicit, self-contained readiness contract.

This responsibility belongs to the Communication engine. It does not belong to the Verification engine. It executes no external capabilities and performs no delivery.

The approved flow is:

```text
communication.response_target_resolved
→ ConversationResponseReadinessEvaluator
→ ConversationResponseReadyHandler
→ conversation.response_ready
```

`conversation.response_ready` is the tenth event of the same `CognitiveEpisode` and is terminal in Phase 20.

## Responsibility

The evaluator shall verify the existence and consistency of:

- the validated response;
- the resolved target;
- the original message;
- the tenant;
- the `CognitiveEpisode`;
- the complete reference chain; and
- the nine preceding events in the approved order.

It shall combine without transformation:

- the exact content of `conversation.response_validated`; and
- the exact target of `communication.response_target_resolved`.

It shall not decide again:

- what text to return;
- whether the content is commercially truthful;
- whether the content complies with business policies;
- which recipient to use;
- which channel to use;
- whether the response should be sent; or
- whether authorization to send exists.

## Approved conceptual model

The approved immutable conceptual model is:

```python
@dataclass(frozen=True, slots=True)
class ReadyConversationResponse:
    response_type: str
    language: str
    text: str
    channel: str
    external_message_id: str
    external_conversation_id: str
    outbound_sender_id: str
    outbound_recipient_id: str
    readiness_method: str
```

The approved initial value is:

```python
readiness_method = "validated_response_with_resolved_target"
```

The model represents a self-contained technical snapshot.

## Copy and authority rule

`conversation.response_ready` copies exactly the following fields from `conversation.response_validated`:

- `response_type`;
- `language`; and
- `text`.

It copies exactly the following fields from `communication.response_target_resolved`:

- `channel`;
- `external_message_id`;
- `external_conversation_id`;
- `outbound_sender_id`; and
- `outbound_recipient_id`.

The following are not permitted:

- trimming;
- translation;
- correction;
- sanitization;
- regeneration;
- format changes;
- replacement;
- inference; or
- transformation of the text or target.

The original authoritative sources remain the referenced events. The self-contained snapshot exists so that a future durable delivery boundary can consume a single contract without reconstructing the complete chain.

Phase 20 does not make this contract durable. Durable persistence remains out of scope.

## Approved event

The approved event name is:

```text
conversation.response_ready
```

Its exact conceptual payload contains:

- `source_event_id`
- `response_validated_event_id`
- `response_target_resolved_event_id`
- `response_type`
- `language`
- `text`
- `channel`
- `external_message_id`
- `external_conversation_id`
- `outbound_sender_id`
- `outbound_recipient_id`
- `readiness_method`

The payload does not contain:

- `is_ready`
- `readiness_status`
- `violations`
- `delivery_request_id`
- `idempotency_key`
- `delivery_status`
- `sent_at`
- `delivered_at`
- `provider_message_id`
- `accepted_event_id`
- `perceived_event_id`
- `normalized_event_id`
- `next_action_event_id`
- `response_request_event_id`
- `response_generated_event_id`
- `generation_method`
- `validation_method`
- `resolution_method`
- `tenant_id` within the payload
- `episode_id` within the payload

The tenant and episode remain represented by the event envelope and the `CognitiveEpisode`.

## Success semantics

Exactly the nine preceding events shall exist in the approved order:

1. `message.received`
2. `message.accepted`
3. `message.perceived`
4. `perception.normalized`
5. `conversation.next_action`
6. `conversation.response_request`
7. `conversation.response_generated`
8. `conversation.response_validated`
9. `communication.response_target_resolved`

All events belong to the same tenant and `CognitiveEpisode`. The complete reference chain is valid. The validated content and resolved target are consistent with their source events.

On success:

- `conversation.response_ready` is appended as the tenth event;
- the event is stored;
- the event is not dispatched in Phase 20; and
- no external call is made.

## Failure semantics

For any inconsistency:

- propagate the exception;
- preserve the nine existing events unchanged;
- do not create or store `conversation.response_ready`;
- do not create a rejection event;
- do not retry;
- do not roll back existing events;
- do not use a fallback; and
- do not correct or substitute content or targets.

## Compatibility

- `POST /dev/messages` retains exactly its HTTP request and response contracts.
- No channel is connected.
- The meaning of Verification is unchanged.
- No engines are added.
- MIKE continues to have exactly 17 engines.
- No dependencies are added.
- Events and models remain immutable.
- Tenant isolation remains mandatory.

## Out of scope

- Delivery requests.
- An outbox.
- Durable persistence.
- An idempotency key.
- Adapters.
- Meta Cloud API.
- WhatsApp.
- Instagram.
- Real webchat.
- Sending.
- Acknowledgement.
- Send confirmation.
- Delivery confirmation.
- `provider_message_id`.
- Retries.
- Delivery status.
- Commercial authorization.
- Content transformation.
- Verification of organizational outcomes.

## Consequences

### Positive

- A self-contained contract for future delivery phases.
- Explicit separation among validated, target resolved, ready, delivery requested, sent, and delivered.
- Exact preservation of content and target.
- Traceability to the authoritative events.
- A simpler future delivery boundary.
- No provider coupling.

### Costs

- Adds a tenth event.
- Deliberately duplicates content and target as a snapshot.
- Still does not permit sending.
- Still provides neither durability nor idempotency.
- Requires the chain invariants to be checked again.
