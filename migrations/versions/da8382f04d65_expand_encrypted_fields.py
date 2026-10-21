"""expand encrypted fields

Revision ID: da8382f04d65
Revises: 08007d24fbae
Create Date: 2026-08-24 19:08:28.170943
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "da8382f04d65"
down_revision: str | Sequence[str] | None = "08007d24fbae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.alter_column(
            "biometric_ref",
            existing_type=sa.VARCHAR(length=200),
            type_=sa.Text(),
            existing_nullable=True,
        )
    with op.batch_alter_table("payments") as batch:
        batch.alter_column(
            "method_token",
            existing_type=sa.VARCHAR(length=240),
            type_=sa.Text(),
            existing_nullable=False,
        )
    op.execute(
        "UPDATE audit_events SET resource_id = customer_id WHERE event_type = 'FaceEnrolled'"
    )


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.alter_column(
            "method_token",
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=240),
            existing_nullable=False,
        )
    with op.batch_alter_table("customers") as batch:
        batch.alter_column(
            "biometric_ref",
            existing_type=sa.Text(),
            type_=sa.VARCHAR(length=200),
            existing_nullable=True,
        )
