"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("apple_id", sa.String(256), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("subscription_status", sa.String(32), nullable=False, server_default="free"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── profiles ──────────────────────────────────────────────────────────────
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("gender", sa.String(32), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("time_of_birth", sa.Time(), nullable=False),
        sa.Column("time_known", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("city_name", sa.String(256), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("timezone_id", sa.String(64), nullable=False),
        sa.Column("utc_offset_at_birth", sa.Integer(), nullable=False),
        sa.Column("natal_chart_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interpretation_mode", sa.String(32), nullable=False, server_default="Practical Daily"),
        sa.Column("notification_time", sa.Time(), nullable=True),
        sa.Column("fcm_token", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_profile_user_id"),
    )

    # ── daily_advice ──────────────────────────────────────────────────────────
    op.create_table(
        "daily_advice",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("theme", sa.Text(), nullable=False),
        sa.Column("moon_phase", sa.String(32), nullable=False),
        sa.Column("transit_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("love_score", sa.SmallInteger(), nullable=False),
        sa.Column("love_text", sa.Text(), nullable=False),
        sa.Column("work_score", sa.SmallInteger(), nullable=False),
        sa.Column("work_text", sa.Text(), nullable=False),
        sa.Column("energy_score", sa.SmallInteger(), nullable=False),
        sa.Column("energy_text", sa.Text(), nullable=False),
        sa.Column("communication_score", sa.SmallInteger(), nullable=False),
        sa.Column("communication_text", sa.Text(), nullable=False),
        sa.Column("mood_score", sa.SmallInteger(), nullable=False),
        sa.Column("mood_text", sa.Text(), nullable=False),
        sa.Column("risk_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "date", "mode", name="uq_user_date_mode"),
    )
    op.create_index("idx_daily_advice_user_date", "daily_advice", ["user_id", sa.text("date DESC")])


def downgrade() -> None:
    op.drop_index("idx_daily_advice_user_date", table_name="daily_advice")
    op.drop_table("daily_advice")
    op.drop_table("profiles")
    op.drop_table("users")
