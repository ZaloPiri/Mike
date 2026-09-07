from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    inspect,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mike_app.runtime.episode import CognitiveEpisode
from mike_app.runtime.delivery_outbox import DeliveryOutboxEntry
from mike_app.runtime.episode_journal import (
    EpisodeConcurrencyConflictError,
    _reject_delivery_requested_for_ordinary_append,
    _validate_delivery_append,
)
from mike_app.runtime.event import Event


class EpisodeJournalInfrastructureError(RuntimeError):
    pass


metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


class EpisodeRow(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("episode_id", "tenant_id"),
        CheckConstraint("schema_version > 0"),
        CheckConstraint("length(btrim(tenant_id)) > 0"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["episode_id", "tenant_id"],
            ["episodes.episode_id", "episodes.tenant_id"],
        ),
        UniqueConstraint("episode_id", "sequence"),
        UniqueConstraint(
            "event_id",
            "episode_id",
            "tenant_id",
            name="uq_events_event_episode_tenant",
        ),
        CheckConstraint("sequence >= 0"),
        CheckConstraint("schema_version > 0"),
        CheckConstraint("length(btrim(tenant_id)) > 0"),
        CheckConstraint("length(btrim(event_type)) > 0"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    journal_position: Mapped[int] = mapped_column(
        BigInteger, Identity(), nullable=False, unique=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)


class DeliveryOutboxRow(Base):
    __tablename__ = "delivery_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["episode_id", "tenant_id"],
            ["episodes.episode_id", "episodes.tenant_id"],
            name="fk_delivery_outbox_episode_tenant",
        ),
        ForeignKeyConstraint(
            ["delivery_request_event_id", "episode_id", "tenant_id"],
            ["events.event_id", "events.episode_id", "events.tenant_id"],
            name="fk_delivery_outbox_delivery_event_episode_tenant",
        ),
        ForeignKeyConstraint(
            ["response_ready_event_id", "episode_id", "tenant_id"],
            ["events.event_id", "events.episode_id", "events.tenant_id"],
            name="fk_delivery_outbox_ready_event_episode_tenant",
        ),
        UniqueConstraint(
            "delivery_request_event_id",
            name="uq_delivery_outbox_delivery_request_event_id",
        ),
        UniqueConstraint(
            "response_ready_event_id",
            name="uq_delivery_outbox_response_ready_event_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_delivery_outbox_idempotency_key",
        ),
        CheckConstraint(
            "length(btrim(tenant_id)) > 0",
            name="ck_delivery_outbox_tenant_non_empty",
        ),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_delivery_outbox_idempotency_key_non_empty",
        ),
        CheckConstraint(
            "length(btrim(channel)) > 0",
            name="ck_delivery_outbox_channel_non_empty",
        ),
        CheckConstraint(
            "length(btrim(external_conversation_id)) > 0",
            name="ck_delivery_outbox_conversation_non_empty",
        ),
        CheckConstraint(
            "length(btrim(outbound_sender_id)) > 0",
            name="ck_delivery_outbox_sender_non_empty",
        ),
        CheckConstraint(
            "length(btrim(outbound_recipient_id)) > 0",
            name="ck_delivery_outbox_recipient_non_empty",
        ),
        CheckConstraint(
            "length(btrim(response_type)) > 0",
            name="ck_delivery_outbox_response_type_non_empty",
        ),
        CheckConstraint(
            "length(btrim(language)) > 0",
            name="ck_delivery_outbox_language_non_empty",
        ),
        CheckConstraint(
            "length(btrim(text)) > 0",
            name="ck_delivery_outbox_text_non_empty",
        ),
        CheckConstraint(
            "status = 'pending'",
            name="ck_delivery_outbox_status_pending",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="ck_delivery_outbox_schema_version_positive",
        ),
    )

    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delivery_request_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    response_ready_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    external_conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    outbound_sender_id: Mapped[str] = mapped_column(Text, nullable=False)
    outbound_recipient_id: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)


class PostgreSQLEpisodeJournal:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def verify_schema(self) -> None:
        try:
            with self._engine.connect() as connection:
                tables = set(
                    connection.execute(
                        select(
                            func.to_regclass("public.episodes"),
                            func.to_regclass("public.events"),
                            func.to_regclass("public.delivery_outbox"),
                        )
                    ).one()
                )
                if None in tables:
                    raise EpisodeJournalInfrastructureError(
                        "required episode journal schema is missing"
                    )
                inspector = inspect(connection)
                expected_columns = {
                    "episodes": {
                        "episode_id", "tenant_id", "created_at", "updated_at",
                        "correlation_id", "schema_version",
                    },
                    "events": {
                        "event_id", "tenant_id", "episode_id", "sequence",
                        "journal_position", "event_type", "occurred_at", "payload",
                        "correlation_id", "causation_id", "schema_version",
                    },
                    "delivery_outbox": {
                        "outbox_id", "tenant_id", "episode_id",
                        "delivery_request_event_id", "response_ready_event_id",
                        "idempotency_key", "channel", "external_conversation_id",
                        "outbound_sender_id", "outbound_recipient_id",
                        "response_type", "language", "text", "status",
                        "created_at", "schema_version",
                    },
                }
                for table_name, expected in expected_columns.items():
                    actual = {column["name"] for column in inspector.get_columns(table_name)}
                    if actual != expected:
                        raise EpisodeJournalInfrastructureError(
                            "required episode journal schema is incompatible"
                        )
                event_unique_names = {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints(
                        "events"
                    )
                }
                outbox_foreign_key_names = {
                    constraint["name"]
                    for constraint in inspector.get_foreign_keys(
                        "delivery_outbox"
                    )
                }
                if (
                    "uq_events_event_episode_tenant"
                    not in event_unique_names
                    or not {
                        "fk_delivery_outbox_episode_tenant",
                        "fk_delivery_outbox_delivery_event_episode_tenant",
                        "fk_delivery_outbox_ready_event_episode_tenant",
                    }.issubset(outbox_foreign_key_names)
                ):
                    raise EpisodeJournalInfrastructureError(
                        "required episode journal schema is incompatible"
                    )
        except EpisodeJournalInfrastructureError:
            raise
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError(
                "PostgreSQL episode journal is unavailable"
            ) from exc

    def create_episode_with_event(self, episode: CognitiveEpisode, event: Event) -> CognitiveEpisode:
        if not isinstance(episode, CognitiveEpisode):
            raise TypeError("episode must be a CognitiveEpisode")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        _reject_delivery_requested_for_ordinary_append(event)
        if episode.tenant_id != event.tenant_id:
            raise ValueError("event tenant does not match episode tenant")
        if episode.event_ids != (event.event_id,):
            raise ValueError("initial episode must reference exactly its initial Event")
        try:
            with Session(self._engine) as session, session.begin():
                session.add(EpisodeRow(
                    episode_id=episode.episode_id, tenant_id=episode.tenant_id,
                    created_at=episode.created_at, updated_at=episode.updated_at,
                    correlation_id=episode.correlation_id, schema_version=episode.schema_version,
                ))
                session.add(self._event_row(event, episode.episode_id, 0))
            return episode
        except IntegrityError as exc:
            self._raise_integrity_error(exc, "event_id or episode_id")
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to create episode") from exc

    def append_event(self, tenant_id: str, episode_id: uuid.UUID, event: Event,
                     expected_event_ids: tuple[uuid.UUID, ...]) -> CognitiveEpisode:
        self._validate_append_inputs(tenant_id, episode_id, event, expected_event_ids)
        _reject_delivery_requested_for_ordinary_append(event)
        if event.tenant_id != tenant_id:
            raise ValueError("event tenant does not match episode tenant")
        try:
            with Session(self._engine) as session, session.begin():
                row = session.execute(
                    select(EpisodeRow).where(
                        EpisodeRow.episode_id == episode_id,
                        EpisodeRow.tenant_id == tenant_id,
                    ).with_for_update()
                ).scalar_one_or_none()
                if row is None:
                    raise ValueError("episode not found")
                ids = tuple(session.scalars(
                    select(EventRow.event_id).where(
                        EventRow.episode_id == episode_id
                    ).order_by(EventRow.sequence)
                ))
                if ids != expected_event_ids:
                    raise EpisodeConcurrencyConflictError(
                        "episode event_ids do not match expected_event_ids"
                    )
                if session.get(EventRow, event.event_id) is not None:
                    raise ValueError("duplicate event_id")
                updated = self._episode_from_row(row, ids).add_event(event)
                session.add(self._event_row(event, episode_id, len(ids)))
                row.updated_at = updated.updated_at
            return updated
        except (ValueError, EpisodeConcurrencyConflictError):
            raise
        except IntegrityError as exc:
            self._raise_integrity_error(exc, "event_id")
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to append event") from exc

    def append_event_with_outbox(
        self,
        tenant_id: str,
        episode_id: uuid.UUID,
        event: Event,
        expected_event_ids: tuple[uuid.UUID, ...],
        outbox_entry: DeliveryOutboxEntry,
    ) -> CognitiveEpisode:
        self._validate_append_inputs(
            tenant_id, episode_id, event, expected_event_ids
        )
        if not isinstance(outbox_entry, DeliveryOutboxEntry):
            raise TypeError("outbox_entry must be a DeliveryOutboxEntry")
        if event.tenant_id != tenant_id:
            raise ValueError("event tenant does not match episode tenant")
        try:
            with Session(self._engine) as session, session.begin():
                episode_row = session.execute(
                    select(EpisodeRow).where(
                        EpisodeRow.episode_id == episode_id,
                        EpisodeRow.tenant_id == tenant_id,
                    ).with_for_update()
                ).scalar_one_or_none()
                if episode_row is None:
                    raise ValueError("episode not found")
                event_rows = session.scalars(
                    select(EventRow).where(
                        EventRow.episode_id == episode_id,
                        EventRow.tenant_id == tenant_id,
                    ).order_by(EventRow.sequence)
                ).all()
                ids = tuple(row.event_id for row in event_rows)
                if ids != expected_event_ids:
                    raise EpisodeConcurrencyConflictError(
                        "episode event_ids do not match expected_event_ids"
                    )
                if session.get(EventRow, event.event_id) is not None:
                    raise ValueError("duplicate event_id")
                preceding_events = tuple(
                    self._event_from_row(row) for row in event_rows
                )
                _validate_delivery_append(
                    tenant_id,
                    episode_id,
                    preceding_events,
                    event,
                    outbox_entry,
                )
                updated = self._episode_from_row(
                    episode_row, ids
                ).add_event(event)
                session.add(self._event_row(event, episode_id, len(ids)))
                # Satisfy the outbox FK without committing the transaction.
                session.flush()
                session.add(self._outbox_row(outbox_entry))
                episode_row.updated_at = updated.updated_at
            return updated
        except (ValueError, EpisodeConcurrencyConflictError):
            raise
        except IntegrityError as exc:
            self._raise_integrity_error(exc, "outbox identifier")
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError(
                "failed to append event with outbox"
            ) from exc

    def get_event(self, tenant_id: str, event_id: uuid.UUID) -> Event | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(event_id, uuid.UUID):
            raise TypeError("event_id must be a uuid.UUID")
        return self._read_one_event(tenant_id, event_id)

    def get_episode(self, tenant_id: str, episode_id: uuid.UUID) -> CognitiveEpisode | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        try:
            with Session(self._engine) as session:
                row = session.execute(select(EpisodeRow).where(
                    EpisodeRow.episode_id == episode_id, EpisodeRow.tenant_id == tenant_id
                )).scalar_one_or_none()
                if row is None:
                    return None
                ids = tuple(session.scalars(select(EventRow.event_id).where(
                    EventRow.episode_id == episode_id
                ).order_by(EventRow.sequence)))
                return self._episode_from_row(row, ids)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to read episode") from exc

    def list_events(self, tenant_id: str, event_type: str | None = None) -> tuple[Event, ...]:
        self._validate_tenant_id(tenant_id)
        if event_type is not None:
            self._validate_event_type(event_type)
        try:
            with Session(self._engine) as session:
                query = select(EventRow).where(EventRow.tenant_id == tenant_id)
                if event_type is not None:
                    query = query.where(EventRow.event_type == event_type)
                rows = session.scalars(query.order_by(EventRow.journal_position)).all()
                return tuple(self._event_from_row(row) for row in rows)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to list events") from exc

    def list_episodes(self, tenant_id: str) -> tuple[CognitiveEpisode, ...]:
        self._validate_tenant_id(tenant_id)
        try:
            with Session(self._engine) as session:
                rows = session.scalars(
                    select(EpisodeRow).join(EventRow).where(
                        EpisodeRow.tenant_id == tenant_id, EventRow.sequence == 0
                    ).order_by(EventRow.journal_position)
                ).all()
                result = []
                for row in rows:
                    ids = tuple(session.scalars(select(EventRow.event_id).where(
                        EventRow.episode_id == row.episode_id
                    ).order_by(EventRow.sequence)))
                    result.append(self._episode_from_row(row, ids))
                return tuple(result)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to list episodes") from exc

    def get_outbox_entry(
        self,
        tenant_id: str,
        outbox_id: uuid.UUID,
    ) -> DeliveryOutboxEntry | None:
        self._validate_tenant_id(tenant_id)
        if not isinstance(outbox_id, uuid.UUID):
            raise TypeError("outbox_id must be a uuid.UUID")
        try:
            with Session(self._engine) as session:
                row = session.execute(
                    select(DeliveryOutboxRow).where(
                        DeliveryOutboxRow.outbox_id == outbox_id,
                        DeliveryOutboxRow.tenant_id == tenant_id,
                    )
                ).scalar_one_or_none()
                return None if row is None else self._outbox_from_row(row)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError(
                "failed to read outbox entry"
            ) from exc

    def list_outbox_entries(
        self,
        tenant_id: str,
    ) -> tuple[DeliveryOutboxEntry, ...]:
        self._validate_tenant_id(tenant_id)
        try:
            with Session(self._engine) as session:
                rows = session.scalars(
                    select(DeliveryOutboxRow).where(
                        DeliveryOutboxRow.tenant_id == tenant_id
                    ).order_by(
                        DeliveryOutboxRow.created_at,
                        DeliveryOutboxRow.outbox_id,
                    )
                ).all()
                return tuple(self._outbox_from_row(row) for row in rows)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError(
                "failed to list outbox entries"
            ) from exc

    def total_event_count(self) -> int:
        return self._count(EventRow)

    def total_episode_count(self) -> int:
        return self._count(EpisodeRow)

    def _count(self, model: type[Base]) -> int:
        try:
            with Session(self._engine) as session:
                return int(session.scalar(select(func.count()).select_from(model)) or 0)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to count journal records") from exc

    def _read_one_event(self, tenant_id: str, event_id: uuid.UUID) -> Event | None:
        try:
            with Session(self._engine) as session:
                row = session.execute(select(EventRow).where(
                    EventRow.event_id == event_id, EventRow.tenant_id == tenant_id
                )).scalar_one_or_none()
                return None if row is None else self._event_from_row(row)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to read event") from exc

    @staticmethod
    def _event_row(event: Event, episode_id: uuid.UUID, sequence: int) -> EventRow:
        return EventRow(
            event_id=event.event_id, tenant_id=event.tenant_id, episode_id=episode_id,
            sequence=sequence, event_type=event.event_type, occurred_at=event.occurred_at,
            payload=event.to_dict()["payload"], correlation_id=event.correlation_id,
            causation_id=event.causation_id, schema_version=event.schema_version,
        )

    @staticmethod
    def _event_from_row(row: EventRow) -> Event:
        return Event(
            event_id=row.event_id, tenant_id=row.tenant_id, event_type=row.event_type,
            occurred_at=row.occurred_at, payload=row.payload,
            correlation_id=row.correlation_id, causation_id=row.causation_id,
            schema_version=row.schema_version,
        )

    @staticmethod
    def _outbox_row(entry: DeliveryOutboxEntry) -> DeliveryOutboxRow:
        return DeliveryOutboxRow(
            outbox_id=entry.outbox_id,
            tenant_id=entry.tenant_id,
            episode_id=entry.episode_id,
            delivery_request_event_id=entry.delivery_request_event_id,
            response_ready_event_id=entry.response_ready_event_id,
            idempotency_key=entry.idempotency_key,
            channel=entry.channel,
            external_conversation_id=entry.external_conversation_id,
            outbound_sender_id=entry.outbound_sender_id,
            outbound_recipient_id=entry.outbound_recipient_id,
            response_type=entry.response_type,
            language=entry.language,
            text=entry.text,
            status=entry.status,
            created_at=entry.created_at,
            schema_version=entry.schema_version,
        )

    @staticmethod
    def _outbox_from_row(row: DeliveryOutboxRow) -> DeliveryOutboxEntry:
        return DeliveryOutboxEntry(
            outbox_id=row.outbox_id,
            tenant_id=row.tenant_id,
            episode_id=row.episode_id,
            delivery_request_event_id=row.delivery_request_event_id,
            response_ready_event_id=row.response_ready_event_id,
            idempotency_key=row.idempotency_key,
            channel=row.channel,
            external_conversation_id=row.external_conversation_id,
            outbound_sender_id=row.outbound_sender_id,
            outbound_recipient_id=row.outbound_recipient_id,
            response_type=row.response_type,
            language=row.language,
            text=row.text,
            status=row.status,
            created_at=row.created_at,
            schema_version=row.schema_version,
        )

    @staticmethod
    def _episode_from_row(row: EpisodeRow, ids: tuple[uuid.UUID, ...]) -> CognitiveEpisode:
        return CognitiveEpisode(
            episode_id=row.episode_id, tenant_id=row.tenant_id,
            created_at=row.created_at, updated_at=row.updated_at,
            event_ids=ids, correlation_id=row.correlation_id,
            schema_version=row.schema_version,
        )

    @classmethod
    def _validate_append_inputs(cls, tenant_id: str, episode_id: uuid.UUID,
                                event: Event, expected: tuple[uuid.UUID, ...]) -> None:
        cls._validate_tenant_id(tenant_id)
        if not isinstance(episode_id, uuid.UUID):
            raise TypeError("episode_id must be a uuid.UUID")
        if not isinstance(event, Event):
            raise TypeError("event must be an Event instance")
        if not isinstance(expected, tuple) or not all(isinstance(item, uuid.UUID) for item in expected):
            raise TypeError("expected_event_ids must be a tuple of uuid.UUID")

    @staticmethod
    def _validate_tenant_id(value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("tenant_id must be a string")
        if not value or not value.strip():
            raise ValueError("tenant_id is required and must be non-empty")

    @staticmethod
    def _validate_event_type(value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("event_type must be a string")
        if not value or not value.strip():
            raise ValueError("event_type is required and must be non-empty")

    @staticmethod
    def _raise_integrity_error(exc: IntegrityError, duplicate_field: str) -> None:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise ValueError(f"duplicate {duplicate_field}") from exc
        raise ValueError("episode journal integrity constraint violated") from exc
