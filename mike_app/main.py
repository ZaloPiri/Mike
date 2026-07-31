from fastapi import FastAPI
from openai import OpenAI

from mike_app.api.dev_inspection import router as dev_inspection_router
from mike_app.api.dev_messages import router as dev_messages_router
from mike_app.api.health import router as health_router
from mike_app.conversation.action_planning import ConversationActionPlanner
from mike_app.conversation.response_generation import (
    DeterministicResponseGenerator,
)
from mike_app.conversation.response_planning import ResponseRequestPlanner
from mike_app.core.settings import get_settings
from mike_app.handlers.conversation_next_action import (
    ConversationNextActionHandler,
)
from mike_app.handlers.conversation_response_request import (
    ConversationResponseRequestHandler,
)
from mike_app.handlers.conversation_response_generated import (
    ConversationResponseGeneratedHandler,
)
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
deterministic_response_generator = DeterministicResponseGenerator()
conversation_response_generated_handler = (
    ConversationResponseGeneratedHandler(
        episode_coordinator,
        deterministic_response_generator,
    )
)
runtime_handler_registry.register(
    "conversation.response_request",
    conversation_response_generated_handler,
)
response_request_planner = ResponseRequestPlanner()
conversation_response_request_handler = (
    ConversationResponseRequestHandler(
        episode_coordinator,
        response_request_planner,
        runtime_dispatcher,
    )
)
runtime_handler_registry.register(
    "conversation.next_action",
    conversation_response_request_handler,
)
conversation_action_planner = ConversationActionPlanner()
conversation_next_action_handler = ConversationNextActionHandler(
    episode_coordinator,
    conversation_action_planner,
    runtime_dispatcher,
)
runtime_handler_registry.register(
    "perception.normalized",
    conversation_next_action_handler,
)
perception_normalizer = PerceptionNormalizer()
perception_normalization_handler = PerceptionNormalizationHandler(
    episode_coordinator,
    perception_normalizer,
    runtime_dispatcher,
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
app.state.conversation_action_planner = conversation_action_planner
app.state.conversation_next_action_handler = (
    conversation_next_action_handler
)
app.state.response_request_planner = response_request_planner
app.state.conversation_response_request_handler = (
    conversation_response_request_handler
)
app.state.deterministic_response_generator = (
    deterministic_response_generator
)
app.state.conversation_response_generated_handler = (
    conversation_response_generated_handler
)

app.include_router(health_router)
app.include_router(dev_messages_router)
app.include_router(dev_inspection_router)
