"""Persist queued AI work independently of browser requests."""

import sqlalchemy as sa

from alembic import op

revision = "e064b2c8d315"
down_revision = "d953a1b7c204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_operations") as batch:
        batch.add_column(
            sa.Column("request_payload", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.add_column(sa.Column("task_name", sa.String(200), server_default="", nullable=False))
        batch.alter_column("started_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.execute(
        sa.text(
            "UPDATE ai_operations SET task_name = "
            "(SELECT name FROM rewrite_tasks WHERE rewrite_tasks.id = ai_operations.task_id)"
        )
    )
    op.create_index(
        "uq_ai_operations_active_task",
        "ai_operations",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_operations_active_task", table_name="ai_operations")
    op.execute(sa.text("UPDATE ai_operations SET started_at = created_at WHERE started_at IS NULL"))
    op.execute(
        sa.text(
            "UPDATE ai_operations SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP "
            "WHERE status = 'queued'"
        )
    )
    with op.batch_alter_table("ai_operations") as batch:
        batch.drop_column("request_payload")
        batch.drop_column("task_name")
        batch.alter_column("started_at", existing_type=sa.DateTime(timezone=True), nullable=False)
