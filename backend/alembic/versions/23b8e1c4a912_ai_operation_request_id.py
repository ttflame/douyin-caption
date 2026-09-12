"""Add request tracing to queued AI operations."""

import sqlalchemy as sa
from alembic import op

revision = "23b8e1c4a912"
down_revision = "f18c62a91d47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_operations") as batch:
        batch.add_column(sa.Column("request_id", sa.String(80), nullable=True))
        batch.create_index("ix_ai_operations_request_id", ["request_id"])


def downgrade() -> None:
    with op.batch_alter_table("ai_operations") as batch:
        batch.drop_index("ix_ai_operations_request_id")
        batch.drop_column("request_id")
