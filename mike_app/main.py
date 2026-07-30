from fastapi import FastAPI

from mike_app.api.dev_messages import router as dev_messages_router
from mike_app.api.health import router as health_router
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

app.state.event_store = event_store
app.state.episode_store = episode_store
app.state.episode_coordinator = episode_coordinator
app.state.runtime_handler_registry = runtime_handler_registry
app.state.runtime_dispatcher = runtime_dispatcher

app.include_router(health_router)
app.include_router(dev_messages_router)
