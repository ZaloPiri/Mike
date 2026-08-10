# ADR-0002 — Outbound Conversation Response Validation

- **Status:** Accepted
- **Date:** 2026-08-10

## Context

Phase 17 ends with `conversation.response_generated`. Before a response can be declared ready for a channel, it requires an independent and auditable technical gate.

This validation belongs to the Communication engine. It does not belong to the Verification engine. Verification evaluates observed organizational outcomes after execution, whereas outbound response validation checks the technical integrity and admissibility of a response before it is sent.

## Decision

The approved flow is:

```text
conversation.response_generated
→ ConversationResponseValidator
→ ConversationResponseValidatedHandler
→ conversation.response_validated
```

### Responsibility

The validator shall:

- validate the `conversation.response_generated` event;
- validate membership in the same tenant and `CognitiveEpisode`;
- validate the complete reference chain;
- validate the types of referenced events;
- validate ID correspondence between events;
- validate that `response_type` matches `conversation.response_request`;
- validate that `language` matches `target_language`;
- accept exactly the `es` language;
- require `text` to be a non-empty string;
- require `generation_method` to equal `deterministic_template`;
- reject NUL and invalid control characters;
- preserve the text exactly; and
- not trim, translate, correct, sanitize, or regenerate the text.

### Approved model

```python
@dataclass(frozen=True, slots=True)
class ValidatedConversationResponse:
    response_type: str
    language: str
    text: str
    generation_method: str
    validation_method: str
```

The approved initial value is:

```python
validation_method = "deterministic_contract"
```

### Approved `conversation.response_validated` payload

The payload contains:

- `source_event_id`
- `accepted_event_id`
- `perceived_event_id`
- `normalized_event_id`
- `next_action_event_id`
- `response_request_event_id`
- `response_generated_event_id`
- `response_type`
- `language`
- `text`
- `generation_method`
- `validation_method`

The payload does not contain:

- `is_valid`
- `validation_status`
- `violations`

### Success semantics

- `conversation.response_validated` exists only when validation succeeds.
- It is appended as the eighth event of the same episode.
- In Phase 18, it is terminal and is not dispatched.

### Failure semantics

- Propagate the exception.
- Preserve the seven existing events.
- Do not create `conversation.response_validated`.
- Do not create a rejection event.
- Do not retry.
- Do not roll back.
- Do not fall back.
- Do not regenerate.

## Out of scope

- Commercial truthfulness.
- Stock, prices, or products.
- Moderation.
- Business policies.
- Human authorization.
- Channel-specific limits.
- An arbitrary maximum length.
- Tenant-specific tone.
- Verification of action outcomes.
- Delivery through channels.
- `conversation.response_ready`.

## Compatibility

- `POST /dev/messages` retains its current contract.
- The HTTP response is unchanged.
- No channel is connected.
- The meaning of the Verification engine is unchanged.
- No engines are added.
- MIKE continues to have exactly 17 engines.

## Consequences

### Positive

- An explicit pre-delivery gate.
- Traceability of the control.
- Separation of generation, validation, and delivery.
- Avoidance of confusion with organizational verification.
- Future channels can consume an admitted response.

### Costs

- One additional event and handler.
- Deliberate repetition of some invariants to provide an independent gate.
- Policies, moderation, and per-channel rules remain uncovered.

## Implementation constraints

- The validator is a deterministic, pure service.
- The validator contains no FastAPI, runtime, stores, environment variables, or network access.
- A separate handler integrates the validator with the runtime.
- Append occurs before any dispatch.
- Validation is tenant-safe.
- Events and models are immutable.
- Tests make no real external calls.
- No new dependencies are introduced.
