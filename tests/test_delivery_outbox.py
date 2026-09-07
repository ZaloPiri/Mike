from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry


def make_entry(**changes: object) -> DeliveryOutboxEntry:
    values = {
        "outbox_id": uuid.uuid4(),
        "tenant_id": "tenant-1",
        "episode_id": uuid.uuid4(),
        "delivery_request_event_id": uuid.uuid4(),
        "response_ready_event_id": uuid.uuid4(),
        "idempotency_key": "idempotency",
        "channel": "development",
        "external_conversation_id": "conversation",
        "outbound_sender_id": "sender",
        "outbound_recipient_id": "recipient",
        "response_type": "answer",
        "language": "es",
        "text": "text",
        "status": "pending",
        "created_at": datetime.now(timezone(timedelta(hours=-3))),
        "schema_version": 1,
    }
    values.update(changes)
    return DeliveryOutboxEntry(**values)


def test_entry_is_immutable_and_normalizes_created_at_to_utc() -> None:
    entry = make_entry()
    assert entry.created_at.utcoffset() == timedelta(0)
    with pytest.raises(FrozenInstanceError):
        entry.status = "changed"


@pytest.mark.parametrize(
    "field_name",
    [
        "outbox_id", "episode_id", "delivery_request_event_id",
        "response_ready_event_id",
    ],
)
def test_entry_rejects_invalid_uuid(field_name: str) -> None:
    with pytest.raises(TypeError, match=field_name):
        make_entry(**{field_name: "not-a-uuid"})


@pytest.mark.parametrize("field_name", ["tenant_id", "channel", "text"])
def test_entry_rejects_empty_required_string(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_entry(**{field_name: " "})


def test_entry_rejects_non_pending_status() -> None:
    with pytest.raises(ValueError, match="pending"):
        make_entry(status="processing")


@pytest.mark.parametrize("schema_version", [0, -1, True, "1"])
def test_entry_rejects_invalid_schema_version(schema_version: object) -> None:
    with pytest.raises(ValueError, match="schema_version"):
        make_entry(schema_version=schema_version)


def test_entry_rejects_naive_created_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_entry(created_at=datetime.now())
