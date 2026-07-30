from mike_app.runtime.context import RuntimeContext
from mike_app.runtime.dispatcher import RuntimeDispatcher
from mike_app.runtime.episode_coordinator import EpisodeCoordinator
from mike_app.runtime.event import Event


class MessageAcceptanceHandler:
    def __init__(
        self,
        episode_coordinator: EpisodeCoordinator,
        runtime_dispatcher: RuntimeDispatcher,
    ) -> None:
        if not isinstance(episode_coordinator, EpisodeCoordinator):
            raise TypeError(
                "episode_coordinator must be an EpisodeCoordinator"
            )
        self._episode_coordinator = episode_coordinator
        if not isinstance(runtime_dispatcher, RuntimeDispatcher):
            raise TypeError(
                "runtime_dispatcher must be a RuntimeDispatcher"
            )
        self._runtime_dispatcher = runtime_dispatcher

    def __call__(
        self,
        context: RuntimeContext,
    ) -> None:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be a RuntimeContext")

        source_event = context.event
        if source_event.event_type != "message.received":
            raise ValueError(
                "MessageAcceptanceHandler requires message.received"
            )

        episode = self._episode_coordinator.find_episode_for_event(
            source_event.tenant_id,
            source_event.event_id,
        )
        if episode is None:
            raise ValueError("source Event is not contained in an Episode")

        derived_event = Event.create(
            tenant_id=source_event.tenant_id,
            event_type="message.accepted",
            payload={"source_event_id": str(source_event.event_id)},
        )
        self._episode_coordinator.append_to_episode(
            episode.episode_id,
            derived_event,
        )
        self._runtime_dispatcher.dispatch(
            RuntimeContext.create(derived_event)
        )
