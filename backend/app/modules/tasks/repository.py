from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.domain import TaskState, VersionKind
from app.modules.tasks.models import CreativePreset, RewriteTask, ScriptVersion
from app.modules.tasks.schemas import CreativeSettings, PresetCreate, TaskCreate, TaskUpdate


class TaskNotFoundError(LookupError):
    pass


class PresetNotFoundError(LookupError):
    pass


class TaskRepository:
    """Persistence boundary that always scopes member content by owner ID."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, owner_id: UUID, payload: TaskCreate) -> RewriteTask:
        task = RewriteTask(
            owner_id=owner_id,
            name=payload.name,
            source_text=payload.source_text,
            creative_settings=payload.creative_settings.model_dump(mode="json"),
            state=TaskState.DRAFT,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_owned(self, task_id: UUID, owner_id: UUID) -> RewriteTask:
        task = await self.session.scalar(
            select(RewriteTask).where(
                RewriteTask.id == task_id,
                RewriteTask.owner_id == owner_id,
            )
        )
        if task is None:
            raise TaskNotFoundError("Task was not found")
        return task

    async def list_owned(
        self,
        owner_id: UUID,
        *,
        search: str | None = None,
        state: TaskState | None = None,
        archived: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[RewriteTask]:
        statement: Select[tuple[RewriteTask]] = select(RewriteTask).where(
            RewriteTask.owner_id == owner_id
        )
        if search:
            statement = statement.where(RewriteTask.name.ilike(f"%{search.strip()}%"))
        if state:
            statement = statement.where(RewriteTask.state == state)
        elif archived:
            statement = statement.where(RewriteTask.state == TaskState.ARCHIVED)
        else:
            statement = statement.where(RewriteTask.state != TaskState.ARCHIVED)
        statement = statement.order_by(RewriteTask.updated_at.desc()).offset(offset).limit(limit)
        return (await self.session.scalars(statement)).all()

    async def update_draft(self, task: RewriteTask, payload: TaskUpdate) -> RewriteTask:
        if task.state != TaskState.DRAFT:
            raise ValueError("Only draft tasks can change source text or creative settings")
        changes = payload.model_dump(exclude_unset=True)
        if "creative_settings" in changes:
            creative_settings = payload.creative_settings
            if creative_settings is not None:
                changes["creative_settings"] = creative_settings.model_dump(mode="json")
        for field_name, value in changes.items():
            setattr(task, field_name, value)
        await self.session.flush()
        return task

    async def copy(self, source: RewriteTask, owner_id: UUID) -> RewriteTask:
        copied = RewriteTask(
            owner_id=owner_id,
            name=f"{source.name} copy",
            source_text=source.source_text,
            creative_settings=dict(source.creative_settings),
            state=TaskState.DRAFT,
        )
        self.session.add(copied)
        await self.session.flush()
        return copied

    async def has_first_draft(self, task_id: UUID) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(ScriptVersion)
            .where(
                ScriptVersion.task_id == task_id,
                ScriptVersion.kind == VersionKind.FIRST_DRAFT,
            )
        )
        return bool(count)


class PresetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_owned(self, owner_id: UUID) -> Sequence[CreativePreset]:
        statement = (
            select(CreativePreset)
            .where(CreativePreset.owner_id == owner_id)
            .order_by(CreativePreset.updated_at.desc())
        )
        return (await self.session.scalars(statement)).all()

    async def get_owned(self, preset_id: UUID, owner_id: UUID) -> CreativePreset:
        preset = await self.session.scalar(
            select(CreativePreset).where(
                CreativePreset.id == preset_id,
                CreativePreset.owner_id == owner_id,
            )
        )
        if preset is None:
            raise PresetNotFoundError("Preset was not found")
        return preset

    async def create(self, owner_id: UUID, payload: PresetCreate) -> CreativePreset:
        preset = CreativePreset(
            owner_id=owner_id,
            name=payload.name,
            settings=payload.settings.model_dump(mode="json"),
        )
        self.session.add(preset)
        await self.session.flush()
        return preset

    async def replace_settings(
        self,
        preset: CreativePreset,
        *,
        name: str | None,
        settings: CreativeSettings | None,
    ) -> CreativePreset:
        if name is not None:
            preset.name = name
        if settings is not None:
            preset.settings = settings.model_dump(mode="json")
        await self.session.flush()
        return preset

    async def delete(self, preset: CreativePreset) -> None:
        await self.session.delete(preset)
        await self.session.flush()
