import uuid

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, field_validator

from mike_app.communication.target_resolution import CommunicationContext
from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class LocalMessageRequest(BaseModel):
    tenant_id: str
    text: str

    @field_validator("tenant_id", "text")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        if not value or value.strip() == "":
            raise ValueError("must be a non-empty string")
        return value


class LocalMessageResponse(BaseModel):
    event_id: uuid.UUID
    episode_id: uuid.UUID
    event_type: str
    tenant_id: str
    dispatched: bool


router = APIRouter()


@router.post(
    "/dev/messages",
    response_model=LocalMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def receive_local_message(
    message: LocalMessageRequest,
    request: Request,
) -> LocalMessageResponse:
    episode_coordinator: EpisodeCoordinator = request.app.state.episode_coordinator
    runtime_dispatcher: RuntimeDispatcher = request.app.state.runtime_dispatcher

    communication_context = CommunicationContext(
        channel="development",
        external_message_id=str(uuid.uuid4()),
        external_conversation_id=str(uuid.uuid4()),
        sender_id="development-user",
        recipient_id=message.tenant_id,
    )

    event = Event.create(
        tenant_id=message.tenant_id,
        event_type="message.received",
        payload={
            "text": message.text,
            "channel": communication_context.channel,
            "external_message_id": (
                communication_context.external_message_id
            ),
            "external_conversation_id": (
                communication_context.external_conversation_id
            ),
            "sender_id": communication_context.sender_id,
            "recipient_id": communication_context.recipient_id,
        },
    )
    episode = episode_coordinator.start_episode(event)
    context = RuntimeContext.create(event)
    runtime_dispatcher.dispatch(context)

    return LocalMessageResponse(
        event_id=event.event_id,
        episode_id=episode.episode_id,
        event_type=event.event_type,
        tenant_id=event.tenant_id,
        dispatched=True,
    )
