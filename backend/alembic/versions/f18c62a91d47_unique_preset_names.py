"""Require unique personal preset names.

Revision ID: f18c62a91d47
Revises: e064b2c8d315
"""

from alembic import op

revision = "f18c62a91d47"
down_revision = "e064b2c8d315"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("creative_presets") as batch:
        batch.drop_index("ix_creative_presets_owner_name")
        batch.create_unique_constraint(
            "uq_creative_presets_owner_name", ["owner_id", "name"]
        )


def downgrade() -> None:
    with op.batch_alter_table("creative_presets") as batch:
        batch.drop_constraint("uq_creative_presets_owner_name", type_="unique")
        batch.create_index("ix_creative_presets_owner_name", ["owner_id", "name"])
