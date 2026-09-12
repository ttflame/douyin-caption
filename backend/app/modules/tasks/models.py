from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.tasks.domain import (
    AiOperationStatus,
    SuggestionDecision,
    SuggestionPriority,
    TaskState,
    ValidationStatus,
)


class RewriteTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rewrite_tasks"
    __table_args__ = (
        CheckConstraint("length(source_text) <= 20000", name="source_text_max_length"),
        Index("ix_rewrite_tasks_owner_updated", "owner_id", "updated_at"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    creative_settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=TaskState.DRAFT, nullable=False)
    archived_from_state: Mapped[str | None] = mapped_column(String(32))
    finalized_at: Mapped[datetime | None]

    analyses: Mapped[list[AnalysisRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    suggestions: Mapped[list[SuggestionRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    versions: Mapped[list[ScriptVersion]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="ScriptVersion.task_id",
    )
    locked_fragments: Mapped[list[LockedFragment]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    ai_operations: Mapped[list[AiOperation]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class CreativePreset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "creative_presets"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_creative_presets_owner_name"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AnalysisRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_analyses"
    __table_args__ = (Index("ix_task_analyses_task_sequence", "task_id", "sequence", unique=True),)

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("rewrite_tasks.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    member_notes: Mapped[str | None] = mapped_column(Text)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_identifier: Mapped[str] = mapped_column(String(160), nullable=False)

    task: Mapped[RewriteTask] = relationship(back_populates="analyses")


class SuggestionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_suggestions"
    __table_args__ = (Index("ix_task_suggestions_task_analysis", "task_id", "analysis_id"),)

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("rewrite_tasks.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_analyses.id", ondelete="CASCADE"), nullable=False
    )
    suggestion_key: Mapped[str] = mapped_column(String(80), nullable=False)
    analysis_issue_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), default=SuggestionPriority.OPTIONAL, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    impact_scope: Mapped[str] = mapped_column(Text, nullable=False)
    example: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(
        String(16), default=SuggestionDecision.PENDING, nullable=False
    )
    member_note: Mapped[str | None] = mapped_column(Text)

    task: Mapped[RewriteTask] = relationship(back_populates="suggestions")


class ScriptVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "script_versions"
    __table_args__ = (Index("ix_script_versions_task_created", "task_id", "created_at"),)

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("rewrite_tasks.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("script_versions.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(24), default=ValidationStatus.NOT_CHECKED, nullable=False
    )
    validation_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_current_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    task: Mapped[RewriteTask] = relationship(back_populates="versions", foreign_keys=[task_id])
    parent: Mapped[ScriptVersion | None] = relationship(
        remote_side="ScriptVersion.id", foreign_keys=[parent_id]
    )


class LockedFragment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locked_fragments"
    __table_args__ = (
        CheckConstraint("start_offset >= 0", name="start_offset_non_negative"),
        CheckConstraint("end_offset > start_offset", name="end_after_start"),
        Index("ix_locked_fragments_task_order", "task_id", "order_index", unique=True),
    )

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("rewrite_tasks.id", ondelete="CASCADE"), nullable=False
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("script_versions.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    task: Mapped[RewriteTask] = relationship(back_populates="locked_fragments")


class AiOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_operations"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "task_id",
            "kind",
            "idempotency_key",
            name="uq_ai_operations_scope_idempotency_key",
        ),
        Index("ix_ai_operations_owner_created", "owner_id", "created_at"),
        Index("ix_ai_operations_task_created", "task_id", "created_at"),
        Index(
            "uq_ai_operations_active_task",
            "task_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("rewrite_tasks.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=AiOperationStatus.RUNNING, nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}", nullable=False
    )
    task_name: Mapped[str] = mapped_column(
        String(200), default="", server_default="", nullable=False
    )
    initial_task_state: Mapped[str] = mapped_column(String(32), nullable=False)
    running_task_state: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_task_state: Mapped[str | None] = mapped_column(String(32))
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[UUID | None]
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    error_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[RewriteTask] = relationship(back_populates="ai_operations")


TASK_MODEL_TYPES = (
    RewriteTask,
    CreativePreset,
    AnalysisRecord,
    SuggestionRecord,
    ScriptVersion,
    LockedFragment,
    AiOperation,
)
