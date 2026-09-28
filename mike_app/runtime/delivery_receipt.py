from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry


def snapshot_hash(entry: DeliveryOutboxEntry) -> str:
    snapshot = {
        "tenant_id": entry.tenant_id,
        "episode_id": str(entry.episode_id),
        "delivery_request_event_id": str(entry.delivery_request_event_id),
        "idempotency_key": entry.idempotency_key,
        "channel": entry.channel,
        "external_conversation_id": entry.external_conversation_id,
        "outbound_sender_id": entry.outbound_sender_id,
        "outbound_recipient_id": entry.outbound_recipient_id,
        "response_type": entry.response_type,
        "language": entry.language,
        "text": entry.text,
        "schema_version": entry.schema_version,
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    receipt_id: uuid.UUID
    tenant_id: str
    outbox_id: uuid.UUID
    delivery_request_event_id: uuid.UUID
    idempotency_key: str
    snapshot_hash: str
    adapter: str
    accepted_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in ("receipt_id", "outbox_id", "delivery_request_event_id"):
            if not isinstance(getattr(self, name), uuid.UUID):
                raise TypeError(f"{name} must be a uuid.UUID")
        for name in ("tenant_id", "idempotency_key", "snapshot_hash", "adapter"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.accepted_at, datetime) or self.accepted_at.tzinfo is None:
            raise ValueError("accepted_at must be timezone-aware")
        object.__setattr__(self, "accepted_at", self.accepted_at.astimezone(timezone.utc))
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version <= 0:
            raise ValueError("schema_version must be a positive integer")

    def is_compatible(self, entry: DeliveryOutboxEntry) -> bool:
        return (
            self.tenant_id == entry.tenant_id
            and self.outbox_id == entry.outbox_id
            and self.delivery_request_event_id == entry.delivery_request_event_id
            and self.idempotency_key == entry.idempotency_key
            and self.snapshot_hash == snapshot_hash(entry)
        )


class ReceiptConflictError(ValueError):
    pass
