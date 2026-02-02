"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.Integer, unique=True, index=True),
        sa.Column("username", sa.String(length=255)),
        sa.Column("first_name", sa.String(length=255)),
        sa.Column("status", sa.Enum("active", "banned", name="userstatus"), nullable=False),
        sa.Column("accepted_aup", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), unique=True),
        sa.Column("status", sa.Enum("active", "expired", name="subscriptionstatus"), nullable=False),
        sa.Column("end_at", sa.DateTime),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("device_id", sa.String(length=36), unique=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(length=255)),
        sa.Column("status", sa.Enum("active", "revoked", name="devicestatus"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime),
        sa.Column("rotated_at", sa.DateTime),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("provider", sa.String(length=50)),
        sa.Column("external_id", sa.String(length=255)),
        sa.Column("plan_id", sa.String(length=50)),
        sa.Column("amount", sa.Integer),
        sa.Column("status", sa.Enum("pending", "succeeded", "failed", name="paymentstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("uq_payments_external_id", "payments", ["external_id"], unique=True)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_telegram_id", sa.Integer),
        sa.Column("action", sa.String(length=255)),
        sa.Column("metadata", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("uq_payments_external_id", table_name="payments")
    op.drop_table("payments")
    op.drop_table("devices")
    op.drop_table("subscriptions")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.execute("DROP TYPE IF EXISTS devicestatus")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
    op.execute("DROP TYPE IF EXISTS userstatus")
