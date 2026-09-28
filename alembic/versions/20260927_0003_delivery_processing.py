"""Add recoverable delivery processing and successful receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260927_0003"
down_revision = "20260820_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 23 restricted the outbox to pending rows.  Phase 24 introduces
    # processing/completed/failed states, so that historical check must be
    # removed before the new state machine can claim a row.
    op.drop_constraint("ck_delivery_outbox_status_pending", "delivery_outbox", type_="check")
    op.add_column("delivery_outbox", sa.Column("adapter_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("delivery_outbox", "adapter_attempt_count", server_default=None)
    op.add_column("delivery_outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("delivery_outbox", sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("delivery_outbox", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("delivery_outbox", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("delivery_outbox", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("delivery_outbox", sa.Column("delivery_accepted_event_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("uq_delivery_outbox_id_tenant", "delivery_outbox", ["tenant_id", "outbox_id"])
    op.create_foreign_key(
        "fk_delivery_outbox_accepted_event_episode_tenant",
        "delivery_outbox", "events",
        ["delivery_accepted_event_id", "episode_id", "tenant_id"],
        ["event_id", "episode_id", "tenant_id"],
    )
    op.create_unique_constraint("uq_delivery_outbox_accepted_event", "delivery_outbox", ["delivery_accepted_event_id"])
    op.create_check_constraint(
        "ck_delivery_outbox_status_valid", "delivery_outbox",
        "status in ('pending', 'processing', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_delivery_outbox_acceptance_pointer", "delivery_outbox",
        "(status = 'completed' and delivery_accepted_event_id is not null) or (status <> 'completed' and delivery_accepted_event_id is null)",
    )
    op.create_index("ix_delivery_outbox_eligibility", "delivery_outbox", ["tenant_id", "status", "next_attempt_at", "created_at", "outbox_id"])
    op.create_table(
        "delivery_receipts",
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_request_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.Text(), nullable=False),
        sa.Column("adapter", sa.Text(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_delivery_receipts_idempotency_key"),
        sa.ForeignKeyConstraint(["tenant_id", "outbox_id"], ["delivery_outbox.tenant_id", "delivery_outbox.outbox_id"], name="fk_delivery_receipts_outbox"),
        sa.CheckConstraint("length(btrim(tenant_id)) > 0", name="ck_delivery_receipts_tenant_non_empty"),
        sa.CheckConstraint("schema_version > 0", name="ck_delivery_receipts_schema_version_positive"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE delivery_outbox, delivery_receipts IN ACCESS EXCLUSIVE MODE"))
    checks = bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM delivery_outbox WHERE status IN ('processing','completed','failed'))
        OR EXISTS (SELECT 1 FROM delivery_outbox WHERE adapter_attempt_count > 0)
        OR EXISTS (SELECT 1 FROM delivery_outbox WHERE claim_token IS NOT NULL OR claimed_at IS NOT NULL OR lease_expires_at IS NOT NULL)
        OR EXISTS (SELECT 1 FROM delivery_outbox WHERE delivery_accepted_event_id IS NOT NULL)
        OR EXISTS (SELECT 1 FROM delivery_receipts)
    """)).scalar_one()
    if checks:
        raise RuntimeError("cannot downgrade Phase 24 schema while processing history exists")
    op.drop_table("delivery_receipts")
    op.drop_index("ix_delivery_outbox_eligibility", table_name="delivery_outbox")
    op.drop_constraint("ck_delivery_outbox_acceptance_pointer", "delivery_outbox", type_="check")
    op.drop_constraint("ck_delivery_outbox_status_valid", "delivery_outbox", type_="check")
    op.drop_constraint("uq_delivery_outbox_accepted_event", "delivery_outbox", type_="unique")
    op.drop_constraint("fk_delivery_outbox_accepted_event_episode_tenant", "delivery_outbox", type_="foreignkey")
    op.drop_constraint("uq_delivery_outbox_id_tenant", "delivery_outbox", type_="unique")
    for column in ("delivery_accepted_event_id", "last_error", "lease_expires_at", "claimed_at", "claim_token", "next_attempt_at", "adapter_attempt_count"):
        op.drop_column("delivery_outbox", column)
    op.create_check_constraint("ck_delivery_outbox_status_pending", "delivery_outbox", "status = 'pending'")
