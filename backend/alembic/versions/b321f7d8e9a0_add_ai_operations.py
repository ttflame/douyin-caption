"""Add durable AI operation records.

Revision ID: b321f7d8e9a0
Revises: 746f36c10c40
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b321f7d8e9a0"
down_revision: str | Sequence[str] | None = "746f36c10c40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_operations",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("initial_task_state", sa.String(length=32), nullable=False),
        sa.Column("running_task_state", sa.String(length=32), nullable=False),
        sa.Column("completed_task_state", sa.String(length=32), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["rewrite_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "task_id",
            "kind",
            "idempotency_key",
            name="uq_ai_operations_scope_idempotency_key",
        ),
    )
    op.create_index("ix_ai_operations_owner_created", "ai_operations", ["owner_id", "created_at"])
    op.create_index("ix_ai_operations_task_created", "ai_operations", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_operations_task_created", table_name="ai_operations")
    op.drop_index("ix_ai_operations_owner_created", table_name="ai_operations")
    op.drop_table("ai_operations")
