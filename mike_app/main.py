from fastapi import FastAPI
from openai import OpenAI

from mike_app.api.dev_inspection import router as dev_inspection_router
from mike_app.api.dev_messages import router as dev_messages_router
from mike_app.api.health import router as health_router
from mike_app.core.settings import get_settings
from mike_app.handlers.message_acceptance import MessageAcceptanceHandler
from mike_app.handlers.message_perception import MessagePerceptionHandler
from mike_app.handlers.perception_normalization import (
    PerceptionNormalizationHandler,
)
from mike_app.perception.normalization import PerceptionNormalizer
from mike_app.perception.openai_client import OpenAIPerceptionClient
from mike_app.perception.service import PerceptionService
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.episode_store import InMemoryEpisodeStore
from mike_app.runtime.event_store import InMemoryEventStore
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry

app = FastAPI(title="MIKE", version="0.1.0")

event_store = InMemoryEventStore()
episode_store = InMemoryEpisodeStore()
episode_coordinator = EpisodeCoordinator(event_store, episode_store)
runtime_handler_registry = RuntimeHandlerRegistry()
runtime_dispatcher = RuntimeDispatcher(runtime_handler_registry)
settings = get_settings()
perception_normalizer = PerceptionNormalizer()
perception_normalization_handler = PerceptionNormalizationHandler(
    episode_coordinator,
    perception_normalizer,
)
runtime_handler_registry.register(
    "message.perceived",
    perception_normalization_handler,
)

openai_sdk_client = None
openai_perception_client = None
perception_service = None
message_perception_handler = None
perception_enabled = bool(
    settings.openai_api_key
    and settings.openai_api_key.strip()
    and settings.openai_model
    and settings.openai_model.strip()
)
if perception_enabled:
    openai_sdk_client = OpenAI(
        api_key=settings.openai_api_key,
        max_retries=0,
    )
    openai_perception_client = OpenAIPerceptionClient(
        openai_sdk_client,
        settings.openai_model,
    )
    perception_service = PerceptionService(openai_perception_client)
    message_perception_handler = MessagePerceptionHandler(
        episode_coordinator,
        perception_service,
        runtime_dispatcher,
    )
    runtime_handler_registry.register(
        "message.accepted",
        message_perception_handler,
    )

message_acceptance_handler = MessageAcceptanceHandler(
    episode_coordinator,
    runtime_dispatcher,
)
runtime_handler_registry.register(
    "message.received",
    message_acceptance_handler,
)

app.state.event_store = event_store
app.state.episode_store = episode_store
app.state.episode_coordinator = episode_coordinator
app.state.runtime_handler_registry = runtime_handler_registry
app.state.runtime_dispatcher = runtime_dispatcher
app.state.message_acceptance_handler = message_acceptance_handler
app.state.openai_sdk_client = openai_sdk_client
app.state.openai_perception_client = openai_perception_client
app.state.perception_service = perception_service
app.state.message_perception_handler = message_perception_handler
app.state.perception_enabled = perception_enabled
app.state.perception_normalizer = perception_normalizer
app.state.perception_normalization_handler = (
    perception_normalization_handler
)

app.include_router(health_router)
app.include_router(dev_messages_router)
app.include_router(dev_inspection_router)
