"""persist onboarding chat sessions

Revision ID: c4f1b2a3d4e5
Revises: da8382f04d65
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f1b2a3d4e5"
down_revision: str | Sequence[str] | None = "da8382f04d65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onboarding_chat_sessions",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=True),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("challenge_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        op.f("ix_onboarding_chat_sessions_customer_id"),
        "onboarding_chat_sessions",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_onboarding_chat_sessions_customer_id"),
        table_name="onboarding_chat_sessions",
    )
    op.drop_table("onboarding_chat_sessions")
