from __future__ import annotations

import uuid
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any


def _freeze_json_compatible(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("payload must contain only finite numbers")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        frozen_dict = {
            key: _freeze_json_compatible(item) for key, item in value.items()
        }
        for key in frozen_dict:
            if not isinstance(key, str):
                raise ValueError("payload must be JSON-compatible")
        return MappingProxyType(frozen_dict)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json_compatible(item) for item in value)
    raise ValueError("payload must be JSON-compatible")


def _unfreeze_json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {key: _unfreeze_json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_unfreeze_json_compatible(item) for item in value]
    raise ValueError("payload must be JSON-compatible")


@dataclass(frozen=True)
class Event:
    event_id: uuid.UUID
    tenant_id: str
    event_type: str
    occurred_at: datetime
    payload: Any
    correlation_id: str | None = None
    causation_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, uuid.UUID):
            raise ValueError("event_id must be a uuid.UUID")
        if not self.tenant_id or self.tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")
        if not self.event_type or self.event_type.strip() == "":
            raise ValueError("event_type is required and must be non-empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        utc_time = self.occurred_at.astimezone(timezone.utc)
        object.__setattr__(self, "occurred_at", utc_time)
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version <= 0:
            raise ValueError("schema_version must be a positive integer")
        object.__setattr__(self, "payload", _freeze_json_compatible(self.payload))

    @classmethod
    def create(
        cls,
        tenant_id: str,
        event_type: str,
        payload: Any | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        schema_version: int = 1,
    ) -> Event:
        payload_to_use = payload if payload is not None else {}
        return cls(
            event_id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc),
            payload=payload_to_use,
            correlation_id=correlation_id,
            causation_id=causation_id,
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "tenant_id": self.tenant_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": _unfreeze_json_compatible(self.payload),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "schema_version": self.schema_version,
        }
