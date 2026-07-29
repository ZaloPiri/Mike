from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from mike_app.runtime.event import Event


@dataclass(frozen=True)
class CognitiveEpisode:
    episode_id: uuid.UUID
    tenant_id: str
    created_at: datetime
    updated_at: datetime
    event_ids: tuple[uuid.UUID, ...]
    correlation_id: str | None
    schema_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.episode_id, uuid.UUID):
            raise ValueError("episode_id must be a uuid.UUID")
        if not self.tenant_id or self.tenant_id.strip() == "":
            raise ValueError("tenant_id is required and must be non-empty")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        created_at_utc = self.created_at.astimezone(timezone.utc)
        updated_at_utc = self.updated_at.astimezone(timezone.utc)
        if updated_at_utc < created_at_utc:
            raise ValueError("updated_at must not be earlier than created_at")
        object.__setattr__(self, "created_at", created_at_utc)
        object.__setattr__(self, "updated_at", updated_at_utc)
        if not isinstance(self.event_ids, tuple):
            raise ValueError("event_ids must be a tuple")
        if not all(isinstance(event_id, uuid.UUID) for event_id in self.event_ids):
            raise ValueError("event_ids must contain only uuid.UUID values")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("duplicate event_ids are not allowed")
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version <= 0:
            raise ValueError("schema_version must be a positive integer")

    @classmethod
    def create(
        cls,
        initial_event: Event,
        correlation_id: str | None = None,
        schema_version: int = 1,
    ) -> CognitiveEpisode:
        if not isinstance(initial_event, Event):
            raise TypeError("initial_event must be an Event instance")
        now = datetime.now(timezone.utc)
        return cls(
            episode_id=uuid.uuid4(),
            tenant_id=initial_event.tenant_id,
            created_at=now,
            updated_at=now,
            event_ids=(initial_event.event_id,),
            correlation_id=correlation_id if correlation_id is not None else initial_event.correlation_id,
            schema_version=schema_version,
        )

    def add_event(self, event: Event) -> CognitiveEpisode:
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        if event.tenant_id != self.tenant_id:
            raise ValueError("event tenant does not match episode tenant")
        if event.event_id in self.event_ids:
            raise ValueError("event_id is already present")
        now = datetime.now(timezone.utc)
        return CognitiveEpisode(
            episode_id=self.episode_id,
            tenant_id=self.tenant_id,
            created_at=self.created_at,
            updated_at=now,
            event_ids=self.event_ids + (event.event_id,),
            correlation_id=self.correlation_id,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": str(self.episode_id),
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "event_ids": [str(event_id) for event_id in self.event_ids],
            "correlation_id": self.correlation_id,
            "schema_version": self.schema_version,
        }
