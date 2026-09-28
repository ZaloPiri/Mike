from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class DeliveryOutboxEntry:
    outbox_id: uuid.UUID
    tenant_id: str
    episode_id: uuid.UUID
    delivery_request_event_id: uuid.UUID
    response_ready_event_id: uuid.UUID
    idempotency_key: str
    channel: str
    external_conversation_id: str
    outbound_sender_id: str
    outbound_recipient_id: str
    response_type: str
    language: str
    text: str
    status: str
    created_at: datetime
    schema_version: int
    adapter_attempt_count: int = 0
    next_attempt_at: datetime | None = None
    claim_token: uuid.UUID | None = None
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    delivery_accepted_event_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "outbox_id",
            "episode_id",
            "delivery_request_event_id",
            "response_ready_event_id",
        ):
            if not isinstance(getattr(self, field_name), uuid.UUID):
                raise TypeError(f"{field_name} must be a uuid.UUID")
        for field_name in (
            "tenant_id",
            "idempotency_key",
            "channel",
            "external_conversation_id",
            "outbound_sender_id",
            "outbound_recipient_id",
            "response_type",
            "language",
            "text",
            "status",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            if not value or value.strip() == "":
                raise ValueError(f"{field_name} must be non-empty")
        if self.status not in {"pending", "processing", "completed", "failed"}:
            raise ValueError("status must be pending, processing, completed, or failed")
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(
            self, "created_at", self.created_at.astimezone(timezone.utc)
        )
        if (
            not isinstance(self.adapter_attempt_count, int)
            or isinstance(self.adapter_attempt_count, bool)
            or not 0 <= self.adapter_attempt_count <= 3
        ):
            raise ValueError("adapter_attempt_count must be an integer from 0 to 3")
        for field_name in ("next_attempt_at", "claimed_at", "lease_expires_at"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, datetime):
                    raise TypeError(f"{field_name} must be a datetime or None")
                if value.tzinfo is None:
                    raise ValueError(f"{field_name} must be timezone-aware")
                object.__setattr__(self, field_name, value.astimezone(timezone.utc))
        if self.claim_token is not None and not isinstance(self.claim_token, uuid.UUID):
            raise TypeError("claim_token must be a uuid.UUID or None")
        if self.last_error is not None:
            if not isinstance(self.last_error, str):
                raise TypeError("last_error must be a string or None")
            if len(self.last_error) > 512:
                raise ValueError("last_error must be at most 512 characters")
        if self.delivery_accepted_event_id is not None and not isinstance(
            self.delivery_accepted_event_id, uuid.UUID
        ):
            raise TypeError("delivery_accepted_event_id must be a uuid.UUID or None")
        if self.status == "completed" and self.delivery_accepted_event_id is None:
            raise ValueError("completed requires delivery_accepted_event_id")
        if self.status != "completed" and self.delivery_accepted_event_id is not None:
            raise ValueError("non-completed status cannot have delivery_accepted_event_id")
        if self.status != "processing" and any(
            value is not None for value in (self.claim_token, self.claimed_at, self.lease_expires_at)
        ):
            raise ValueError("claim fields require processing status")
        if self.status == "processing" and any(
            value is None for value in (self.claim_token, self.claimed_at, self.lease_expires_at)
        ):
            raise ValueError("processing requires complete claim fields")
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version <= 0
        ):
            raise ValueError("schema_version must be a positive integer")
