from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import AfterValidator, BaseModel

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.event import Event
from mike_app.runtime.episode_coordinator import EpisodeCoordinator


def _validate_tenant_id(value: str) -> str:
    if value.strip() == "":
        raise ValueError("tenant_id must be a non-empty string")
    return value


TenantId = Annotated[
    str,
    Path(min_length=1),
    AfterValidator(_validate_tenant_id),
]


class DevEventResponse(BaseModel):
    event_id: uuid.UUID
    tenant_id: str
    event_type: str
    payload: Any
    occurred_at: datetime
    correlation_id: str | None
    schema_version: int


class DevEpisodeSummaryResponse(BaseModel):
    episode_id: uuid.UUID
    tenant_id: str
    correlation_id: str | None
    schema_version: int
    created_at: datetime
    updated_at: datetime
    event_count: int


class DevEpisodeDetailResponse(BaseModel):
    episode_id: uuid.UUID
    tenant_id: str
    correlation_id: str | None
    schema_version: int
    created_at: datetime
    updated_at: datetime
    event_ids: list[uuid.UUID]
    events: list[DevEventResponse]


router = APIRouter()


def _event_response(event: Event) -> DevEventResponse:
    serialized = event.to_dict()
    return DevEventResponse(
        event_id=event.event_id,
        tenant_id=event.tenant_id,
        event_type=event.event_type,
        payload=serialized["payload"],
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        schema_version=event.schema_version,
    )


def _episode_summary(
    episode: CognitiveEpisode,
) -> DevEpisodeSummaryResponse:
    return DevEpisodeSummaryResponse(
        episode_id=episode.episode_id,
        tenant_id=episode.tenant_id,
        correlation_id=episode.correlation_id,
        schema_version=episode.schema_version,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
        event_count=len(episode.event_ids),
    )


@router.get(
    "/dev/tenants/{tenant_id}/events",
    response_model=list[DevEventResponse],
)
def list_tenant_events(
    tenant_id: TenantId,
    request: Request,
) -> list[DevEventResponse]:
    coordinator: EpisodeCoordinator = request.app.state.episode_coordinator
    return [
        _event_response(event)
        for event in coordinator.list_events(tenant_id)
    ]


@router.get(
    "/dev/tenants/{tenant_id}/episodes",
    response_model=list[DevEpisodeSummaryResponse],
)
def list_tenant_episodes(
    tenant_id: TenantId,
    request: Request,
) -> list[DevEpisodeSummaryResponse]:
    coordinator: EpisodeCoordinator = request.app.state.episode_coordinator
    return [
        _episode_summary(episode)
        for episode in coordinator.list_episodes(tenant_id)
    ]


@router.get(
    "/dev/tenants/{tenant_id}/episodes/{episode_id}",
    response_model=DevEpisodeDetailResponse,
)
def get_tenant_episode(
    tenant_id: TenantId,
    episode_id: uuid.UUID,
    request: Request,
) -> DevEpisodeDetailResponse:
    coordinator: EpisodeCoordinator = request.app.state.episode_coordinator
    episode = coordinator.get_episode(tenant_id, episode_id)
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Episode not found",
        )

    events: list[DevEventResponse] = []
    for event_id in episode.event_ids:
        event = coordinator.get_event(tenant_id, event_id)
        if event is None:
            raise RuntimeError(
                "Episode references an Event unavailable to its tenant"
            )
        events.append(_event_response(event))

    return DevEpisodeDetailResponse(
        episode_id=episode.episode_id,
        tenant_id=episode.tenant_id,
        correlation_id=episode.correlation_id,
        schema_version=episode.schema_version,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
        event_ids=list(episode.event_ids),
        events=events,
    )
