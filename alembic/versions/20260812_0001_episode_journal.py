"""Create the transactional episode journal schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260812_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "episodes",
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("episode_id", "tenant_id"),
        sa.CheckConstraint("schema_version > 0"),
        sa.CheckConstraint("length(btrim(tenant_id)) > 0"),
    )
    op.create_table(
        "events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("journal_position", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("causation_id", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["episode_id", "tenant_id"],
            ["episodes.episode_id", "episodes.tenant_id"],
        ),
        sa.UniqueConstraint("episode_id", "sequence"),
        sa.CheckConstraint("sequence >= 0"),
        sa.CheckConstraint("schema_version > 0"),
        sa.CheckConstraint("length(btrim(tenant_id)) > 0"),
        sa.CheckConstraint("length(btrim(event_type)) > 0"),
    )


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("episodes")
