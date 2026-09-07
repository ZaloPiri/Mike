"""Create the atomic delivery request outbox."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260820_0002"
down_revision = "20260812_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_events_event_episode_tenant",
        "events",
        ["event_id", "episode_id", "tenant_id"],
    )
    op.create_table(
        "delivery_outbox",
        sa.Column(
            "outbox_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "episode_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "delivery_request_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "response_ready_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_conversation_id", sa.Text(), nullable=False),
        sa.Column("outbound_sender_id", sa.Text(), nullable=False),
        sa.Column("outbound_recipient_id", sa.Text(), nullable=False),
        sa.Column("response_type", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["episode_id", "tenant_id"],
            ["episodes.episode_id", "episodes.tenant_id"],
            name="fk_delivery_outbox_episode_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_request_event_id", "episode_id", "tenant_id"],
            ["events.event_id", "events.episode_id", "events.tenant_id"],
            name="fk_delivery_outbox_delivery_event_episode_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["response_ready_event_id", "episode_id", "tenant_id"],
            ["events.event_id", "events.episode_id", "events.tenant_id"],
            name="fk_delivery_outbox_ready_event_episode_tenant",
        ),
        sa.UniqueConstraint(
            "delivery_request_event_id",
            name="uq_delivery_outbox_delivery_request_event_id",
        ),
        sa.UniqueConstraint(
            "response_ready_event_id",
            name="uq_delivery_outbox_response_ready_event_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_delivery_outbox_idempotency_key",
        ),
        sa.CheckConstraint(
            "length(btrim(tenant_id)) > 0",
            name="ck_delivery_outbox_tenant_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_delivery_outbox_idempotency_key_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(channel)) > 0",
            name="ck_delivery_outbox_channel_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(external_conversation_id)) > 0",
            name="ck_delivery_outbox_conversation_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(outbound_sender_id)) > 0",
            name="ck_delivery_outbox_sender_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(outbound_recipient_id)) > 0",
            name="ck_delivery_outbox_recipient_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(response_type)) > 0",
            name="ck_delivery_outbox_response_type_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(language)) > 0",
            name="ck_delivery_outbox_language_non_empty",
        ),
        sa.CheckConstraint(
            "length(btrim(text)) > 0",
            name="ck_delivery_outbox_text_non_empty",
        ),
        sa.CheckConstraint(
            "status = 'pending'", name="ck_delivery_outbox_status_pending"
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_delivery_outbox_schema_version_positive",
        ),
    )


def downgrade() -> None:
    op.drop_table("delivery_outbox")
    op.drop_constraint(
        "uq_events_event_episode_tenant",
        "events",
        type_="unique",
    )
