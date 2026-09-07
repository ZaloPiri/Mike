from contextlib import asynccontextmanager

from fastapi import FastAPI
from openai import OpenAI
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from mike_app.api.dev_inspection import router as dev_inspection_router
from mike_app.api.dev_messages import router as dev_messages_router
from mike_app.api.health import router as health_router
from mike_app.communication.target_resolution import (
    ConversationResponseTargetResolver,
)
from mike_app.communication.delivery_request import (
    ConversationDeliveryRequestPlanner,
)
from mike_app.communication.readiness import (
    ConversationResponseReadinessEvaluator,
)
from mike_app.conversation.action_planning import ConversationActionPlanner
from mike_app.conversation.response_generation import (
    DeterministicResponseGenerator,
)
from mike_app.conversation.response_planning import ResponseRequestPlanner
from mike_app.conversation.response_validation import (
    ConversationResponseValidator,
)
from mike_app.core.settings import Settings, get_settings, validate_episode_journal_settings
from mike_app.handlers.conversation_next_action import (
    ConversationNextActionHandler,
)
from mike_app.handlers.conversation_response_request import (
    ConversationResponseRequestHandler,
)
from mike_app.handlers.conversation_response_generated import (
    ConversationResponseGeneratedHandler,
)
from mike_app.handlers.conversation_response_validated import (
    ConversationResponseValidatedHandler,
)
from mike_app.handlers.conversation_response_target_resolved import (
    ConversationResponseTargetResolvedHandler,
)
from mike_app.handlers.conversation_response_ready import (
    ConversationResponseReadyHandler,
)
from mike_app.handlers.conversation_delivery_requested import (
    ConversationDeliveryRequestedHandler,
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
from mike_app.runtime.episode_journal import (
    EpisodeJournalView,
    EventJournalView,
    InMemoryEpisodeJournal,
)
from mike_app.runtime.handler_registry import RuntimeHandlerRegistry
from mike_app.runtime.postgresql_episode_journal import (
    EpisodeJournalInfrastructureError,
    PostgreSQLEpisodeJournal,
)

def _configure_app(app: FastAPI, episode_journal) -> None:
    settings: Settings = app.state.settings
    event_store = EventJournalView(episode_journal)
    episode_store = EpisodeJournalView(episode_journal)
    episode_coordinator = EpisodeCoordinator(episode_journal)
    runtime_handler_registry = RuntimeHandlerRegistry()
    runtime_dispatcher = RuntimeDispatcher(runtime_handler_registry)

    conversation_delivery_request_planner = (
        ConversationDeliveryRequestPlanner()
    )
    conversation_delivery_requested_handler = (
        ConversationDeliveryRequestedHandler(
            episode_coordinator,
            conversation_delivery_request_planner,
        )
    )
    runtime_handler_registry.register(
        "conversation.response_ready",
        conversation_delivery_requested_handler,
    )

    deterministic_response_generator = DeterministicResponseGenerator()
    conversation_response_validator = ConversationResponseValidator()
    conversation_response_readiness_evaluator = (
    ConversationResponseReadinessEvaluator()
)
    conversation_response_ready_handler = ConversationResponseReadyHandler(
        episode_coordinator,
        conversation_response_readiness_evaluator,
        runtime_dispatcher,
    )
    runtime_handler_registry.register(
    "communication.response_target_resolved",
    conversation_response_ready_handler,
)
    conversation_response_target_resolver = (
    ConversationResponseTargetResolver()
)
    conversation_response_target_resolved_handler = (
    ConversationResponseTargetResolvedHandler(
        episode_coordinator,
        conversation_response_target_resolver,
        runtime_dispatcher,
    )
)
    runtime_handler_registry.register(
    "conversation.response_validated",
    conversation_response_target_resolved_handler,
)
    conversation_response_validated_handler = (
    ConversationResponseValidatedHandler(
        episode_coordinator,
        conversation_response_validator,
        runtime_dispatcher,
    )
)
    runtime_handler_registry.register(
    "conversation.response_generated",
    conversation_response_validated_handler,
)
    conversation_response_generated_handler = (
    ConversationResponseGeneratedHandler(
        episode_coordinator,
        deterministic_response_generator,
        runtime_dispatcher,
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

    app.state.episode_journal = episode_journal
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
    app.state.conversation_response_validator = conversation_response_validator
    app.state.conversation_response_readiness_evaluator = (
    conversation_response_readiness_evaluator
)
    app.state.conversation_response_ready_handler = (
    conversation_response_ready_handler
)
    app.state.conversation_response_target_resolver = (
    conversation_response_target_resolver
)
    app.state.conversation_response_target_resolved_handler = (
    conversation_response_target_resolved_handler
)
    app.state.conversation_response_validated_handler = (
    conversation_response_validated_handler
)
    app.state.conversation_response_generated_handler = (
    conversation_response_generated_handler
)
    app.state.conversation_delivery_request_planner = (
        conversation_delivery_request_planner
    )
    app.state.conversation_delivery_requested_handler = (
        conversation_delivery_requested_handler
    )



@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    validate_episode_journal_settings(settings)
    if settings.episode_journal == "postgres":
        try:
            engine = create_engine(settings.database_url, pool_pre_ping=True)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError(
                "PostgreSQL episode journal configuration is invalid"
            ) from exc
        journal = PostgreSQLEpisodeJournal(engine)
        try:
            journal.verify_schema()
            _configure_app(app, journal)
            yield
        finally:
            engine.dispose()
        return
    _configure_app(app, InMemoryEpisodeJournal())
    yield


def create_app(app_settings: Settings | None = None) -> FastAPI:
    settings = app_settings if app_settings is not None else get_settings()
    created = FastAPI(title="MIKE", version="0.1.0", lifespan=lifespan)
    created.state.settings = settings
    created.include_router(health_router)
    created.include_router(dev_messages_router)
    created.include_router(dev_inspection_router)
    return created


app = create_app()
