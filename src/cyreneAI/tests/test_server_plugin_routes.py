from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import HTTPException

from cyreneAI.core.errors.plugin import PluginNotFoundError
from cyreneAI.core.schema.server import PluginPathRequestBody
from cyreneAI.server.routes import plugins as plugin_routes


class _FailingPluginAdminService:
    def _raise(self) -> None:
        raise PluginNotFoundError("plugin missing")

    def list_plugins(self) -> None:
        self._raise()

    def list_commands(self) -> None:
        self._raise()

    def list_events(self) -> None:
        self._raise()

    def list_tasks(self) -> None:
        self._raise()

    def list_middlewares(self) -> None:
        self._raise()

    def list_statuses(self) -> None:
        self._raise()

    def list_sources(self) -> None:
        self._raise()

    def runtime_capabilities(self) -> None:
        self._raise()

    def validate_path(self, body: PluginPathRequestBody) -> None:
        self._raise()

    def install_path(self, body: PluginPathRequestBody) -> None:
        self._raise()

    async def list_task_instances(self, **kwargs: Any) -> None:
        self._raise()

    async def cancel_task(self, task_id: str) -> None:
        self._raise()

    async def retry_task(self, task_id: str) -> None:
        self._raise()

    def get_plugin(self, plugin_id: str) -> None:
        self._raise()

    def inspect_plugin(self, plugin_id: str) -> None:
        self._raise()

    def disable_plugin(self, plugin_id: str) -> None:
        self._raise()

    def enable_plugin(self, plugin_id: str) -> None:
        self._raise()

    def reload_plugin(self, plugin_id: str) -> None:
        self._raise()

    def list_plugin_commands(self, plugin_id: str) -> None:
        self._raise()

    def list_plugin_events(self, plugin_id: str) -> None:
        self._raise()

    def list_plugin_tasks(self, plugin_id: str) -> None:
        self._raise()

    def list_plugin_middlewares(self, plugin_id: str) -> None:
        self._raise()

    def get_plugin_status(self, plugin_id: str) -> None:
        self._raise()

    def list_permission_audit(self, plugin_id: str) -> None:
        self._raise()

    async def list_storage_keys(self, plugin_id: str) -> None:
        self._raise()

    async def get_storage_value(self, plugin_id: str, key: str) -> None:
        self._raise()

    async def delete_storage_value(self, plugin_id: str, key: str) -> None:
        self._raise()

    async def clear_storage(self, plugin_id: str) -> None:
        self._raise()


_PluginRouteCall = Callable[[_FailingPluginAdminService], Awaitable[Any]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call_route",
    [
        lambda service: plugin_routes.list_plugins(service=service),
        lambda service: plugin_routes.list_plugin_commands(service=service),
        lambda service: plugin_routes.list_plugin_events(service=service),
        lambda service: plugin_routes.list_plugin_tasks(service=service),
        lambda service: plugin_routes.list_plugin_middlewares(service=service),
        lambda service: plugin_routes.list_plugin_statuses(service=service),
        lambda service: plugin_routes.list_plugin_sources(service=service),
        lambda service: plugin_routes.list_plugin_runtime_capabilities(
            service=service
        ),
        lambda service: plugin_routes.validate_plugin_path(
            PluginPathRequestBody(path="/plugins/demo"),
            service=service,
        ),
        lambda service: plugin_routes.install_plugin_path(
            PluginPathRequestBody(path="/plugins/demo"),
            service=service,
        ),
        lambda service: plugin_routes.list_plugin_task_instances(
            plugin_id="demo.hello",
            task_name="follow_up",
            status=["failed"],
            service=service,
        ),
        lambda service: plugin_routes.cancel_plugin_task("task-1", service=service),
        lambda service: plugin_routes.retry_plugin_task("task-1", service=service),
        lambda service: plugin_routes.get_plugin("demo.hello", service=service),
        lambda service: plugin_routes.inspect_plugin("demo.hello", service=service),
        lambda service: plugin_routes.disable_plugin("demo.hello", service=service),
        lambda service: plugin_routes.enable_plugin("demo.hello", service=service),
        lambda service: plugin_routes.reload_plugin("demo.hello", service=service),
        lambda service: plugin_routes.list_single_plugin_commands(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.list_single_plugin_events(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.list_single_plugin_tasks(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.list_single_plugin_middlewares(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.get_plugin_status(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.list_plugin_permission_audit(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.list_plugin_storage_keys(
            "demo.hello",
            service=service,
        ),
        lambda service: plugin_routes.get_plugin_storage_value(
            "demo.hello",
            "state",
            service=service,
        ),
        lambda service: plugin_routes.delete_plugin_storage_value(
            "demo.hello",
            "state",
            service=service,
        ),
        lambda service: plugin_routes.clear_plugin_storage(
            "demo.hello",
            service=service,
        ),
    ],
)
async def test_plugin_routes_map_cyrene_errors_to_http_errors(
    call_route: _PluginRouteCall,
) -> None:
    service = _FailingPluginAdminService()

    with pytest.raises(HTTPException) as exc_info:
        await call_route(service)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "plugin missing"
