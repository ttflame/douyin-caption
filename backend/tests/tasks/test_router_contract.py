import importlib
import inspect
from unittest.mock import AsyncMock

from app.modules.identity.router import get_current_member
from app.modules.tasks.router import TaskApiError, router, task_exception_handler

task_router_module = importlib.import_module("app.modules.tasks.router")
task_ai_operations_module = importlib.import_module("app.modules.tasks.ai_operations")

EXPECTED_METHODS = {
    ("GET", "/presets"),
    ("POST", "/presets"),
    ("PATCH", "/presets/{preset_id}"),
    ("DELETE", "/presets/{preset_id}"),
    ("GET", "/tasks"),
    ("POST", "/tasks"),
    ("GET", "/tasks/{task_id}"),
    ("PATCH", "/tasks/{task_id}"),
    ("POST", "/tasks/{task_id}/copy"),
    ("POST", "/tasks/{task_id}/archive"),
    ("POST", "/tasks/{task_id}/restore"),
    ("POST", "/tasks/{task_id}/analysis"),
    ("GET", "/tasks/{task_id}/analysis/{analysis_id}"),
    ("GET", "/tasks/{task_id}/analyses"),
    ("PATCH", "/tasks/{task_id}/analysis/{analysis_id}"),
    ("POST", "/tasks/{task_id}/suggestions"),
    ("GET", "/tasks/{task_id}/suggestions"),
    ("PATCH", "/tasks/{task_id}/suggestions/{suggestion_id}"),
    ("POST", "/tasks/{task_id}/first-draft"),
    ("POST", "/tasks/{task_id}/revisions"),
    ("GET", "/operations/{operation_id}"),
    ("GET", "/operations"),
    ("DELETE", "/operations/history"),
    ("POST", "/operations/{operation_id}/cancel"),
    ("POST", "/operations/{operation_id}/retry"),
    ("GET", "/tasks/{task_id}/versions"),
    ("GET", "/tasks/{task_id}/versions/{version_id}"),
    ("POST", "/tasks/{task_id}/versions/{version_id}/manual-edit"),
    ("POST", "/tasks/{task_id}/versions/compare"),
    ("POST", "/tasks/{task_id}/versions/{version_id}/locks"),
    ("DELETE", "/tasks/{task_id}/locks/{lock_id}"),
    ("GET", "/tasks/{task_id}/locks"),
    ("POST", "/tasks/{task_id}/versions/{version_id}/finalize"),
    ("GET", "/tasks/{task_id}/export"),
}


def test_router_matches_task_api_contract() -> None:
    actual = {
        (method, route.path)
        for route in router.routes
        for method in route.methods or set()
        if method != "HEAD"
    }

    assert actual == EXPECTED_METHODS


def test_every_route_requires_an_authenticated_member() -> None:
    for route in router.routes:
        dependencies = [dependency.call for dependency in route.dependant.dependencies]
        assert get_current_member in dependencies, route.path


def test_all_resource_queries_are_owner_scoped() -> None:
    source = inspect.getsource(task_router_module)

    assert "RewriteTask.owner_id == owner_id" in source
    assert "get_owned(task_id, owner_id)" in source
    assert "get_owned(preset_id, member.id)" in source
    assert "await _owned_task(session, task_id, member.id)" in source
    operation_source = inspect.getsource(task_ai_operations_module)
    assert "AiOperation.owner_id == owner_id" in operation_source


async def test_task_error_uses_shared_error_contract() -> None:
    response = await task_exception_handler(
        None,  # type: ignore[arg-type]
        TaskApiError("task_not_found", "Task was not found", 404),
    )

    assert response.status_code == 404
    assert response.body == (
        b'{"error":{"code":"task_not_found","message":"Task was not found","details":{}}}'
    )


async def test_commit_and_refresh_loads_server_generated_fields() -> None:
    session = AsyncMock()
    instance = object()

    await task_router_module._commit_and_refresh(session, instance)

    session.commit.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(instance)
