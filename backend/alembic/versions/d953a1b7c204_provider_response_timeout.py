"""Persist member provider response deadlines.

Revision ID: d953a1b7c204
Revises: c742e9b10f63
"""

import sqlalchemy as sa

from alembic import op

revision = "d953a1b7c204"
down_revision = "c742e9b10f63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_settings",
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="240"),
    )


def downgrade() -> None:
    with op.batch_alter_table("provider_settings") as batch:
        batch.drop_column("timeout_seconds")
