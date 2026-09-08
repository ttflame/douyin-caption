"""Initial identity and rewriting-task schema.

Revision ID: 746f36c10c40
Revises:
Create Date: 2026-09-05 00:48:25.728993

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "746f36c10c40"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "members",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_members")),
    )
    op.create_index(op.f("ix_members_username"), "members", ["username"], unique=True)

    op.create_table(
        "model_catalog_entries",
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("provider_model_id", sa.String(length=150), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_catalog_entries")),
        sa.UniqueConstraint(
            "provider_model_id", name=op.f("uq_model_catalog_entries_provider_model_id")
        ),
    )

    op.create_table(
        "provider_settings",
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_provider_settings_member_id_members"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model_catalog_entries.id"],
            name=op.f("fk_provider_settings_model_id_model_catalog_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_settings")),
    )
    op.create_index(
        op.f("ix_provider_settings_member_id"),
        "provider_settings",
        ["member_id"],
        unique=True,
    )

    op.create_table(
        "rewrite_tasks",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("creative_settings", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("archived_from_state", sa.String(length=32), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "length(source_text) <= 20000",
            name=op.f("ck_rewrite_tasks_source_text_max_length"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["members.id"],
            name=op.f("fk_rewrite_tasks_owner_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rewrite_tasks")),
    )
    op.create_index(op.f("ix_rewrite_tasks_owner_id"), "rewrite_tasks", ["owner_id"])
    op.create_index("ix_rewrite_tasks_owner_updated", "rewrite_tasks", ["owner_id", "updated_at"])

    op.create_table(
        "creative_presets",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["members.id"],
            name=op.f("fk_creative_presets_owner_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creative_presets")),
    )
    op.create_index(op.f("ix_creative_presets_owner_id"), "creative_presets", ["owner_id"])
    op.create_index("ix_creative_presets_owner_name", "creative_presets", ["owner_id", "name"])

    op.create_table(
        "task_analyses",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("member_notes", sa.Text(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=32), nullable=False),
        sa.Column("model_identifier", sa.String(length=160), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["rewrite_tasks.id"],
            name=op.f("fk_task_analyses_task_id_rewrite_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_analyses")),
    )
    op.create_index(
        "ix_task_analyses_task_sequence",
        "task_analyses",
        ["task_id", "sequence"],
        unique=True,
    )

    op.create_table(
        "task_suggestions",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("suggestion_key", sa.String(length=80), nullable=False),
        sa.Column("analysis_issue_ids", sa.JSON(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("impact_scope", sa.Text(), nullable=False),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("member_note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["task_analyses.id"],
            name=op.f("fk_task_suggestions_analysis_id_task_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["rewrite_tasks.id"],
            name=op.f("fk_task_suggestions_task_id_rewrite_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_suggestions")),
    )
    op.create_index(
        "ix_task_suggestions_task_analysis",
        "task_suggestions",
        ["task_id", "analysis_id"],
    )

    op.create_table(
        "script_versions",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("validation_status", sa.String(length=24), nullable=False),
        sa.Column("validation_details", sa.JSON(), nullable=False),
        sa.Column("is_current_final", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["script_versions.id"],
            name=op.f("fk_script_versions_parent_id_script_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["rewrite_tasks.id"],
            name=op.f("fk_script_versions_task_id_rewrite_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_versions")),
    )
    op.create_index("ix_script_versions_task_created", "script_versions", ["task_id", "created_at"])

    op.create_table(
        "locked_fragments",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("source_version_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "end_offset > start_offset",
            name=op.f("ck_locked_fragments_end_after_start"),
        ),
        sa.CheckConstraint(
            "start_offset >= 0",
            name=op.f("ck_locked_fragments_start_offset_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["script_versions.id"],
            name=op.f("fk_locked_fragments_source_version_id_script_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["rewrite_tasks.id"],
            name=op.f("fk_locked_fragments_task_id_rewrite_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locked_fragments")),
    )
    op.create_index(
        "ix_locked_fragments_task_order",
        "locked_fragments",
        ["task_id", "order_index"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_locked_fragments_task_order", table_name="locked_fragments")
    op.drop_table("locked_fragments")
    op.drop_index("ix_script_versions_task_created", table_name="script_versions")
    op.drop_table("script_versions")
    op.drop_index("ix_task_suggestions_task_analysis", table_name="task_suggestions")
    op.drop_table("task_suggestions")
    op.drop_index("ix_task_analyses_task_sequence", table_name="task_analyses")
    op.drop_table("task_analyses")
    op.drop_index("ix_creative_presets_owner_name", table_name="creative_presets")
    op.drop_index(op.f("ix_creative_presets_owner_id"), table_name="creative_presets")
    op.drop_table("creative_presets")
    op.drop_index("ix_rewrite_tasks_owner_updated", table_name="rewrite_tasks")
    op.drop_index(op.f("ix_rewrite_tasks_owner_id"), table_name="rewrite_tasks")
    op.drop_table("rewrite_tasks")
    op.drop_index(op.f("ix_provider_settings_member_id"), table_name="provider_settings")
    op.drop_table("provider_settings")
    op.drop_table("model_catalog_entries")
    op.drop_index(op.f("ix_members_username"), table_name="members")
    op.drop_table("members")
