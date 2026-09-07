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
        if self.status != "pending":
            raise ValueError("status must be pending")
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(
            self, "created_at", self.created_at.astimezone(timezone.utc)
        )
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version <= 0
        ):
            raise ValueError("schema_version must be a positive integer")
