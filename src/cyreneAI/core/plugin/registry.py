from __future__ import annotations

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.plugin import PluginNotFoundError, PluginStateError
from cyreneAI.core.plugin.plugin_protocol import PluginExecutorProtocol
from cyreneAI.core.plugin.plugin_protocol import PluginEventExecutorProtocol
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginDefinition,
    PluginEvent,
    PluginEventDefinition,
    PluginLifecycleStatus,
    PluginStatusReport,
    PluginTaskDefinition,
)


class PluginRegistry:
    """
    插件注册器。
    """

    def __init__(self) -> None:
        self._definitions: dict[str, PluginDefinition] = {}
        self._executors: dict[str, PluginExecutorProtocol] = {}
        self._event_executors: dict[str, PluginEventExecutorProtocol] = {}
        self._command_to_plugin: dict[str, str] = {}
        self._statuses: dict[str, PluginStatusReport] = {}

    def register(
        self,
        definition: PluginDefinition,
        executor: PluginExecutorProtocol | None = None,
        event_executor: PluginEventExecutorProtocol | None = None,
    ) -> None:
        """
        注册插件。
        """
        if definition.plugin_id in self._definitions:
            raise ConflictError(f"该插件 {definition.plugin_id} 已注册")

        command_names = self._enabled_command_names(definition)
        for command_name in command_names:
            if command_name in self._command_to_plugin:
                raise ConflictError(f"该插件命令 {command_name} 已注册")

        self._definitions[definition.plugin_id] = definition
        self.record_status(_status_from_definition(definition))
        if executor is not None:
            self._executors[definition.plugin_id] = executor
        if event_executor is not None:
            self._event_executors[definition.plugin_id] = event_executor
        for command_name in command_names:
            self._command_to_plugin[command_name] = definition.plugin_id

    def unregister(self, plugin_id: str) -> None:
        """
        注销插件。
        """
        definition = self._definitions.get(plugin_id)
        if definition is None:
            raise PluginNotFoundError(f"该插件 {plugin_id} 不存在")

        for command_name in self._enabled_command_names(definition):
            self._command_to_plugin.pop(command_name, None)
        self._definitions.pop(plugin_id, None)
        self._executors.pop(plugin_id, None)
        self._event_executors.pop(plugin_id, None)
        self._statuses.pop(plugin_id, None)

    def get_definition(self, plugin_id: str) -> PluginDefinition:
        """
        获取插件定义。
        """
        definition = self._definitions.get(plugin_id)
        if definition is None:
            raise PluginNotFoundError(f"该插件 {plugin_id} 不存在")
        return definition

    def get_executor(self, plugin_id: str) -> PluginExecutorProtocol:
        """
        获取插件执行器。
        """
        self.get_definition(plugin_id)
        executor = self._executors.get(plugin_id)
        if executor is None:
            raise PluginStateError(f"该插件 {plugin_id} 未注册执行器")
        return executor

    def exists(self, plugin_id: str) -> bool:
        """
        判断插件是否存在。
        """
        return plugin_id in self._definitions

    def list_definitions(self) -> list[PluginDefinition]:
        """
        列出插件定义。
        """
        return list(self._definitions.values())

    def list_commands(self) -> list[PluginCommandDefinition]:
        """
        列出已启用插件命令。
        """
        commands: list[PluginCommandDefinition] = []
        for definition in self._definitions.values():
            if not definition.enabled:
                continue
            commands.extend(command for command in definition.commands if command.enabled)
        return commands

    def list_events(self) -> list[PluginEventDefinition]:
        """
        列出已启用插件事件订阅。
        """
        events: list[PluginEventDefinition] = []
        for definition in self._definitions.values():
            if not definition.enabled:
                continue
            events.extend(event for event in definition.events if event.enabled)
        return events

    def list_tasks(self) -> list[PluginTaskDefinition]:
        """
        列出已启用插件任务。
        """
        tasks: list[PluginTaskDefinition] = []
        for definition in self._definitions.values():
            if not definition.enabled:
                continue
            tasks.extend(task for task in definition.tasks if task.enabled)
        return tasks

    def record_status(self, status: PluginStatusReport) -> None:
        """
        记录插件生命周期状态。
        """
        self._statuses[status.plugin_id] = status

    def list_statuses(self) -> list[PluginStatusReport]:
        """
        列出插件生命周期状态。
        """
        statuses = dict(self._statuses)
        for plugin_id, definition in self._definitions.items():
            statuses.setdefault(plugin_id, _status_from_definition(definition))
        return list(statuses.values())

    def resolve_command(
        self,
        command_name: str,
    ) -> tuple[PluginDefinition, PluginCommandDefinition, PluginExecutorProtocol]:
        """
        根据命令名解析插件。
        """
        normalized_name = _normalize_command_name(command_name)
        plugin_id = self._command_to_plugin.get(normalized_name)
        if plugin_id is None:
            raise PluginNotFoundError(f"该插件命令 {command_name} 不存在")

        definition = self.get_definition(plugin_id)
        command = _find_command_definition(definition, normalized_name)
        if command is None:
            raise PluginStateError(f"该插件命令 {command_name} 状态异常")
        return definition, command, self.get_executor(plugin_id)

    def resolve_events(
        self,
        event: PluginEvent,
    ) -> list[tuple[PluginDefinition, PluginEventDefinition, PluginEventExecutorProtocol]]:
        """
        根据事件类型解析所有匹配的插件事件订阅。
        """
        resolved: list[
            tuple[PluginDefinition, PluginEventDefinition, PluginEventExecutorProtocol]
        ] = []
        for definition in self._definitions.values():
            if not definition.enabled:
                continue
            executor = self._event_executors.get(definition.plugin_id)
            if executor is None:
                continue
            for event_definition in definition.events:
                if not event_definition.enabled:
                    continue
                if event_definition.event_type == event.event_type:
                    resolved.append((definition, event_definition, executor))
        return resolved

    def _enabled_command_names(self, definition: PluginDefinition) -> set[str]:
        if not definition.enabled:
            return set()

        names: set[str] = set()
        for command in definition.commands:
            if not command.enabled:
                continue
            for name in (command.name, *command.aliases):
                normalized_name = _normalize_command_name(name)
                if normalized_name:
                    names.add(normalized_name)
        return names


def _find_command_definition(
    definition: PluginDefinition,
    command_name: str,
) -> PluginCommandDefinition | None:
    for command in definition.commands:
        if not command.enabled:
            continue
        names = {_normalize_command_name(command.name)}
        names.update(_normalize_command_name(alias) for alias in command.aliases)
        if command_name in names:
            return command
    return None


def _normalize_command_name(name: str) -> str:
    return name.strip().lower().removeprefix("/")


def _status_from_definition(definition: PluginDefinition) -> PluginStatusReport:
    return PluginStatusReport(
        plugin_id=definition.plugin_id,
        status=(
            PluginLifecycleStatus.ENABLED
            if definition.enabled
            else PluginLifecycleStatus.DISABLED
        ),
        enabled=definition.enabled,
        name=definition.name,
        version=definition.version,
    )
