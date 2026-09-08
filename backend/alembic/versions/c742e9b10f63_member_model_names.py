"""Store provider model names directly in member settings.

Revision ID: c742e9b10f63
Revises: b321f7d8e9a0
Create Date: 2026-09-07
"""

from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "c742e9b10f63"
down_revision = "b321f7d8e9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_settings", sa.Column("model_name", sa.String(150), nullable=True))
    op.execute(
        sa.text(
            "UPDATE provider_settings SET model_name = "
            "(SELECT provider_model_id FROM model_catalog_entries "
            "WHERE model_catalog_entries.id = provider_settings.model_id)"
        )
    )
    with op.batch_alter_table("provider_settings") as batch:
        batch.drop_constraint(
            "fk_provider_settings_model_id_model_catalog_entries", type_="foreignkey"
        )
        batch.drop_column("model_id")
        batch.alter_column(
            "model_name", new_column_name="model_id", existing_type=sa.String(150), nullable=False
        )
    op.drop_table("model_catalog_entries")


def downgrade() -> None:
    catalog = op.create_table(
        "model_catalog_entries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("provider_model_id", sa.String(150), nullable=False, unique=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column("provider_settings", sa.Column("catalog_id", sa.UUID(), nullable=True))
    settings = sa.table(
        "provider_settings",
        sa.column("model_id", sa.String(150)),
        sa.column("catalog_id", sa.UUID()),
    )
    connection = op.get_bind()
    for name in connection.scalars(sa.select(settings.c.model_id).distinct()).all():
        model_id = uuid4()
        connection.execute(
            catalog.insert().values(
                id=model_id,
                label=name[:100],
                provider_model_id=name,
                capabilities={},
                is_active=True,
            )
        )
        connection.execute(
            settings.update().where(settings.c.model_id == name).values(catalog_id=model_id)
        )
    with op.batch_alter_table("provider_settings") as batch:
        batch.drop_column("model_id")
        batch.alter_column(
            "catalog_id", new_column_name="model_id", existing_type=sa.UUID(), nullable=False
        )
    with op.batch_alter_table("provider_settings") as batch:
        batch.create_foreign_key(
            "fk_provider_settings_model_id_model_catalog_entries",
            "model_catalog_entries",
            ["model_id"],
            ["id"],
            ondelete="RESTRICT",
        )
