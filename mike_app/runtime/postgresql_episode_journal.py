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
    Index,
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
    _reject_delivery_accepted_for_ordinary_append,
    _validate_delivery_append,
)
from mike_app.runtime.event import Event
from mike_app.runtime.delivery_receipt import DeliveryReceipt, ReceiptConflictError, snapshot_hash


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
        UniqueConstraint("tenant_id", "outbox_id", name="uq_delivery_outbox_id_tenant"),
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
        ForeignKeyConstraint(
            ["delivery_accepted_event_id", "episode_id", "tenant_id"],
            ["events.event_id", "events.episode_id", "events.tenant_id"],
            name="fk_delivery_outbox_accepted_event_episode_tenant",
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
            "status in ('pending', 'processing', 'completed', 'failed')",
            name="ck_delivery_outbox_status_valid",
        ),
        CheckConstraint(
            "(status = 'completed' and delivery_accepted_event_id is not null) or (status <> 'completed' and delivery_accepted_event_id is null)",
            name="ck_delivery_outbox_acceptance_pointer",
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
    adapter_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claimed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_accepted_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class DeliveryReceiptRow(Base):
    __tablename__ = "delivery_receipts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_delivery_receipts_idempotency_key"),
        ForeignKeyConstraint(["tenant_id", "outbox_id"], ["delivery_outbox.tenant_id", "delivery_outbox.outbox_id"], name="fk_delivery_receipts_outbox"),
        CheckConstraint("length(btrim(tenant_id)) > 0", name="ck_delivery_receipts_tenant_non_empty"),
        CheckConstraint("schema_version > 0", name="ck_delivery_receipts_schema_version_positive"),
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delivery_request_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(Text, nullable=False)
    adapter: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
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
                            func.to_regclass("public.delivery_receipts"),
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
                        "created_at", "schema_version", "adapter_attempt_count",
                        "next_attempt_at", "claim_token", "claimed_at",
                        "lease_expires_at", "last_error", "delivery_accepted_event_id",
                    },
                    "delivery_receipts": {
                        "receipt_id", "tenant_id", "outbox_id", "delivery_request_event_id",
                        "idempotency_key", "snapshot_hash", "adapter", "accepted_at", "schema_version",
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
                outbox_unique_names = {
                    constraint["name"] for constraint in inspector.get_unique_constraints("delivery_outbox")
                }
                outbox_check_names = {
                    constraint["name"] for constraint in inspector.get_check_constraints("delivery_outbox")
                }
                receipt_unique_names = {
                    constraint["name"] for constraint in inspector.get_unique_constraints("delivery_receipts")
                }
                receipt_foreign_key_names = {
                    constraint["name"] for constraint in inspector.get_foreign_keys("delivery_receipts")
                }
                checks_by_name = {
                    constraint["name"]: " ".join(constraint["sqltext"].split()).lower()
                    for table_name in ("delivery_outbox", "delivery_receipts")
                    for constraint in inspector.get_check_constraints(table_name)
                }
                if (
                    "uq_events_event_episode_tenant"
                    not in event_unique_names
                    or not {
                        "fk_delivery_outbox_episode_tenant",
                        "fk_delivery_outbox_delivery_event_episode_tenant",
                        "fk_delivery_outbox_ready_event_episode_tenant",
                        "fk_delivery_outbox_accepted_event_episode_tenant",
                    }.issubset(outbox_foreign_key_names)
                    or not {"uq_delivery_outbox_accepted_event", "uq_delivery_outbox_id_tenant"}.issubset(outbox_unique_names)
                    or not {"ck_delivery_outbox_status_valid", "ck_delivery_outbox_acceptance_pointer"}.issubset(outbox_check_names)
                    or "uq_delivery_receipts_idempotency_key" not in receipt_unique_names
                    or "fk_delivery_receipts_outbox" not in receipt_foreign_key_names
                    or not all(value in checks_by_name.get("ck_delivery_outbox_status_valid", "") for value in ("status", "pending", "processing", "completed", "failed"))
                    or not all(value in checks_by_name.get("ck_delivery_outbox_acceptance_pointer", "") for value in ("status", "completed", "delivery_accepted_event_id", "is not null", "is null"))
                    or "schema_version > 0" not in checks_by_name.get("ck_delivery_receipts_schema_version_positive", "")
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
        _reject_delivery_accepted_for_ordinary_append(event)
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
        _reject_delivery_accepted_for_ordinary_append(event)
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

    def claim_one_delivery(self, tenant_id: str, now, lease_seconds: int) -> DeliveryOutboxEntry | None:
        from datetime import timedelta
        self._validate_tenant_id(tenant_id)
        try:
            with Session(self._engine) as session, session.begin():
                database_now = session.scalar(select(func.clock_timestamp()))
                query = select(DeliveryOutboxRow).where(
                    DeliveryOutboxRow.tenant_id == tenant_id,
                    ((DeliveryOutboxRow.status == "pending") & ((DeliveryOutboxRow.next_attempt_at.is_(None)) | (DeliveryOutboxRow.next_attempt_at <= func.clock_timestamp())))
                    | ((DeliveryOutboxRow.status == "processing") & (DeliveryOutboxRow.lease_expires_at <= func.clock_timestamp())),
                ).order_by(DeliveryOutboxRow.created_at, DeliveryOutboxRow.outbox_id).with_for_update(skip_locked=True).limit(1)
                row = session.scalars(query).first()
                if row is None:
                    return None
                database_now = session.scalar(select(func.clock_timestamp()))
                if row.status == "pending" and row.next_attempt_at is not None and row.next_attempt_at > database_now:
                    return None
                if row.status == "processing" and (row.lease_expires_at is None or row.lease_expires_at > database_now):
                    return None
                row.status = "processing"
                row.claim_token = uuid.uuid4()
                row.claimed_at = database_now
                row.lease_expires_at = database_now + timedelta(seconds=lease_seconds)
                session.flush()
                return self._outbox_from_row(row)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to claim delivery") from exc

    def get_delivery_receipt(self, tenant_id: str, idempotency_key: str) -> DeliveryReceipt | None:
        self._validate_tenant_id(tenant_id)
        try:
            with Session(self._engine) as session:
                row = session.scalars(select(DeliveryReceiptRow).where(DeliveryReceiptRow.tenant_id == tenant_id, DeliveryReceiptRow.idempotency_key == idempotency_key)).first()
                return None if row is None else self._receipt_from_row(row)
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to read delivery receipt") from exc

    def save_delivery_receipt(self, receipt: DeliveryReceipt, claim_token: uuid.UUID) -> DeliveryReceipt:
        try:
            with Session(self._engine) as session, session.begin():
                outbox = session.scalars(select(DeliveryOutboxRow).where(DeliveryOutboxRow.outbox_id == receipt.outbox_id, DeliveryOutboxRow.tenant_id == receipt.tenant_id).with_for_update()).one_or_none()
                database_now = session.scalar(select(func.clock_timestamp()))
                if outbox is None or outbox.status != "processing" or outbox.claim_token != claim_token or outbox.lease_expires_at is None or outbox.lease_expires_at <= database_now or receipt.snapshot_hash != snapshot_hash(self._outbox_from_row(outbox)):
                    raise ValueError("stale or invalid delivery claim")
                existing = session.scalars(select(DeliveryReceiptRow).where(DeliveryReceiptRow.idempotency_key == receipt.idempotency_key)).first()
                if existing is not None:
                    value = self._receipt_from_row(existing)
                    if value != receipt:
                        raise ReceiptConflictError("receipt idempotency conflict")
                    return value
                session.add(DeliveryReceiptRow(receipt_id=receipt.receipt_id, tenant_id=receipt.tenant_id, outbox_id=receipt.outbox_id, delivery_request_event_id=receipt.delivery_request_event_id, idempotency_key=receipt.idempotency_key, snapshot_hash=receipt.snapshot_hash, adapter=receipt.adapter, accepted_at=receipt.accepted_at, schema_version=receipt.schema_version))
                return receipt
        except ReceiptConflictError:
            raise
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to save delivery receipt") from exc

    def start_adapter_attempt(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, now) -> DeliveryOutboxEntry:
        try:
            with Session(self._engine) as session, session.begin():
                row = session.scalars(select(DeliveryOutboxRow).where(DeliveryOutboxRow.outbox_id == outbox_id, DeliveryOutboxRow.tenant_id == tenant_id).with_for_update()).one_or_none()
                database_now = session.scalar(select(func.clock_timestamp()))
                if row is None or row.status != "processing" or row.claim_token != claim_token or row.lease_expires_at is None or row.lease_expires_at <= database_now or row.adapter_attempt_count >= 3:
                    raise ValueError("stale or invalid delivery claim")
                row.adapter_attempt_count += 1
                session.flush()
                return self._outbox_from_row(row)
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to start adapter attempt") from exc

    def fail_delivery(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, now, error: str, retry_at) -> DeliveryOutboxEntry:
        from datetime import timedelta
        if not isinstance(error, str) or not error or len(error) > 512:
            raise ValueError("error must be a bounded non-empty string")
        try:
            with Session(self._engine) as session, session.begin():
                row = session.scalars(select(DeliveryOutboxRow).where(DeliveryOutboxRow.outbox_id == outbox_id, DeliveryOutboxRow.tenant_id == tenant_id).with_for_update()).one_or_none()
                database_now = session.scalar(select(func.clock_timestamp()))
                if row is None or row.status != "processing" or row.claim_token != claim_token or row.lease_expires_at is None or row.lease_expires_at <= database_now:
                    raise ValueError("stale or invalid delivery claim")
                if session.scalars(select(DeliveryReceiptRow).where(DeliveryReceiptRow.tenant_id == tenant_id, DeliveryReceiptRow.idempotency_key == row.idempotency_key)).first() is not None:
                    raise ValueError("successful receipt already exists")
                row.status = "pending" if retry_at is not None and row.adapter_attempt_count < 3 else "failed"
                row.next_attempt_at = database_now + timedelta(seconds=30 if row.adapter_attempt_count == 1 else 120) if retry_at is not None and row.adapter_attempt_count < 3 else None
                row.last_error = error
                row.claim_token = None
                row.claimed_at = None
                row.lease_expires_at = None
                session.flush()
                return self._outbox_from_row(row)
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to record delivery failure") from exc

    def finalize_delivery(self, tenant_id: str, outbox_id: uuid.UUID, claim_token: uuid.UUID, receipt: DeliveryReceipt) -> DeliveryOutboxEntry:
        try:
            with Session(self._engine) as session, session.begin():
                row = session.scalars(select(DeliveryOutboxRow).where(DeliveryOutboxRow.outbox_id == outbox_id, DeliveryOutboxRow.tenant_id == tenant_id).with_for_update()).one_or_none()
                database_now = session.scalar(select(func.clock_timestamp()))
                if row is None:
                    raise ValueError("outbox not found")
                if row.status == "completed":
                    return self._outbox_from_row(row)
                if row.status != "processing" or row.claim_token != claim_token or row.lease_expires_at is None or row.lease_expires_at <= database_now:
                    raise ValueError("stale or invalid delivery claim")
                stored = session.scalars(select(DeliveryReceiptRow).where(DeliveryReceiptRow.tenant_id == tenant_id, DeliveryReceiptRow.idempotency_key == receipt.idempotency_key)).one_or_none()
                if stored is None or self._receipt_from_row(stored) != receipt or not receipt.is_compatible(self._outbox_from_row(row)):
                    raise ValueError("receipt is not compatible with outbox")
                events = session.scalars(select(EventRow).where(EventRow.episode_id == row.episode_id, EventRow.tenant_id == tenant_id).order_by(EventRow.sequence)).all()
                if len(events) != 11 or events[-1].event_id != row.delivery_request_event_id:
                    raise ValueError("delivery request is not terminal in episode")
                request_event = events[-1]
                preceding = tuple(self._event_from_row(value) for value in events[:-1])
                _validate_delivery_append(tenant_id, row.episode_id, preceding, self._event_from_row(events[-1]), self._outbox_from_row(row))
                event = Event.create(tenant_id, "communication.delivery_accepted", {"schema_version": 1, "delivery_request_event_id": str(row.delivery_request_event_id), "response_ready_event_id": str(row.response_ready_event_id), "outbox_id": str(row.outbox_id), "receipt_id": str(receipt.receipt_id), "acceptance_method": "development_adapter", "adapter": "development"}, correlation_id=request_event.correlation_id, causation_id=str(row.delivery_request_event_id))
                episode_row = session.scalars(select(EpisodeRow).where(EpisodeRow.episode_id == row.episode_id, EpisodeRow.tenant_id == tenant_id).with_for_update()).one()
                session.add(self._event_row(event, row.episode_id, len(events)))
                # Materialize event 12 before setting the acceptance pointer;
                # PostgreSQL checks the composite FK at statement flush time.
                session.flush()
                row.delivery_accepted_event_id = event.event_id
                row.status = "completed"
                row.claim_token = None
                row.claimed_at = None
                row.lease_expires_at = None
                episode_row.updated_at = event.occurred_at
                session.flush()
                return self._outbox_from_row(row)
        except ValueError:
            raise
        except SQLAlchemyError as exc:
            raise EpisodeJournalInfrastructureError("failed to finalize delivery") from exc

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
            adapter_attempt_count=entry.adapter_attempt_count,
            next_attempt_at=entry.next_attempt_at,
            claim_token=entry.claim_token,
            claimed_at=entry.claimed_at,
            lease_expires_at=entry.lease_expires_at,
            last_error=entry.last_error,
            delivery_accepted_event_id=entry.delivery_accepted_event_id,
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
            adapter_attempt_count=row.adapter_attempt_count,
            next_attempt_at=row.next_attempt_at,
            claim_token=row.claim_token,
            claimed_at=row.claimed_at,
            lease_expires_at=row.lease_expires_at,
            last_error=row.last_error,
            delivery_accepted_event_id=row.delivery_accepted_event_id,
        )

    @staticmethod
    def _receipt_from_row(row: DeliveryReceiptRow) -> DeliveryReceipt:
        return DeliveryReceipt(
            receipt_id=row.receipt_id,
            tenant_id=row.tenant_id,
            outbox_id=row.outbox_id,
            delivery_request_event_id=row.delivery_request_event_id,
            idempotency_key=row.idempotency_key,
            snapshot_hash=row.snapshot_hash,
            adapter=row.adapter,
            accepted_at=row.accepted_at,
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
